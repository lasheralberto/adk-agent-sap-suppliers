import uuid
import json
import re
import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.tools.sandbox.script_execution_tool import maybe_execute_matching_script
from agent.tools.mcp.sap_suppliers_tools import build_suppliers_query_payload


APP_NAME = "multi_agent_executor"
USER_ID = "user1"
_STREAM_CHUNK_SIZE = 180


def _to_plain_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, dict, list)):
        return value
    return str(value)


def _build_prompt_with_precomputed_context(question: str) -> str:
    precomputed = maybe_execute_matching_script(question)
    if precomputed is None:
        return question

    parts = [question]
    if precomputed is not None:
        parts.extend(
            [
                "",
                "[Contexto de script ejecutado automaticamente]",
                precomputed,
                "",
                "Usa este resultado para complementar tu respuesta final al usuario.",
            ]
        )

    return "\n".join(parts)


def _extract_text(content: object) -> str:
    if not content or not getattr(content, "parts", None):
        return ""

    chunks = []
    for part in content.parts:
        text = getattr(part, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _normalize_tool_call_record(record: object, fallback_agent: object | None = None) -> dict[str, object] | None:
    if not isinstance(record, dict):
        return None

    tool = record.get("tool") or record.get("name")
    if not tool:
        return None

    normalized: dict[str, object] = {"tool": _to_plain_value(tool)}

    agent = record.get("agent") or record.get("author") or fallback_agent
    if agent:
        normalized["agent"] = _to_plain_value(agent)

    args = record.get("args")
    if args is None:
        args = record.get("arguments")
    if args is not None:
        normalized["args"] = _to_plain_value(args)

    return normalized


def _extract_nested_tool_calls(value: object, fallback_agent: object | None = None) -> list[dict[str, object]]:
    nested_calls: list[dict[str, object]] = []

    if isinstance(value, dict):
        candidate = _normalize_tool_call_record(value, fallback_agent)
        if candidate:
            nested_calls.append(candidate)

        embedded = value.get("tool_calls")
        if isinstance(embedded, list):
            for item in embedded:
                nested_calls.extend(_extract_nested_tool_calls(item, fallback_agent))

        for nested_value in value.values():
            if isinstance(nested_value, (dict, list)):
                nested_calls.extend(_extract_nested_tool_calls(nested_value, fallback_agent))

    elif isinstance(value, list):
        for item in value:
            nested_calls.extend(_extract_nested_tool_calls(item, fallback_agent))

    return nested_calls


def _extract_tool_calls(content: object, event: object | None = None) -> list[dict[str, object]]:
    if not content or not getattr(content, "parts", None):
        return []

    calls: list[dict[str, object]] = []
    author = _to_plain_value(getattr(event, "author", None)) if event else None

    for part in content.parts:
        function_call = getattr(part, "function_call", None)
        if not function_call:
            function_response = getattr(part, "function_response", None)
            if not function_response:
                continue

            response_payload = (
                _to_plain_value(getattr(function_response, "response", None))
                or _to_plain_value(getattr(function_response, "output", None))
                or _to_plain_value(getattr(function_response, "result", None))
                or _to_plain_value(getattr(function_response, "content", None))
            )
            if response_payload is not None:
                calls.extend(_extract_nested_tool_calls(response_payload, fallback_agent=author))
            continue

        tool_name = _to_plain_value(getattr(function_call, "name", None))
        tool_args = _to_plain_value(
            getattr(function_call, "args", None) or getattr(function_call, "arguments", None)
        )

        if not tool_name:
            continue

        payload: dict[str, object] = {"tool": tool_name}
        if author:
            payload["agent"] = author
        if tool_args is not None:
            payload["args"] = tool_args

        calls.append(payload)

    return calls


def _append_unique_tool_calls(target: list[dict[str, object]], new_items: list[dict[str, object]]) -> None:
    seen = {
        (str(item.get("agent", "")), str(item.get("tool", "")), str(item.get("args", "")))
        for item in target
    }

    for item in new_items:
        signature = (
            str(item.get("agent", "")),
            str(item.get("tool", "")),
            str(item.get("args", "")),
        )
        if signature in seen:
            continue
        target.append(item)
        seen.add(signature)


def _collect_unique_tool_calls(
    target: list[dict[str, object]], new_items: list[dict[str, object]]
) -> list[dict[str, object]]:
    seen = {
        (str(item.get("agent", "")), str(item.get("tool", "")), str(item.get("args", "")))
        for item in target
    }
    added: list[dict[str, object]] = []

    for item in new_items:
        signature = (
            str(item.get("agent", "")),
            str(item.get("tool", "")),
            str(item.get("args", "")),
        )
        if signature in seen:
            continue
        target.append(item)
        added.append(item)
        seen.add(signature)

    return added


def _extract_delta(full_text: str, previous_text: str) -> str:
    if not full_text:
        return ""
    if not previous_text:
        return full_text
    if full_text.startswith(previous_text):
        return full_text[len(previous_text) :]
    if full_text == previous_text:
        return ""
    return full_text


def _stringify_tool_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False).strip()
        except TypeError:
            return str(value).strip()
    return str(value).strip()


def _split_stream_text(text: str, chunk_size: int = _STREAM_CHUNK_SIZE) -> list[str]:
    if not text:
        return []

    cleaned = text
    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: list[str] = []
    cursor = 0
    text_len = len(cleaned)
    while cursor < text_len:
        end = min(cursor + chunk_size, text_len)
        if end < text_len:
            split_at = cleaned.rfind(" ", cursor, end)
            if split_at > cursor + (chunk_size // 3):
                end = split_at + 1
        piece = cleaned[cursor:end]
        if piece:
            chunks.append(piece)
        cursor = end

    return chunks


def _extract_tool_output_events(content: object, event: object | None = None) -> list[dict[str, str]]:
    if not content or not getattr(content, "parts", None):
        return []

    author = str(_to_plain_value(getattr(event, "author", None)) or "") if event else ""

    outputs: list[dict[str, str]] = []
    for part in content.parts:
        function_response = getattr(part, "function_response", None)
        if not function_response:
            continue

        tool_name = str(_to_plain_value(getattr(function_response, "name", None)) or "tool")
        raw_output = (
            _to_plain_value(getattr(function_response, "response", None))
            or _to_plain_value(getattr(function_response, "output", None))
            or _to_plain_value(getattr(function_response, "result", None))
            or _to_plain_value(getattr(function_response, "content", None))
        )
        text_output = _stringify_tool_output(raw_output)
        if not text_output:
            continue

        outputs.append(
            {
                "agent": author,
                "tool": tool_name,
                "output": text_output,
            }
        )

    return outputs


def _extract_query_object_from_payload(payload: object) -> object | None:
    parsed = _try_parse_json_like(payload)

    if isinstance(parsed, dict):
        if isinstance(parsed.get("query"), (dict, list, str)):
            return parsed.get("query")
        if "field" in parsed and "args" in parsed:
            return parsed

    return None


def _extract_query_from_json_text(json_text: str) -> object | None:
    try:
        parsed = json.loads(json_text)
    except Exception:
        return None

    return _extract_query_object_from_payload(parsed)


def _extract_query_from_response_text(response_text: str) -> tuple[str, object | None]:
    if not response_text:
        return response_text, None

    cleaned_response = response_text
    query_value: object | None = None

    fenced_candidates = list(
        re.finditer(r"```json\s*(\{[\s\S]*?\})\s*```", response_text, flags=re.IGNORECASE)
    )
    for match in fenced_candidates:
        candidate = match.group(1)
        extracted = _extract_query_from_json_text(candidate)
        if extracted is None:
            continue
        query_value = extracted
        cleaned_response = cleaned_response.replace(match.group(0), "").strip()
        break

    if query_value is None:
        stripped = response_text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            extracted = _extract_query_from_json_text(stripped)
            if extracted is not None:
                query_value = extracted
                cleaned_response = ""

    cleaned_response = re.sub(r"\n{3,}", "\n\n", cleaned_response).strip()
    return cleaned_response, query_value


def _extract_query_events(content: object, event: object | None = None) -> list[object]:
    if not content or not getattr(content, "parts", None):
        return []

    queries: list[object] = []
    for part in content.parts:
        function_response = getattr(part, "function_response", None)
        if not function_response:
            continue

        tool_name = str(_to_plain_value(getattr(function_response, "name", None)) or "")
        if tool_name != "prepare_suppliers_query":
            continue

        raw_output = (
            _to_plain_value(getattr(function_response, "response", None))
            or _to_plain_value(getattr(function_response, "output", None))
            or _to_plain_value(getattr(function_response, "result", None))
            or _to_plain_value(getattr(function_response, "content", None))
        )
        query_value = _extract_query_object_from_payload(raw_output)
        if query_value is not None:
            queries.append(query_value)

    return queries


def _is_suppliers_agent_call(call: dict[str, object]) -> bool:
    return str(call.get("tool", "")) == "suppliers_agent"


def _extract_request_from_call(call: dict[str, object], fallback_request: str = "") -> str:
    args = call.get("args")
    if isinstance(args, dict):
        request = args.get("request")
        if isinstance(request, str) and request.strip():
            return request.strip()
    return (fallback_request or "").strip()


def _normalize_query_for_call_args(query_value: object) -> dict[str, object] | None:
    parsed = _try_parse_json_like(query_value)
    if not isinstance(parsed, dict):
        return None

    if "query" in parsed and isinstance(parsed.get("query"), dict):
        parsed = parsed["query"]
        if not isinstance(parsed, dict):
            return None

    top_field = str(parsed.get("field", "")).strip().upper()
    raw_args = parsed.get("args")
    if not isinstance(raw_args, list) or not raw_args:
        return None

    normalized_items: list[dict[str, object]] = []
    for item in raw_args:
        if not isinstance(item, dict):
            continue
        normalized_item: dict[str, object] = {
            "low": item.get("low", ""),
            "option": item.get("option", "EQ"),
            "sign": item.get("sign", "I"),
        }

        raw_limit = item.get("limit")
        if isinstance(raw_limit, str) and raw_limit.strip().isdigit():
            raw_limit = int(raw_limit.strip())
        if isinstance(raw_limit, int) and raw_limit > 0:
            normalized_item["limit"] = raw_limit

        item_field = str(item.get("field", "")).strip().upper()
        if item_field:
            normalized_item["field"] = item_field
        elif top_field:
            normalized_item["field"] = top_field

        normalized_items.append(normalized_item)

    if not normalized_items:
        return None

    return {"args": normalized_items}


def _build_query_for_request(request_text: str) -> dict[str, object] | None:
    if not request_text or not request_text.strip():
        return None

    infer_with_llm = os.getenv("SUPPLIERS_RUNNER_INFERENCE", "1").strip().lower() not in {"0", "false", "no", "off"}
    provider_for_inference = os.getenv("LLM_PROVIDER") if infer_with_llm else ""

    try:
        payload = build_suppliers_query_payload(
            question=request_text.strip(),
            llm_provider=provider_for_inference,
        )
    except Exception:
        return None

    return _normalize_query_for_call_args(payload.get("query"))


def _inject_query_into_suppliers_calls(
    tool_calls: list[dict[str, object]],
    query_value: object | None,
    fallback_request: str = "",
) -> bool:
    injected = False

    for call in tool_calls:
        if not _is_suppliers_agent_call(call):
            continue

        args = call.get("args")
        if not isinstance(args, dict):
            args = {}

        request_text = _extract_request_from_call(call, fallback_request)
        if request_text:
            args["request"] = request_text

        normalized_query = _normalize_query_for_call_args(query_value)
        if normalized_query is None:
            normalized_query = _build_query_for_request(request_text)

        if normalized_query is None:
            call["args"] = args
            continue

        args["query"] = normalized_query
        call["args"] = args
        injected = True

    return injected


def _try_parse_json_like(value: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    if text[0] not in ("{", "["):
        return value

    try:
        return json.loads(text)
    except Exception:
        return value


def _coerce_score(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return None
    return None


def _extract_confidence_score(value: object) -> float | None:
    parsed = _try_parse_json_like(value)

    direct_score = _coerce_score(parsed)
    if direct_score is not None:
        return direct_score

    if isinstance(parsed, dict):
        for key in ("confidence", "score"):
            if key in parsed:
                score_value = _extract_confidence_score(parsed.get(key))
                if score_value is not None:
                    return score_value

        for nested in parsed.values():
            score_value = _extract_confidence_score(nested)
            if score_value is not None:
                return score_value

    if isinstance(parsed, list):
        for item in parsed:
            score_value = _extract_confidence_score(item)
            if score_value is not None:
                return score_value

    return None


def _extract_tool_score_events(content: object, event: object | None = None) -> list[dict[str, object]]:
    if not content or not getattr(content, "parts", None):
        return []

    author = str(_to_plain_value(getattr(event, "author", None)) or "") if event else ""
    scores: list[dict[str, object]] = []

    for part in content.parts:
        function_response = getattr(part, "function_response", None)
        if not function_response:
            continue

        tool_name = str(_to_plain_value(getattr(function_response, "name", None)) or "")
        if tool_name.lower() != "intent_router":
            continue

        raw_output = (
            _to_plain_value(getattr(function_response, "response", None))
            or _to_plain_value(getattr(function_response, "output", None))
            or _to_plain_value(getattr(function_response, "result", None))
            or _to_plain_value(getattr(function_response, "content", None))
        )

        score_value = _extract_confidence_score(raw_output)
        if score_value is None:
            continue

        scores.append({
            "agent": author,
            "tool": tool_name,
            "score": score_value,
        })

    return scores


async def _run_once(message_text: str, session_id: str, agent: object) -> dict[str, object]:
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )

    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=session_service,
    )
    message = types.Content(role="user", parts=[types.Part(text=message_text)])

    last_text = ""
    tool_calls: list[dict[str, object]] = []
    query_value: object | None = None
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=message,
    ):
        _append_unique_tool_calls(tool_calls, _extract_tool_calls(event.content, event))

        for item in _extract_query_events(event.content, event):
            query_value = item

        current_text = _extract_text(event.content)
        if current_text:
            cleaned_current_text, query_from_text = _extract_query_from_response_text(current_text)
            last_text = cleaned_current_text
            if query_from_text is not None:
                query_value = query_from_text

        if event.is_final_response():
            final_text = _extract_text(event.content)
            if final_text:
                cleaned_final_text, query_from_text = _extract_query_from_response_text(final_text)
                if query_from_text is not None:
                    query_value = query_from_text
                _inject_query_into_suppliers_calls(tool_calls, query_value, message_text)
                result = {"response": cleaned_final_text, "tool_calls": tool_calls}
                return result

    _inject_query_into_suppliers_calls(tool_calls, query_value, message_text)
    result = {"response": last_text, "tool_calls": tool_calls}
    return result


async def stream_agent(question: str, agent: object):
    """Async generator that yields text chunks from agent events."""
    prompt_text = _build_prompt_with_precomputed_context(question)
    request_id = uuid.uuid4().hex

    session_service = InMemorySessionService()
    session_id = f"stream-{request_id}"
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )

    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=session_service,
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt_text)])

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=message,
    ):
        text = _extract_text(event.content)
        if text:
            yield text


async def run_agent_streaming(question: str, agent: object):
    """Async generator that yields payload chunks with response/tool_calls."""
    prompt_text = _build_prompt_with_precomputed_context(question)
    request_id = uuid.uuid4().hex
    session1_id = f"session1-{request_id}"
    session2_id = f"session2-{request_id}"

    async def _stream_attempt(message_text: str, session_id: str):
        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id,
        )

        runner = Runner(
            agent=agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        message = types.Content(role="user", parts=[types.Part(text=message_text)])

        last_full_text = ""
        tool_calls: list[dict[str, object]] = []
        query_value: object | None = None
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=message,
        ):
            payload: dict[str, object] = {}

            added_calls = _collect_unique_tool_calls(
                tool_calls, _extract_tool_calls(event.content, event)
            )
            if added_calls:
                payload["tool_calls"] = tool_calls

            score_events = _extract_tool_score_events(event.content, event)
            if score_events:
                payload["score"] = score_events[-1].get("score")

            query_events = _extract_query_events(event.content, event)
            if query_events:
                query_value = query_events[-1]

            full_text = _extract_text(event.content)
            cleaned_full_text, query_from_text = _extract_query_from_response_text(full_text)
            if query_from_text is not None:
                query_value = query_from_text

            injected_query = _inject_query_into_suppliers_calls(tool_calls, query_value, message_text)
            if injected_query:
                payload["tool_calls"] = tool_calls

            delta = _extract_delta(cleaned_full_text, last_full_text)
            if delta:
                last_full_text = cleaned_full_text
                payload["response"] = delta

            if not payload:
                continue

            response_text = str(payload.get("response", ""))
            if not response_text:
                yield payload
                continue

            response_chunks = _split_stream_text(response_text)
            for index, response_chunk in enumerate(response_chunks):
                chunk_payload: dict[str, object] = {"response": response_chunk}
                if index == 0 and payload.get("tool_calls"):
                    chunk_payload["tool_calls"] = payload["tool_calls"]
                if index == 0 and payload.get("score") is not None:
                    chunk_payload["score"] = payload["score"]
                yield chunk_payload

    got_response = False
    async for payload in _stream_attempt(prompt_text, session1_id):
        if str(payload.get("response", "")).strip():
            got_response = True
        yield payload

    if got_response:
        return

    retry_prompt = (
        f"{prompt_text}\n\n"
        "[Retry obligatorio]\n"
        "La ejecucion anterior no devolvio texto final. Reintenta coordinando a todos los agentes necesarios. "
        "Debes producir una respuesta final en texto para el usuario, usando answer_agent. "
        "Solo pregunta si falta un recurso externo (por ejemplo API key)."
    )

    retry_got_response = False
    async for payload in _stream_attempt(retry_prompt, session2_id):
        if str(payload.get("response", "")).strip():
            retry_got_response = True
        yield payload

    if not retry_got_response:
        yield {
            "response": "No se pudo producir una respuesta final en texto. Reintenta la consulta o proporciona mas contexto.",
            "tool_calls": [],
        }


async def run_agent(question: str, agent: object) -> dict[str, object]:
    prompt_text = _build_prompt_with_precomputed_context(question)
    request_id = uuid.uuid4().hex
    session1_id = f"session1-{request_id}"
    session2_id = f"session2-{request_id}"

    first_attempt = await _run_once(prompt_text, session1_id, agent)
    if str(first_attempt.get("response", "")).strip():
        return first_attempt

    retry_prompt = (
        f"{prompt_text}\n\n"
        "[Retry obligatorio]\n"
        "La ejecucion anterior no devolvio texto final. Reintenta coordinando a todos los agentes necesarios. "
        "Debes producir una respuesta final en texto para el usuario, usando answer_agent. "
        "Solo pregunta si falta un recurso externo (por ejemplo API key)."
    )
    second_attempt = await _run_once(retry_prompt, session2_id, agent)
    if str(second_attempt.get("response", "")).strip():
        return second_attempt

    return {
        "response": "No se pudo producir una respuesta final en texto. Reintenta la consulta o proporciona mas contexto.",
        "tool_calls": [],
    }
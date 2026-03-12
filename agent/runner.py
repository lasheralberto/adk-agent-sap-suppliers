import uuid
import json

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from tools.script_execution_tool import maybe_execute_matching_script


APP_NAME = "multi_agent_executor"
USER_ID = "user1"
_CODE_EXECUTION_AUTHORS = {"code_programmer", "generic_scripts_agent", "script_generator_agent"}


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


def _extract_tool_calls(content: object, event: object | None = None) -> list[dict[str, object]]:
    if not content or not getattr(content, "parts", None):
        return []

    calls: list[dict[str, object]] = []
    author = _to_plain_value(getattr(event, "author", None)) if event else None

    for part in content.parts:
        function_call = getattr(part, "function_call", None)
        if not function_call:
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


def _extract_tool_output_events(content: object, event: object | None = None) -> list[dict[str, str]]:
    if not content or not getattr(content, "parts", None):
        return []

    author = str(_to_plain_value(getattr(event, "author", None)) or "") if event else ""
    if author not in _CODE_EXECUTION_AUTHORS:
        return []

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
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=message,
    ):
        _append_unique_tool_calls(tool_calls, _extract_tool_calls(event.content, event))

        current_text = _extract_text(event.content)
        if current_text:
            last_text = current_text

        if event.is_final_response():
            final_text = _extract_text(event.content)
            if final_text:
                return {"response": final_text, "tool_calls": tool_calls}

    return {"response": last_text, "tool_calls": tool_calls}


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
        streamed_tool_outputs: set[tuple[str, str, str]] = set()

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
                payload["tool_calls"] = added_calls

            streamed_messages: list[str] = []
            for item in _extract_tool_output_events(event.content, event):
                signature = (item["agent"], item["tool"], item["output"])
                if signature in streamed_tool_outputs:
                    continue
                streamed_tool_outputs.add(signature)
                streamed_messages.append(
                    f"[{item['agent']} -> {item['tool']}]\n{item['output']}"
                )

            full_text = _extract_text(event.content)
            delta = _extract_delta(full_text, last_full_text)
            if delta:
                streamed_messages.append(delta)
                last_full_text = full_text

            if streamed_messages:
                payload["response"] = "\n\n".join(streamed_messages)

            if payload:
                yield payload

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
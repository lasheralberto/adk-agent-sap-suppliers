import asyncio
import json
import queue
import threading
from typing import Generator

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from agent.app import build_orchestrator
from agent.runner import run_agent, run_agent_streaming


app = Flask(__name__)
CORS(app)

HEARTBEAT_INTERVAL_SECONDS = 5


@app.get("/health")
def health() -> tuple[dict, int]:
    return {"status": "ok"}, 200


def _sse(data: dict[str, object], event: str = "chunk") -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_generator(question: str, agent: object) -> Generator[str, None, None]:
    """Bridges the async run_agent_streaming generator into a sync Flask generator via queue."""
    q: queue.Queue = queue.Queue()
    _DONE = object()
    _ERROR = object()

    async def _consume() -> None:
        try:
            async for chunk in run_agent_streaming(question, agent):
                q.put(chunk)
        except Exception as exc:  # noqa: BLE001
            q.put((_ERROR, str(exc)))
        finally:
            q.put(_DONE)

    threading.Thread(target=lambda: asyncio.run(_consume()), daemon=True).start()

    # Emit periodic heartbeat events so proxies/clients keep the stream open on long-running tasks.
    while True:
        try:
            item = q.get(timeout=HEARTBEAT_INTERVAL_SECONDS)
        except queue.Empty:
            yield _sse({"response": "", "tool_calls": []}, event="heartbeat")
            continue
        if item is _DONE:
            yield _sse({"response": "", "tool_calls": []}, event="done")
            break
        if isinstance(item, tuple) and item[0] is _ERROR:
            yield _sse({"response": str(item[1]), "tool_calls": []}, event="error")
            break
        yield _sse(item)


@app.post("/ask")
def ask_agent() -> Response | tuple[dict, int]:
    data = request.get_json(silent=True) or {}
    question = data.get("question")
    model = data.get("model")
    llm_provider = data.get("llm_provider")
    stream_param = data.get("stream", False)
    
    # Handle both string ("True"/"False") and boolean values
    if isinstance(stream_param, str):
        stream = stream_param.lower() in ("true", "1", "yes")
    else:
        stream = bool(stream_param)

    if not isinstance(question, str) or not question.strip():
        return {"error": "Field 'question' must be a non-empty string."}, 400

    if not isinstance(model, str) or not model.strip():
        return {"error": "Field 'model' must be a non-empty string."}, 400

    if not isinstance(llm_provider, str) or not llm_provider.strip():
        return {"error": "Field 'llm_provider' must be a non-empty string."}, 400

    try:
        orchestrator = build_orchestrator(
            llm_provider=llm_provider.strip().lower(),
            model_name=model.strip(),
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    if stream:
        return Response(
            stream_with_context(_stream_generator(question.strip(), orchestrator)),
            content_type="text/event-stream",
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
            },
        )

    result = asyncio.run(run_agent(question.strip(), orchestrator))
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
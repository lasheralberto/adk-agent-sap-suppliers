import asyncio
import json
import queue
import threading
from typing import Generator

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from agent.app import orchestrator
from agent.runner import run_agent, stream_agent


app = Flask(__name__)
CORS(app)


@app.get("/health")
def health() -> tuple[dict, int]:
    return {"status": "ok"}, 200


def _sse(data: str, event: str = "chunk") -> str:
    return f"event: {event}\ndata: {json.dumps({'text': data})}\n\n"


def _stream_generator(question: str) -> Generator[str, None, None]:
    """Bridges the async stream_agent generator into a sync Flask generator via queue."""
    q: queue.Queue = queue.Queue()
    _DONE = object()
    _ERROR = object()

    async def _consume() -> None:
        try:
            async for chunk in stream_agent(question, orchestrator):
                q.put(chunk)
        except Exception as exc:  # noqa: BLE001
            q.put((_ERROR, str(exc)))
        finally:
            q.put(_DONE)

    threading.Thread(target=lambda: asyncio.run(_consume()), daemon=True).start()

    while True:
        item = q.get()
        if item is _DONE:
            yield _sse("", event="done")
            break
        if isinstance(item, tuple) and item[0] is _ERROR:
            yield _sse(item[1], event="error")
            break
        yield _sse(item)


@app.post("/ask")
def ask_agent() -> Response | tuple[dict, int]:
    data = request.get_json(silent=True) or {}
    question = data.get("question")
    stream = bool(data.get("stream", False))

    if not isinstance(question, str) or not question.strip():
        return {"error": "Field 'question' must be a non-empty string."}, 400

    if stream:
        return Response(
            stream_with_context(_stream_generator(question.strip())),
            content_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    result = asyncio.run(run_agent(question.strip(), orchestrator))
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
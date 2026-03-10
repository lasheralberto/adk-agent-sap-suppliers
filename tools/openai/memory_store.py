import io
import os
from datetime import datetime, timezone
from typing import Any

from tools.openai.vector_store import ensure_vector_store, get_openai_client, update_vector_store


DEFAULT_TOP_K = 3
DEFAULT_SUMMARY_MAX_CHARS = 700


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _extract_search_text(item: Any) -> str:
    chunks: list[str] = []
    for chunk in getattr(item, "content", []) or []:
        text_value = ""
        if isinstance(chunk, dict):
            text_obj = chunk.get("text")
            if isinstance(text_obj, dict):
                text_value = _to_text(text_obj.get("value"))
            else:
                text_value = _to_text(text_obj)
        else:
            text_obj = getattr(chunk, "text", None)
            text_value = _to_text(getattr(text_obj, "value", text_obj))

        if text_value:
            chunks.append(text_value)

    if chunks:
        return "\n".join(chunks)
    return _to_text(getattr(item, "text", ""))


def retrieve_similar_memories(question: str, top_k: int | None = None) -> list[str]:
    query = _to_text(question)
    if not query:
        return []

    try:
        store_id = ensure_vector_store()
        client = get_openai_client()
        if top_k is None:
            top_k_raw = _to_text(os.getenv("MEMORY_TOP_K", str(DEFAULT_TOP_K)))
            top_k = int(top_k_raw) if top_k_raw.isdigit() else DEFAULT_TOP_K

        results = client.vector_stores.search(
            vector_store_id=store_id,
            query=query,
            max_num_results=top_k,
        )
    except Exception:
        return []

    memories: list[str] = []
    for item in getattr(results, "data", []) or []:
        text = _extract_search_text(item)
        if text:
            memories.append(text)

    return memories


def save_memory(question: str, final_answer: str) -> bool:
    question_text = _to_text(question)
    answer_text = _to_text(final_answer)
    if not question_text or not answer_text:
        return False

    summary = _clip(answer_text, DEFAULT_SUMMARY_MAX_CHARS)
    payload = {
        "question": question_text,
        "answer_summary": summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    content = (
        f"Question: {payload['question']}\n"
        f"Answer Summary: {payload['answer_summary']}\n"
        f"Created At: {payload['created_at']}"
    )

    memory_file = io.BytesIO(content.encode("utf-8"))
    memory_file.name = f"memory-{int(datetime.now(timezone.utc).timestamp())}.txt"

    try:
        store_id = ensure_vector_store()
        client = get_openai_client()
    except Exception:
        return False

    try:
        client.vector_stores.files.upload_and_poll(
            vector_store_id=store_id,
            file=memory_file,
        )
    except Exception:
        try:
            uploaded_file = client.files.create(file=memory_file, purpose="assistants")
            client.vector_stores.files.create(
                vector_store_id=store_id,
                file_id=uploaded_file.id,
            )
        except Exception:
            return False

    try:
        update_vector_store(
            vector_store_id=store_id,
            metadata={
                "source": "orchestrator-memory",
                "last_memory_at": payload["created_at"],
            },
        )
    except Exception:
        pass

    return True

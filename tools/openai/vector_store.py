import os
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI


DEFAULT_VECTOR_STORE_NAME = "orchestrator-memory"


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_vector_store_id() -> str | None:
    return os.getenv("VECTOR_STORE_ID")


def update_vector_store(
    vector_store_id: str,
    name: str | None = None,
    metadata: dict[str, str] | None = None,
    expires_after_days: int | None = None,
) -> Any:
    client = get_openai_client()

    payload: dict[str, Any] = {}
    if name:
        payload["name"] = name
    if metadata:
        payload["metadata"] = metadata
    if expires_after_days and expires_after_days > 0:
        payload["expires_after"] = {
            "anchor": "last_active_at",
            "days": expires_after_days,
        }

    if not payload:
        return client.vector_stores.retrieve(vector_store_id=vector_store_id)
    return client.vector_stores.update(vector_store_id=vector_store_id, **payload)


def ensure_vector_store() -> str:
    client = get_openai_client()
    vector_store_id = get_vector_store_id()
    expires_after_days_raw = os.getenv("MEMORY_EXPIRY_DAYS", "").strip()
    expires_after_days = int(expires_after_days_raw) if expires_after_days_raw.isdigit() else None

    if not vector_store_id:
        create_payload: dict[str, Any] = {"name": DEFAULT_VECTOR_STORE_NAME}
        if expires_after_days and expires_after_days > 0:
            create_payload["expires_after"] = {
                "anchor": "last_active_at",
                "days": expires_after_days,
            }
        vector_store = client.vector_stores.create(**create_payload)
        os.environ["VECTOR_STORE_ID"] = vector_store.id
        return vector_store.id

    update_vector_store(
        vector_store_id=vector_store_id,
        name=DEFAULT_VECTOR_STORE_NAME,
        metadata={
            "source": "orchestrator-memory",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        expires_after_days=expires_after_days,
    )
    return vector_store_id

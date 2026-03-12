import json
from typing import Any, Optional

from tools.memory.providers.in_memory import InMemoryProvider


class RedisProvider:
    """Phase 1 adapter.

    If redis dependency or connection is unavailable, it falls back to in-process memory.
    """

    def __init__(self, url: str | None = None) -> None:
        self._fallback = InMemoryProvider()
        self._client = None

        if not url:
            return

        try:
            import redis  # type: ignore

            self._client = redis.Redis.from_url(url)
            self._client.ping()
        except Exception:
            self._client = None

    def get(self, key: str) -> Optional[Any]:
        if self._client is None:
            return self._fallback.get(key)

        value = self._client.get(key)
        if value is None:
            return None

        decoded = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        try:
            return json.loads(decoded)
        except Exception:
            return decoded

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if self._client is None:
            self._fallback.set(key, value, ttl=ttl)
            return

        payload = json.dumps(value, ensure_ascii=True, default=str)
        if isinstance(ttl, int) and ttl > 0:
            self._client.setex(key, ttl, payload)
        else:
            self._client.set(key, payload)

    def delete(self, key: str) -> None:
        if self._client is None:
            self._fallback.delete(key)
            return
        self._client.delete(key)

    def search(self, query: str, top_k: int = 5) -> list[Any]:
        if self._client is None:
            return self._fallback.search(query, top_k=top_k)

        safe_query = str(query or "").strip().lower()
        if not safe_query:
            return []

        safe_top_k = top_k if isinstance(top_k, int) and top_k > 0 else 5
        results: list[Any] = []
        cursor = 0

        while True:
            cursor, keys = self._client.scan(cursor=cursor, count=100)
            for key in keys or []:
                value = self.get(key.decode("utf-8") if isinstance(key, bytes) else str(key))
                if value is not None and safe_query in str(value).lower():
                    results.append(value)
                    if len(results) >= safe_top_k:
                        return results

            if cursor == 0:
                break

        return results

import time
from typing import Any, Optional


class InMemoryProvider:
    def __init__(self) -> None:
        self._db: dict[str, tuple[Any, Optional[float]]] = {}

    def _is_expired(self, key: str) -> bool:
        item = self._db.get(key)
        if not item:
            return False

        _, expires_at = item
        if expires_at is None:
            return False
        return time.time() >= expires_at

    def _purge_if_expired(self, key: str) -> None:
        if self._is_expired(key):
            self._db.pop(key, None)

    def get(self, key: str) -> Optional[Any]:
        self._purge_if_expired(key)
        item = self._db.get(key)
        if not item:
            return None
        value, _ = item
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expires_at = None
        if isinstance(ttl, int) and ttl > 0:
            expires_at = time.time() + ttl
        self._db[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._db.pop(key, None)

    def search(self, query: str, top_k: int = 5) -> list[Any]:
        safe_query = str(query or "").strip().lower()
        if not safe_query:
            return []

        safe_top_k = top_k if isinstance(top_k, int) and top_k > 0 else 5
        matches: list[Any] = []
        for key in list(self._db.keys()):
            self._purge_if_expired(key)

        for value, _ in self._db.values():
            if safe_query in str(value).lower():
                matches.append(value)
                if len(matches) >= safe_top_k:
                    break

        return matches

import json
import sqlite3
import time
from typing import Any, Optional


class SQLiteProvider:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at INTEGER
            )
            """
        )
        self._conn.commit()

    def _now(self) -> int:
        return int(time.time())

    def _purge_expired(self) -> None:
        self._conn.execute(
            "DELETE FROM memory_kv WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (self._now(),),
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[Any]:
        self._purge_expired()
        row = self._conn.execute("SELECT value FROM memory_kv WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        raw_value = row[0]
        try:
            return json.loads(raw_value)
        except Exception:
            return raw_value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        payload = json.dumps(value, ensure_ascii=True, default=str)
        expires_at = self._now() + ttl if isinstance(ttl, int) and ttl > 0 else None
        self._conn.execute(
            """
            INSERT INTO memory_kv (key, value, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at
            """,
            (key, payload, expires_at),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM memory_kv WHERE key = ?", (key,))
        self._conn.commit()

    def search(self, query: str, top_k: int = 5) -> list[Any]:
        self._purge_expired()
        safe_query = str(query or "").strip()
        if not safe_query:
            return []

        safe_top_k = top_k if isinstance(top_k, int) and top_k > 0 else 5
        rows = self._conn.execute(
            "SELECT value FROM memory_kv WHERE value LIKE ? LIMIT ?",
            (f"%{safe_query}%", safe_top_k),
        ).fetchall()

        parsed: list[Any] = []
        for row in rows:
            raw_value = row[0]
            try:
                parsed.append(json.loads(raw_value))
            except Exception:
                parsed.append(raw_value)
        return parsed

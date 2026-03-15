from typing import Any, Optional

from agent.tools.memory.factory import build_memory_provider
from agent.tools.memory.interface import IMemoryProvider


class MemoryTool:
    def __init__(self, memory_provider: Optional[IMemoryProvider] = None):
        self.memory = memory_provider or build_memory_provider()

    def remember(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.memory.set(key, value, ttl=ttl)

    def recall(self, key: str) -> Any:
        return self.memory.get(key)

    def forget(self, key: str) -> None:
        self.memory.delete(key)

    def search(self, query: str, top_k: int = 5) -> list[Any]:
        return self.memory.search(query, top_k=top_k)

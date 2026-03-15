from typing import Any, Optional, Protocol


class IKeyValueMemoryProvider(Protocol):
    def get(self, key: str) -> Optional[Any]:
        ...

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ...

    def delete(self, key: str) -> None:
        ...


class IVectorMemoryProvider(Protocol):
    def search(self, query: str, top_k: int = 5) -> list[Any]:
        ...


class IMemoryProvider(IKeyValueMemoryProvider, IVectorMemoryProvider, Protocol):
    pass

from typing import Any, Dict, Optional

from .openai_provider import OpenAIProvider
from .in_memory import InMemoryProvider
from .redis_provider import RedisProvider
from .sqlite_provider import SQLiteProvider
from .pinecone_provider import PineconeProvider


class ProviderFactory:
    @staticmethod
    def get_provider(provider: str, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        name = (provider or "").lower()
        if name in ("openai", "openaiprovider"):
            return OpenAIProvider(**cfg)
        if name in ("pinecone", "pineconeprovider"):
            return PineconeProvider(**cfg)
        if name in ("redis", "redisprovider"):
            return RedisProvider(**cfg)
        if name in ("sqlite", "sqliteprovider"):
            return SQLiteProvider(**cfg)
        if name in ("langextract", "langextractprovider"):
            try:
                from ...improvers.langextract.langextract_provider import LangExtractProvider
            except ModuleNotFoundError:
                raise ModuleNotFoundError(
                    "LangExtract provider requires the 'langextract' package. Install it or choose another provider."
                )
            return LangExtractProvider(**cfg)
        # fallback to in-memory
        return InMemoryProvider()


class ProviderWrapper:
    def __init__(self, provider: str | object, config: Optional[Dict[str, Any]] = None) -> None:
        if isinstance(provider, str):
            self._impl = ProviderFactory.get_provider(provider, config)
        else:
            # assume already instantiated provider-like object
            self._impl = provider

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        return getattr(self._impl, "set")(key, value, ttl)

    def get(self, key: str) -> Optional[Any]:
        return getattr(self._impl, "get")(key)

    def delete(self, key: str) -> None:
        return getattr(self._impl, "delete")(key)

    def search(self, query: str, top_k: int = 5) -> list[Any]:
        return getattr(self._impl, "search")(query, top_k)

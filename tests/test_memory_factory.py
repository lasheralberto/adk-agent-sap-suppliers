import os
import unittest

from tools.memory.factory import build_memory_provider
from tools.memory.providers.in_memory import InMemoryProvider
from tools.memory.providers.sqlite_provider import SQLiteProvider


class TestMemoryFactory(unittest.TestCase):
    def setUp(self):
        self._original_provider = os.environ.get("MEMORY_PROVIDER")
        self._original_sqlite_path = os.environ.get("SQLITE_MEMORY_DB_PATH")

    def tearDown(self):
        if self._original_provider is None:
            os.environ.pop("MEMORY_PROVIDER", None)
        else:
            os.environ["MEMORY_PROVIDER"] = self._original_provider

        if self._original_sqlite_path is None:
            os.environ.pop("SQLITE_MEMORY_DB_PATH", None)
        else:
            os.environ["SQLITE_MEMORY_DB_PATH"] = self._original_sqlite_path

        build_memory_provider(reset=True)

    def test_default_is_inmemory(self):
        os.environ.pop("MEMORY_PROVIDER", None)
        provider = build_memory_provider(reset=True)
        self.assertIsInstance(provider, InMemoryProvider)

    def test_sqlite_provider_selected(self):
        os.environ["MEMORY_PROVIDER"] = "sqlite"
        os.environ["SQLITE_MEMORY_DB_PATH"] = ":memory:"
        provider = build_memory_provider(reset=True)
        self.assertIsInstance(provider, SQLiteProvider)

    def test_unknown_provider_falls_back_to_inmemory(self):
        os.environ["MEMORY_PROVIDER"] = "does-not-exist"
        provider = build_memory_provider(reset=True)
        self.assertIsInstance(provider, InMemoryProvider)


if __name__ == "__main__":
    unittest.main()

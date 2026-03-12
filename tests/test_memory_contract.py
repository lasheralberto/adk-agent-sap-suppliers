import tempfile
import unittest

from tools.memory.providers.in_memory import InMemoryProvider
from tools.memory.providers.sqlite_provider import SQLiteProvider


class _MemoryContractTests:
    def build_provider(self):
        raise NotImplementedError

    def test_set_get_delete(self):
        provider = self.build_provider()

        provider.set("user:1", {"name": "Ana"})
        self.assertEqual(provider.get("user:1"), {"name": "Ana"})

        provider.delete("user:1")
        self.assertIsNone(provider.get("user:1"))

    def test_search(self):
        provider = self.build_provider()

        provider.set("a", {"topic": "python memory patterns"})
        provider.set("b", {"topic": "sql basics"})
        provider.set("c", {"topic": "python adapters"})

        results = provider.search("python", top_k=2)
        self.assertEqual(len(results), 2)


class TestInMemoryProviderContract(_MemoryContractTests, unittest.TestCase):
    def build_provider(self):
        return InMemoryProvider()


class TestSQLiteProviderContract(_MemoryContractTests, unittest.TestCase):
    def build_provider(self):
        tmp_dir = tempfile.mkdtemp(prefix="memory-provider-")
        db_path = f"{tmp_dir}/memory.db"
        return SQLiteProvider(db_path=db_path)


if __name__ == "__main__":
    unittest.main()

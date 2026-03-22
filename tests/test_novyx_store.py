import unittest
from unittest.mock import patch

from change_intelligence.novyx_store import NovyxConfig, NovyxStore


class NovyxStoreTests(unittest.TestCase):
    def test_store_skips_source_when_client_signature_does_not_support_it(self):
        captured = {}

        class FakeNovyx:
            def __init__(self, api_key, api_url="https://example.test", timeout=30, agent_id=None):
                captured["api_key"] = api_key
                captured["api_url"] = api_url
                captured["timeout"] = timeout
                captured["agent_id"] = agent_id

        with patch("change_intelligence.novyx_store.Novyx", FakeNovyx):
            store = NovyxStore(
                NovyxConfig(
                    api_key="nram_test",
                    api_url="https://example.test",
                    agent_id="change-intelligence",
                    source="ignored-source",
                )
            )

        self.assertIsInstance(store.client, FakeNovyx)
        self.assertEqual(captured["api_key"], "nram_test")
        self.assertEqual(captured["api_url"], "https://example.test")
        self.assertEqual(captured["agent_id"], "change-intelligence")


if __name__ == "__main__":
    unittest.main()

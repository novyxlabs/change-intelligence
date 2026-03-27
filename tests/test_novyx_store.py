import unittest

from change_intelligence.novyx_store import NovyxConfig, NovyxStore


class FakeNovyxClient:
    def __init__(self):
        self.agent_id = "change-intelligence"
        self.calls = []

    def list_spaces(self):
        return {"spaces": [{"space_id": "cs_test", "name": "change-intelligence"}]}

    def remember(self, observation, **kwargs):
        self.calls.append({"observation": observation, "kwargs": kwargs})
        return {"id": "mem_123"}

    def memories(self, **kwargs):
        return []

    def audit(self, **kwargs):
        return []


class NovyxStoreTests(unittest.TestCase):
    def test_remember_passes_metadata_and_context_through_sdk(self):
        client = FakeNovyxClient()
        store = NovyxStore(NovyxConfig(api_key="test"), client=client)

        result = store._remember(
            "metadata repro",
            tags=["analysis-run"],
            context="repo#1",
            importance=5,
            metadata={"top_doc": "errors.md"},
        )

        self.assertEqual(result["id"], "mem_123")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["observation"], "metadata repro")
        self.assertEqual(call["kwargs"]["context"], "repo#1")
        self.assertEqual(call["kwargs"]["metadata"], {"top_doc": "errors.md"})
        self.assertEqual(call["kwargs"]["space_id"], "cs_test")
        self.assertIsNone(call["kwargs"].get("conflict_strategy"))

    def test_record_feedback_can_pass_lww_conflict_strategy(self):
        client = FakeNovyxClient()
        store = NovyxStore(NovyxConfig(api_key="test"), client=client)

        store.record_feedback(
            repository="repo/test",
            pull_request_number=12,
            command="/ci correct",
            commenter="blake",
            comment_url="https://example.test/comment/1",
            conflict_strategy="lww",
        )

        remember_calls = [call for call in client.calls if "kwargs" in call]
        self.assertTrue(remember_calls)
        self.assertEqual(remember_calls[0]["kwargs"]["conflict_strategy"], "lww")

    def test_record_historical_analysis_uses_lww_conflict_strategy(self):
        client = FakeNovyxClient()
        store = NovyxStore(NovyxConfig(api_key="test"), client=client)

        store.record_historical_analysis(
            repository="repo/test",
            pull_request_number=12,
            changed_files=["src/errors.ts"],
            top_doc="errors.md",
            top_confidence=91,
            confidence_tier="high-confidence",
            comment_url="https://example.test/comment/1",
            restore_metadata=True,
        )

        remember_calls = [call for call in client.calls if "kwargs" in call]
        self.assertTrue(remember_calls)
        self.assertEqual(remember_calls[0]["kwargs"]["conflict_strategy"], "lww")

    def test_record_historical_analysis_can_reuse_original_observation(self):
        client = FakeNovyxClient()
        store = NovyxStore(NovyxConfig(api_key="test"), client=client)

        store.record_historical_analysis(
            repository="repo/test",
            pull_request_number=12,
            changed_files=["src/errors.ts"],
            top_doc="errors.md",
            top_confidence=91,
            confidence_tier="high-confidence",
            comment_url="https://example.test/comment/1",
            restore_metadata=True,
            original_observation="Analysis run for repo/test#12@abc123: high-confidence",
        )

        remember_calls = [call for call in client.calls if "kwargs" in call]
        self.assertTrue(remember_calls)
        self.assertEqual(
            remember_calls[0]["observation"],
            "Analysis run for repo/test#12@abc123: high-confidence",
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from change_intelligence.feedback import parse_feedback_command, process_feedback_event
from change_intelligence.metrics import compute_metrics


class FakeStore:
    def __init__(self, feedback, runs):
        self.feedback = feedback
        self.runs = runs

    def list_memories(self, tags, limit=500):
        if tags == ["ci-feedback"]:
            return self.feedback
        if tags == ["analysis-run"]:
            return self.runs
        return []


class FakeFeedbackStore:
    def __init__(self):
        self.recorded = []

    def record_feedback(self, **kwargs):
        self.recorded.append(kwargs)
        return {"feedback": kwargs["command"].replace("/ci ", "")}


class FeedbackAndMetricsTests(unittest.TestCase):
    def test_parse_feedback_command(self):
        self.assertEqual(parse_feedback_command("/ci correct"), "/ci correct")
        self.assertEqual(parse_feedback_command("Looks good\n/ci wrong-doc"), "/ci wrong-doc")
        self.assertIsNone(parse_feedback_command("thanks"))

    def test_process_feedback_event_requires_trusted_commenter(self):
        import change_intelligence.feedback as module

        class FakeGitHub:
            def issue_comments(self, owner, repo, issue_number, installation_id):
                return [
                    {
                        "html_url": "https://github.com/acme/app/pull/1#issuecomment-1",
                        "body": "<!-- change-intelligence-comment -->\nReport",
                        "user": {"login": "change-intelligence-bot"},
                        "author_association": "NONE",
                    },
                    {
                        "html_url": "https://github.com/acme/app/pull/1#issuecomment-2",
                        "body": "/ci correct",
                        "user": {"login": "outsider"},
                        "author_association": "NONE",
                    },
                ]

            def user_permission(self, owner, repo, username, installation_id):
                return None

        original_from_env = module.GitHubClient.from_env
        try:
            module.GitHubClient.from_env = classmethod(lambda cls: FakeGitHub())
            result = process_feedback_event(
                '{"repository":{"full_name":"acme/app"},"issue":{"number":1,"pull_request":{"url":"present"}},"comment":{"body":"/ci correct","html_url":"https://github.com/acme/app/pull/1#issuecomment-2","user":{"login":"outsider"}}}',
                FakeFeedbackStore(),
            )
        finally:
            module.GitHubClient.from_env = original_from_env

        self.assertTrue(result["ignored"])
        self.assertEqual(result["reason"], "untrusted-feedback")

    def test_process_feedback_event_accepts_trusted_commenter(self):
        import change_intelligence.feedback as module

        class FakeGitHub:
            def issue_comments(self, owner, repo, issue_number, installation_id):
                return [
                    {
                        "html_url": "https://github.com/acme/app/pull/1#issuecomment-1",
                        "body": "<!-- change-intelligence-comment -->\nReport",
                        "user": {"login": "change-intelligence-bot"},
                        "author_association": "NONE",
                    },
                    {
                        "html_url": "https://github.com/acme/app/pull/1#issuecomment-2",
                        "body": "/ci correct",
                        "user": {"login": "blake"},
                        "author_association": "OWNER",
                    },
                ]

            def user_permission(self, owner, repo, username, installation_id):
                return "admin"

        store = FakeFeedbackStore()
        original_from_env = module.GitHubClient.from_env
        try:
            module.GitHubClient.from_env = classmethod(lambda cls: FakeGitHub())
            result = process_feedback_event(
                '{"repository":{"full_name":"acme/app"},"issue":{"number":1,"pull_request":{"url":"present"}},"comment":{"body":"/ci correct","html_url":"https://github.com/acme/app/pull/1#issuecomment-2","user":{"login":"blake"}}}',
                store,
            )
        finally:
            module.GitHubClient.from_env = original_from_env

        self.assertTrue(result["ok"])
        self.assertEqual(store.recorded[0]["commenter"], "blake")

    def test_compute_metrics(self):
        store = FakeStore(
            feedback=[
                {"tags": ["ci-feedback", "wrong-doc"], "context": "novyxlabs/novyx-core#1", "created_at": "2026-03-18T10:00:00Z"},
                {"tags": ["ci-feedback", "correct"], "context": "novyxlabs/novyx-core#1", "created_at": "2026-03-18T11:00:00Z"},
                {"tags": ["ci-feedback", "wrong-doc"], "context": "novyxlabs/novyx-core#2", "created_at": "2026-03-18T12:00:00Z"},
                {"tags": ["ci-feedback", "missed-doc"], "context": "novyxlabs/novyx-mcp#3"},
            ],
            runs=[
                {"tags": ["analysis-run", "suppressed"], "context": "novyxlabs/novyx-core#1", "created_at": "2026-03-18T09:00:00Z"},
                {"tags": ["analysis-run", "commented"], "context": "novyxlabs/novyx-core#1", "created_at": "2026-03-18T11:00:00Z"},
                {"tags": ["analysis-run", "commented"], "context": "novyxlabs/novyx-core#2"},
                {"tags": ["analysis-run", "suppressed"], "context": "novyxlabs/novyx-mcp#3"},
            ],
        )
        metrics = compute_metrics(store)
        self.assertEqual(metrics["feedback_total"], 3)
        self.assertEqual(metrics["analysis_runs"], 3)
        self.assertEqual(metrics["unique_prs"], 3)
        self.assertAlmostEqual(metrics["top_1_rate"], 1 / 3)
        self.assertAlmostEqual(metrics["comment_rate"], 2 / 3)
        self.assertAlmostEqual(metrics["false_positive_rate"], 1 / 2)
        self.assertEqual(metrics["proof_window"]["remaining_to_minimum"], 17)
        self.assertFalse(metrics["proof_window"]["ready_for_case_study"])
        self.assertEqual(metrics["proof_window"]["unique_prs"], 3)
        self.assertEqual(metrics["repositories"]["novyxlabs/novyx-core"]["analysis_runs"], 2)
        self.assertAlmostEqual(metrics["repositories"]["novyxlabs/novyx-core"]["top_1_rate"], 1 / 2)
        self.assertEqual(metrics["repositories"]["novyxlabs/novyx-mcp"]["analysis_runs"], 1)


if __name__ == "__main__":
    unittest.main()

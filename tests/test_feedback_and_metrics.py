import unittest

from change_intelligence.feedback import parse_feedback_command, process_feedback_event
from change_intelligence.metrics import (
    compute_metrics,
    render_case_studies_markdown,
    render_founder_digest_markdown,
)


class FakeStore:
    def __init__(self, feedback, runs):
        self.feedback = feedback
        self.runs = runs
        self.audit_entries = [
            {"operation": "CREATE", "artifact_id": "mem_feedback_1", "timestamp": "2026-03-18T12:00:00Z"}
        ]
        self.eval_history_payload = {
            "history": [{"health_score": 97, "timestamp": "2026-03-18T12:00:00Z"}]
        }
        self.eval_drift_payload = {"drift_score": 0.03, "days": 7}

    def list_memories(self, tags, limit=500):
        if tags == ["ci-feedback"]:
            return self.feedback
        if tags == ["analysis-run"]:
            return self.runs
        return []

    def evaluation_history(self, limit=10):
        return self.eval_history_payload

    def evaluation_drift(self, days=7):
        return self.eval_drift_payload

    def feedback_audit(self, limit=50):
        return self.audit_entries[:limit]


class BrokenObservabilityStore(FakeStore):
    def evaluation_history(self, limit=10):
        raise RuntimeError("eval-history unavailable")

    def evaluation_drift(self, days=7):
        raise RuntimeError("eval-drift unavailable")

    def feedback_audit(self, limit=50):
        raise RuntimeError("audit unavailable")


class FakeFeedbackStore:
    def __init__(self):
        self.recorded = []

    def record_feedback(self, **kwargs):
        self.recorded.append(kwargs)
        return {
            "feedback": kwargs["command"].replace("/ci ", ""),
            "graph_update": {"updated": True, "predicate": "documents"},
            "audit_entries": [{"operation": "CREATE", "artifact_id": "mem_1"}],
        }


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
        self.assertTrue(result["graph_update"]["updated"])
        self.assertEqual(result["audit_entries"][0]["operation"], "CREATE")

    def test_compute_metrics(self):
        store = FakeStore(
            feedback=[
                {"tags": ["ci-feedback", "wrong-doc"], "context": "novyxlabs/novyx-core#1", "created_at": "2026-03-18T10:00:00Z"},
                {"tags": ["ci-feedback", "correct"], "context": "novyxlabs/novyx-core#1", "created_at": "2026-03-18T11:00:00Z"},
                {"tags": ["ci-feedback", "wrong-doc"], "context": "novyxlabs/novyx-core#2", "created_at": "2026-03-18T12:00:00Z"},
                {"tags": ["ci-feedback", "missed-doc"], "context": "novyxlabs/novyx-mcp#3"},
            ],
            runs=[
                {
                    "tags": ["analysis-run", "silent", "suppressed"],
                    "context": "novyxlabs/novyx-core#1",
                    "created_at": "2026-03-18T09:00:00Z",
                    "metadata": {
                        "repository": "novyxlabs/novyx-core",
                        "pull_request_number": 1,
                        "changed_files": ["src/billing/createCheckoutSession.ts"],
                        "top_doc": "billing.md",
                        "top_confidence": 42,
                        "confidence_tier": "silent",
                    },
                },
                {
                    "tags": ["analysis-run", "review-recommended", "commented"],
                    "context": "novyxlabs/novyx-core#1",
                    "created_at": "2026-03-18T11:00:00Z",
                    "metadata": {
                        "repository": "novyxlabs/novyx-core",
                        "pull_request_number": 1,
                        "changed_files": ["src/billing/createCheckoutSession.ts"],
                        "top_doc": "billing.md",
                        "top_confidence": 84,
                        "confidence_tier": "review-recommended",
                        "github_comment_status": "failed",
                        "auth_mode": "token",
                    },
                },
                {
                    "tags": ["analysis-run", "high-confidence", "commented"],
                    "context": "novyxlabs/novyx-core#2",
                    "metadata": {
                        "repository": "novyxlabs/novyx-core",
                        "pull_request_number": 2,
                        "changed_files": ["src/api/search.py"],
                        "top_doc": "search-reference.md",
                        "top_confidence": 96,
                        "confidence_tier": "high-confidence",
                    },
                },
                {
                    "tags": ["analysis-run", "silent", "suppressed"],
                    "context": "novyxlabs/novyx-mcp#3",
                    "metadata": {
                        "repository": "novyxlabs/novyx-mcp",
                        "pull_request_number": 3,
                        "changed_files": ["memory/health/cache.py"],
                        "top_doc": "memory-health.md",
                        "top_confidence": 33,
                        "confidence_tier": "silent",
                    },
                },
            ],
        )
        metrics = compute_metrics(store)
        self.assertEqual(metrics["feedback_total"], 3)
        self.assertEqual(metrics["analysis_runs"], 3)
        self.assertEqual(metrics["unique_prs"], 3)
        self.assertAlmostEqual(metrics["top_1_rate"], 1 / 3)
        self.assertAlmostEqual(metrics["comment_rate"], 2 / 3)
        self.assertAlmostEqual(metrics["false_positive_rate"], 1 / 2)
        self.assertAlmostEqual(metrics["confidence_tiers"]["high_confidence_rate"], 1 / 3)
        self.assertAlmostEqual(metrics["confidence_tiers"]["silent_rate"], 1 / 3)
        self.assertEqual(metrics["side_effects"]["counts"]["comment_failures"], 1)
        self.assertEqual(metrics["side_effects"]["counts"]["token_auth_runs"], 1)
        self.assertTrue(any("GitHub comment writes failed" in item["message"] for item in metrics["alerts"]))
        self.assertEqual(metrics["trend"]["top_1_rate"], "flat")
        self.assertEqual(metrics["case_studies"][0]["top_doc"], "billing.md")
        self.assertEqual(metrics["proof_window"]["remaining_to_minimum"], 17)
        self.assertFalse(metrics["proof_window"]["ready_for_case_study"])
        self.assertEqual(metrics["proof_window"]["unique_prs"], 3)
        self.assertEqual(metrics["repositories"]["novyxlabs/novyx-core"]["analysis_runs"], 2)
        self.assertAlmostEqual(metrics["repositories"]["novyxlabs/novyx-core"]["top_1_rate"], 1 / 2)
        self.assertEqual(metrics["repositories"]["novyxlabs/novyx-mcp"]["analysis_runs"], 1)
        self.assertEqual(metrics["novyx"]["audit"]["entry_count"], 1)
        self.assertEqual(metrics["novyx"]["eval"]["history_count"], 1)
        self.assertEqual(metrics["novyx"]["eval"]["drift"]["drift_score"], 0.03)

    def test_render_case_studies_markdown(self):
        markdown = render_case_studies_markdown(
            [
                {
                    "repository": "novyxlabs/novyx-core",
                    "pull_request_number": 12,
                    "changed_file": "src/billing/createCheckoutSession.ts",
                    "top_doc": "billing.md",
                    "top_confidence": 84,
                    "confidence_tier": "review-recommended",
                    "area": "src/billing",
                    "created_at": "2026-03-22T12:01:00Z",
                }
            ]
        )
        self.assertIn("# Change Intelligence Case Studies", markdown)
        self.assertIn("novyxlabs/novyx-core #12", markdown)
        self.assertIn("`billing.md`", markdown)

    def test_render_founder_digest_markdown(self):
        metrics = {
            "analysis_runs": 12,
            "feedback_total": 7,
            "top_1_rate": 0.75,
            "false_positive_rate": 0.2,
            "trend": {
                "top_1_rate": "up 10 pts",
                "false_positive_rate": "down 5 pts",
                "miss_rate": "flat",
            },
            "confidence_tiers": {
                "counts": {
                    "high_confidence": 4,
                    "review_recommended": 5,
                    "silent": 3,
                }
            },
            "case_studies": [
                {
                    "repository": "novyxlabs/novyx-core",
                    "pull_request_number": 12,
                    "changed_file": "src/billing/createCheckoutSession.ts",
                    "top_doc": "billing.md",
                    "top_confidence": 84,
                    "confidence_tier": "review-recommended",
                }
            ],
            "hotspots": [
                {
                    "area": "src/billing",
                    "repository": "novyxlabs/novyx-core",
                    "runs": 5,
                    "wrong_doc": 1,
                    "missed_doc": 1,
                    "false_positive_rate": 0.25,
                    "miss_rate": 0.2,
                    "top_doc": "billing.md",
                }
            ],
            "proof_window": {"remaining_to_minimum": 8},
        }
        markdown = render_founder_digest_markdown(metrics)
        self.assertIn("# Change Intelligence Founder Digest", markdown)
        self.assertIn("Best accepted example this week came from `novyxlabs/novyx-core` PR `#12`.", markdown)
        self.assertIn("- Top-1 trend: `up 10 pts`", markdown)
        self.assertIn("Noisiest area right now is `src/billing`", markdown)

    def test_compute_metrics_surfaces_novyx_errors(self):
        store = BrokenObservabilityStore(feedback=[], runs=[])
        metrics = compute_metrics(store)
        self.assertEqual(metrics["novyx"]["eval"]["history_error"], "eval-history unavailable")
        self.assertEqual(metrics["novyx"]["eval"]["drift_error"], "eval-drift unavailable")
        self.assertEqual(metrics["novyx"]["audit"]["error"], "audit unavailable")


if __name__ == "__main__":
    unittest.main()

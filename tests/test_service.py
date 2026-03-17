import json
from pathlib import Path
import unittest

from change_intelligence.analysis import analyze_patch
from change_intelligence.github_client import COMMENT_MARKER
from change_intelligence.service import ServiceConfig, process_github_event


FIXTURES = Path(__file__).resolve().parent.parent / "test" / "fixtures"


class FakeNovyxStore:
    def __init__(self):
        self.calls = []
        self.learned = False

    def recall_patterns(self, query: str, limit: int = 5):
        self.calls.append(("recall", query, limit, self.learned))
        if self.learned:
            return [
                {
                    "id": "mem_accepted",
                    "observation": "src/billing/createCheckoutSession.ts changed -> docs/billing.md was accepted after merge",
                    "score": 0.97,
                    "tags": ["change-pattern", "accepted"],
                    "metadata": {"relative_path": "billing.md"},
                }
            ]
        return [
            {
                "id": "mem_predicted",
                "observation": "src/billing/createCheckoutSession.ts changed -> docs/billing.md was predicted for docs review",
                "score": 0.66,
                "tags": ["change-pattern", "predicted"],
                "metadata": {"relative_path": "billing.md"},
            }
        ]

    def rank_signals(self, repository, changed_files):
        self.calls.append(("rank", repository, list(changed_files), self.learned))
        if self.learned:
            return {"billing.md": {"graph_hits": 2, "accepted_hits": 2, "rejected_hits": 0}}
        return {"billing.md": {"graph_hits": 1, "accepted_hits": 0, "rejected_hits": 0}}

    def learn_from_merge(self, repository, pull_request_number, changed_files, predicted_docs, actual_docs):
        self.learned = True
        self.calls.append(
            ("learn", repository, pull_request_number, list(changed_files), list(predicted_docs), list(actual_docs))
        )
        return {"accepted": ["billing.md"], "rejected": [], "missed": []}

    def record_analysis(self, repository, pull_request_number, changed_files, recommendations):
        self.calls.append(
            ("record", repository, pull_request_number, list(changed_files), len(recommendations))
        )
        return {"trace_id": "trace_123"}


class FakeGitHubClient:
    def __init__(self, patch: str):
        self.patch = patch
        self.comments = []
        self.docs_requests = []
        self.file_requests = []
        self.deleted_comments = []

    def repo_docs(self, owner, repo, docs_path, ref, installation_id):
        self.docs_requests.append((owner, repo, docs_path, ref, installation_id))
        return [
            {
                "path": "docs/billing.md",
                "relative_path": "billing.md",
                "content": (
                    "# Billing Guide\n\n## createCheckoutSession\n\nUse `createCheckoutSession` to start checkout."
                ),
            },
            {
                "path": "docs/onboarding.md",
                "relative_path": "onboarding.md",
                "content": "# Onboarding\n\nSet up your workspace.",
            },
        ]

    def pull_request_files(self, owner, repo, pull_number, installation_id):
        self.file_requests.append((owner, repo, pull_number, installation_id))
        return [
            {
                "filename": "src/billing/createCheckoutSession.ts",
                "patch": "\n".join(self.patch.splitlines()[4:]),
            },
            {
                "filename": "docs/billing.md",
                "patch": "@@ -1,2 +1,3 @@\n # Billing Guide\n+\n+Updated coupon support.",
            },
        ]

    def upsert_issue_comment(self, owner, repo, issue_number, installation_id, body):
        self.comments.append((owner, repo, issue_number, installation_id, body))
        return {"id": 99, "body": f"{COMMENT_MARKER}\n{body}"}

    def clear_issue_comment(self, owner, repo, issue_number, installation_id):
        self.deleted_comments.append((owner, repo, issue_number, installation_id))
        return {"id": 99, "deleted": True}


class ChangeIntelligenceServiceTests(unittest.TestCase):
    def test_analyze_patch_ranks_billing_doc(self):
        patch = (FIXTURES / "sample.patch").read_text(encoding="utf8")
        docs_root = FIXTURES / "repo" / "docs"
        result = analyze_patch(
            patch,
            docs_root,
            learned_signals={"billing.md": {"graph_hits": 2, "accepted_hits": 1, "rejected_hits": 0}},
            patterns=[
                {
                    "observation": "src/billing/createCheckoutSession.ts changed -> docs/billing.md was accepted after merge",
                    "score": 0.9,
                }
            ],
        )

        self.assertEqual(result["recommendations"][0]["relative_path"], "billing.md")
        self.assertGreaterEqual(result["recommendations"][0]["confidence"], 60)
        self.assertIn("createCheckoutSession", result["summary"]["changed_symbols"])
        self.assertIn("target_heading", result["recommendations"][0]["draft_patch"])

    def test_process_github_event_learns_on_merge_and_posts_high_confidence_comment(self):
        patch = (FIXTURES / "sample.patch").read_text(encoding="utf8")
        body = json.dumps(
            {
                "action": "closed",
                "repository": {"full_name": "acme/app"},
                "pull_request": {
                    "number": 42,
                    "merged_at": "2026-03-17T00:00:00Z",
                    "head": {"sha": "abc123"},
                },
            }
        )
        store = FakeNovyxStore()
        github_client = FakeGitHubClient(patch)
        result = process_github_event(
            body,
            None,
            ServiceConfig(
                docs_root=FIXTURES / "repo" / "docs",
                github_client=github_client,
                novyx_store=store,
                confidence_threshold=60,
            ),
        )

        self.assertEqual(result["status_code"], 200)
        self.assertFalse(result["payload"]["comment_suppressed"])
        self.assertEqual(result["payload"]["comment"]["id"], 99)
        self.assertEqual(result["payload"]["recommendations"][0]["relative_path"], "billing.md")
        self.assertGreaterEqual(result["payload"]["recommendations"][0]["confidence"], 60)
        self.assertEqual(result["payload"]["learning_feedback"]["accepted"], ["billing.md"])
        self.assertTrue(any(call[0] == "learn" for call in store.calls))
        self.assertEqual(github_client.comments[0][2], 42)

    def test_process_github_event_stays_silent_below_threshold(self):
        patch = (FIXTURES / "sample.patch").read_text(encoding="utf8")
        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/app"},
                "pull_request": {"number": 42, "patch": patch},
            }
        )

        class LowSignalStore(FakeNovyxStore):
            def rank_signals(self, repository, changed_files):
                self.calls.append(("rank", repository, list(changed_files), self.learned))
                return {}

            def recall_patterns(self, query: str, limit: int = 5):
                self.calls.append(("recall", query, limit, self.learned))
                return []

        store = LowSignalStore()
        github_client = FakeGitHubClient(patch)
        result = process_github_event(
            body,
            None,
            ServiceConfig(
                docs_root=FIXTURES / "repo" / "docs",
                novyx_store=store,
                github_client=github_client,
                confidence_threshold=60,
            ),
        )

        self.assertEqual(result["status_code"], 200)
        self.assertTrue(result["payload"]["comment_suppressed"])
        self.assertEqual(result["payload"]["comment"]["deleted"], True)
        self.assertIsNone(result["payload"]["comment_body"])
        self.assertEqual(github_client.deleted_comments[0][2], 42)

    def test_invalid_signature_is_rejected(self):
        result = process_github_event(
            "{}",
            "sha256=bad",
            ServiceConfig(docs_root=FIXTURES / "repo" / "docs", webhook_secret="secret"),
        )
        self.assertEqual(result["status_code"], 401)


if __name__ == "__main__":
    unittest.main()

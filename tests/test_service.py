import json
import tempfile
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

    def record_analysis(self, repository, pull_request_number, changed_files, recommendations, **kwargs):
        self.calls.append(
            ("record", repository, pull_request_number, list(changed_files), len(recommendations), kwargs)
        )
        return {
            "trace_id": "trace_123",
            "evaluation": {"health_score": 98, "drift_score": 0.02},
            "audit_entries": [{"operation": "CREATE", "artifact_id": "mem_run_1"}],
        }


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
        record_call = next(call for call in store.calls if call[0] == "record")
        self.assertEqual(record_call[5]["action"], "closed")
        self.assertEqual(record_call[5]["release_notes"]["recommended_docs"][0], "billing.md")
        self.assertEqual(record_call[5]["release_notes"]["confidence"], result["payload"]["release_notes"]["confidence"])
        self.assertEqual(github_client.comments[0][2], 42)
        self.assertEqual(result["payload"]["trace"]["evaluation"]["health_score"], 98)

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

    def test_missing_patch_without_github_access_returns_bad_request(self):
        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/app"},
                "pull_request": {"number": 42},
            }
        )
        result = process_github_event(
            body,
            None,
            ServiceConfig(docs_root=FIXTURES / "repo" / "docs"),
        )
        self.assertEqual(result["status_code"], 400)

    def test_process_github_event_applies_repository_ownership_rules(self):
        patch = """diff --git a/src/billing/retries.py b/src/billing/retries.py
index 1111111..2222222 100644
--- a/src/billing/retries.py
+++ b/src/billing/retries.py
@@ -0,0 +1,2 @@
+def sync_invoice_retry_window():
+    return True
"""

        class OwnershipGitHubClient(FakeGitHubClient):
            def repo_docs(self, owner, repo, docs_path, ref, installation_id):
                self.docs_requests.append((owner, repo, docs_path, ref, installation_id))
                return [
                    {
                        "path": "docs/billing.md",
                        "relative_path": "billing.md",
                        "content": "# Billing\n\nOverview of invoices and retry policy.",
                    },
                    {
                        "path": "docs/ops.md",
                        "relative_path": "ops.md",
                        "content": "# Operations\n\n## sync_invoice_retry_window\n\nThis worker updates the retry window.",
                    },
                ]

            def pull_request_files(self, owner, repo, pull_number, installation_id):
                self.file_requests.append((owner, repo, pull_number, installation_id))
                return [
                    {
                        "filename": "src/billing/retries.py",
                        "patch": "\n".join(patch.splitlines()[4:]),
                    }
                ]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(
                {
                    "repositories": {
                        "acme/app": [
                            {
                                "code_prefix": "src/billing/",
                                "doc_prefix": "billing.md",
                                "score_boost": 32,
                                "description": "Billing code should update the billing guide.",
                            }
                        ]
                    }
                },
                handle,
            )
            rules_path = Path(handle.name)
        self.addCleanup(lambda: rules_path.unlink(missing_ok=True))

        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/app"},
                "pull_request": {"number": 42, "patch": patch},
            }
        )
        github_client = OwnershipGitHubClient(patch)
        result = process_github_event(
            body,
            None,
            ServiceConfig(
                docs_root=FIXTURES / "repo" / "docs",
                github_client=github_client,
                confidence_threshold=60,
                ownership_rules_path=rules_path,
            ),
        )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["payload"]["recommendations"][0]["relative_path"], "billing.md")
        self.assertTrue(
            any("Ownership rule matched" in line for line in result["payload"]["recommendations"][0]["evidence"])
        )

    def test_process_github_event_reports_changed_routes_and_prefers_surface_docs(self):
        patch = """diff --git a/src/api/search.py b/src/api/search.py
index 1111111..2222222 100644
--- a/src/api/search.py
+++ b/src/api/search.py
@@ -10,0 +11,4 @@
+@router.get("/v1/search")
+def search():
+    pass
+app.post("/v1/search/reindex")
"""

        class SurfaceGitHubClient(FakeGitHubClient):
            def repo_docs(self, owner, repo, docs_path, ref, installation_id):
                self.docs_requests.append((owner, repo, docs_path, ref, installation_id))
                return [
                    {
                        "path": "docs/search-reference.md",
                        "relative_path": "search-reference.md",
                        "content": "# Search API\n\n## GET /v1/search\n\nUse `/v1/search`.\n\n## POST /v1/search/reindex\n\nRebuild the index.",
                    },
                    {
                        "path": "docs/search-overview.md",
                        "relative_path": "search-overview.md",
                        "content": "# Search Overview\n\nThis guide explains search internals.",
                    },
                ]

            def pull_request_files(self, owner, repo, pull_number, installation_id):
                self.file_requests.append((owner, repo, pull_number, installation_id))
                return [
                    {
                        "filename": "src/api/search.py",
                        "patch": "\n".join(patch.splitlines()[4:]),
                    }
                ]

        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/app"},
                "pull_request": {"number": 42, "patch": patch},
            }
        )
        github_client = SurfaceGitHubClient(patch)
        result = process_github_event(
            body,
            None,
            ServiceConfig(
                docs_root=FIXTURES / "repo" / "docs",
                github_client=github_client,
                confidence_threshold=60,
            ),
        )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["payload"]["summary"]["changed_surfaces"], ["/v1/search", "/v1/search/reindex"])
        self.assertEqual(result["payload"]["recommendations"][0]["relative_path"], "search-reference.md")
        self.assertTrue(result["payload"]["release_notes"]["included_in_report"])
        self.assertEqual(result["payload"]["release_notes"]["affected_surfaces"], ["/v1/search", "/v1/search/reindex"])


if __name__ == "__main__":
    unittest.main()

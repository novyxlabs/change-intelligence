import json
import tempfile
from pathlib import Path
import unittest

import requests

from change_intelligence.analysis import analyze_patch
from change_intelligence.github_client import COMMENT_MARKER
from change_intelligence.service import (
    ServiceConfig,
    filter_comment_patterns,
    filter_comment_recommendations,
    process_github_event,
)


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
            return {"billing.md": {"graph_hits": 2, "accepted_hits": 2, "rejected_hits": 0, "exact_file_hits": 1}}
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
        self.installation_requests = []

    def repository_installation_id(self, owner, repo):
        self.installation_requests.append((owner, repo))
        return 123

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

    def auth_mode(self):
        return "app"


class BrokenGitHubClient(FakeGitHubClient):
    def upsert_issue_comment(self, owner, repo, issue_number, installation_id, body):
        raise RuntimeError("comment write failed")


class ChangeIntelligenceServiceTests(unittest.TestCase):
    def test_filter_comment_recommendations_keeps_exact_surface_docs_only_when_top_match_is_exact(self):
        recommendations = [
            {"relative_path": "api-reference/webhooks.md", "confidence": 92, "score": 347, "surface_match_count": 3, "evidence": ["Mentions changed routes or APIs: /v1/webhooks"]},
            {"relative_path": "api-reference/anomalies.md", "confidence": 74, "score": 0, "surface_match_count": 1, "evidence": ["Mentions changed routes or APIs: /v1/webhooks"]},
            {"relative_path": "mcp/tools-reference.md", "confidence": 80, "score": 135, "surface_match_count": 0, "evidence": ["Shared change terms with `change_intelligence/server.py`: api, webhook"]},
        ]

        pruned = filter_comment_recommendations(recommendations, threshold=60)

        self.assertEqual(
            [item["relative_path"] for item in pruned],
            ["api-reference/webhooks.md"],
        )

    def test_filter_comment_patterns_drops_irrelevant_history_for_exact_surface_match(self):
        patterns = [
            {"observation": "change_intelligence/server.py changed -> index.md was predicted for docs review", "score": 0.7},
            {"observation": "change_intelligence/server.py changed -> api-reference/webhooks.md was predicted for docs review", "score": 0.8},
        ]
        recommendations = [
            {"relative_path": "api-reference/webhooks.md", "surface_match_count": 3, "confidence": 92, "score": 347}
        ]

        filtered = filter_comment_patterns(patterns, recommendations)

        self.assertEqual(len(filtered), 1)
        self.assertIn("api-reference/webhooks.md", filtered[0]["observation"])

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
        self.assertEqual(result["payload"]["confidence_tier"], "high-confidence")
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
        self.assertEqual(result["payload"]["side_effects"]["github_comment"]["status"], "commented")
        self.assertEqual(result["payload"]["auth_mode"], "app")
        self.assertEqual(result["payload"]["docs_path"], "docs")
        self.assertIn("### What Changed", result["payload"]["comment_body"])
        self.assertIn("### Why This Is High Confidence", result["payload"]["comment_body"])
        self.assertIn("### Risk If Ignored", result["payload"]["comment_body"])
        self.assertIn("Tier: `high-confidence`", result["payload"]["comment_body"])
        self.assertIn("The top doc mentions the changed symbols directly.", result["payload"]["comment_body"])
        self.assertTrue(any("Novyx remembers this exact changed file mapping" in line for line in result["payload"]["recommendations"][0]["evidence"]))
        self.assertEqual(result["payload"]["trace"]["evaluation"]["health_score"], 98)

    def test_exact_route_evidence_survives_into_high_confidence_reasoning(self):
        patch = """diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 1111111..2222222 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,3 @@
+# POST /v1/webhooks
+# GET /v1/webhooks/{webhook_id}
+# GET /v1/webhooks/{webhook_id}/deliveries
"""
        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "novyxlabs/change-intelligence"},
                "pull_request": {"number": 3, "patch": patch},
            }
        )

        class WebhookDocsGitHubClient(FakeGitHubClient):
            def repo_docs(self, owner, repo, docs_path, ref, installation_id):
                self.docs_requests.append((owner, repo, docs_path, ref, installation_id))
                return [
                    {
                        "path": "docs/api-reference/webhooks.md",
                        "relative_path": "api-reference/webhooks.md",
                        "content": "# Webhooks\n\n## POST /v1/webhooks\n\nCreate a webhook.\n\n## GET /v1/webhooks/{webhook_id}\n\nRead a webhook.\n\n## GET /v1/webhooks/{webhook_id}/deliveries\n\nInspect delivery history.",
                    },
                    {
                        "path": "docs/api-reference/anomalies.md",
                        "relative_path": "api-reference/anomalies.md",
                        "content": "# Anomalies\n\nWatch webhook anomalies from `/v1/webhooks`.",
                    },
                    {
                        "path": "docs/mcp/tools-reference.md",
                        "relative_path": "mcp/tools-reference.md",
                        "content": "# Tools Reference\n\nGeneral MCP tool configuration and setup.",
                    },
                ]

            def pull_request_files(self, owner, repo, pull_number, installation_id):
                self.file_requests.append((owner, repo, pull_number, installation_id))
                return [{"filename": "change_intelligence/server.py", "patch": "\n".join(patch.splitlines()[4:])}]

        result = process_github_event(
            body,
            None,
            ServiceConfig(
                docs_root=FIXTURES / "repo" / "docs",
                github_client=WebhookDocsGitHubClient(patch),
                confidence_threshold=60,
            ),
        )

        self.assertIn("Exact route or API surface matches were found in the top doc.", result["payload"]["comment_body"])
        self.assertNotIn("### mcp/tools-reference.md", result["payload"]["comment_body"])

    def test_process_github_event_autodetects_common_docs_path_when_docs_is_missing(self):
        patch = (FIXTURES / "sample.patch").read_text(encoding="utf8")
        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/app"},
                "pull_request": {"number": 42, "head": {"sha": "abc123"}},
            }
        )

        class AutoDetectGitHubClient(FakeGitHubClient):
            def repo_docs(self, owner, repo, docs_path, ref, installation_id):
                self.docs_requests.append((owner, repo, docs_path, ref, installation_id))
                if docs_path == "docs":
                    response = requests.Response()
                    response.status_code = 404
                    error = requests.HTTPError(response=response)
                    raise error
                return [
                    {
                        "path": "handbook/billing.md",
                        "relative_path": "billing.md",
                        "content": "# Billing Guide\n\n## createCheckoutSession\n\nUse `createCheckoutSession` to start checkout.",
                    }
                ]

            def discover_docs_path(self, owner, repo, installation_id, ref, preferred=None):
                return "handbook"

        result = process_github_event(
            body,
            None,
            ServiceConfig(
                docs_root=FIXTURES / "repo" / "docs",
                github_client=AutoDetectGitHubClient(patch),
                confidence_threshold=60,
            ),
        )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["payload"]["docs_path"], "handbook")
        self.assertEqual(result["payload"]["recommendations"][0]["relative_path"], "billing.md")

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
        self.assertEqual(result["payload"]["confidence_tier"], "silent")
        self.assertEqual(result["payload"]["comment"]["deleted"], True)
        self.assertEqual(result["payload"]["side_effects"]["github_comment"]["status"], "cleared")
        self.assertIsNone(result["payload"]["comment_body"])
        self.assertEqual(github_client.deleted_comments[0][2], 42)

    def test_process_github_event_captures_comment_write_failures_without_crashing(self):
        patch = (FIXTURES / "sample.patch").read_text(encoding="utf8")
        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/app"},
                "pull_request": {"number": 42, "patch": patch},
            }
        )
        result = process_github_event(
            body,
            None,
            ServiceConfig(
                docs_root=FIXTURES / "repo" / "docs",
                novyx_store=FakeNovyxStore(),
                github_client=BrokenGitHubClient(patch),
                confidence_threshold=60,
            ),
        )

        self.assertEqual(result["status_code"], 200)
        self.assertFalse(result["payload"]["comment_suppressed"])
        self.assertIsNone(result["payload"]["comment"])
        self.assertEqual(result["payload"]["side_effects"]["github_comment"]["status"], "failed")
        self.assertIn("comment write failed", result["payload"]["side_effects"]["github_comment"]["error"])

    def test_process_github_event_uses_top_level_number_from_real_github_payload(self):
        patch = (FIXTURES / "sample.patch").read_text(encoding="utf8")
        body = json.dumps(
            {
                "action": "opened",
                "number": 42,
                "repository": {"full_name": "acme/app"},
                "pull_request": {
                    "patch": patch,
                    "head": {"sha": "abc123"},
                },
            }
        )
        github_client = FakeGitHubClient(patch)
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
        self.assertEqual(result["payload"]["pull_request_number"], 42)
        self.assertEqual(github_client.file_requests[0][2], 42)

    def test_process_github_event_resolves_installation_id_for_repo_webhook_under_app_auth(self):
        patch = (FIXTURES / "sample.patch").read_text(encoding="utf8")
        body = json.dumps(
            {
                "action": "opened",
                "number": 42,
                "repository": {"full_name": "acme/app"},
                "pull_request": {
                    "patch": patch,
                    "head": {"sha": "abc123"},
                },
            }
        )
        github_client = FakeGitHubClient(patch)
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
        self.assertEqual(github_client.installation_requests, [("acme", "app")])
        self.assertEqual(github_client.docs_requests[0][-1], 123)
        self.assertEqual(github_client.file_requests[0][-1], 123)
        if github_client.comments:
            self.assertEqual(github_client.comments[0][3], 123)
        else:
            self.assertEqual(github_client.deleted_comments[0][3], 123)

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
        self.assertFalse(result["payload"]["support_updates"]["included_in_report"])
        self.assertFalse(result["payload"]["onboarding_updates"]["included_in_report"])
        self.assertIn("API or route behavior changed:", result["payload"]["comment_body"])
        self.assertIn("Exact route or API surface matches were found in the top doc.", result["payload"]["comment_body"])
        self.assertIn("`search-reference.md` is likely now misleading", result["payload"]["comment_body"])


if __name__ == "__main__":
    unittest.main()

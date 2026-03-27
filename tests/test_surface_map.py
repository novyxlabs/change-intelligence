import unittest

from change_intelligence.analysis import analyze_patch
from change_intelligence.surface_map import extract_surfaces_from_line


PATCH = """diff --git a/src/api/search.py b/src/api/search.py
index 1111111..2222222 100644
--- a/src/api/search.py
+++ b/src/api/search.py
@@ -10,0 +11,5 @@
+@router.get("/v1/search")
+def search():
+    return fetch("https://example.com")
+app.post("/v1/search/reindex")
+request("GET /v1/search")
"""


DOCS = [
    {
        "path": "docs/search-reference.md",
        "relative_path": "search-reference.md",
        "content": "# Search API\n\n## GET /v1/search\n\nUse `/v1/search` to query.\n\n## POST /v1/search/reindex\n\nRebuild the search index.",
    },
    {
        "path": "docs/search-overview.md",
        "relative_path": "search-overview.md",
        "content": "# Search Overview\n\nThis guide explains how search works internally.",
    },
]


class SurfaceMapTests(unittest.TestCase):
    def test_extract_surfaces_from_line_detects_common_route_forms(self):
        self.assertEqual(
            extract_surfaces_from_line('@router.get("/v1/search")'),
            {"/v1/search"},
        )
        self.assertEqual(
            extract_surfaces_from_line('request("GET /v1/search/reindex")'),
            {"/v1/search/reindex"},
        )
        self.assertEqual(
            extract_surfaces_from_line("Docs mention /v1/webhooks."),
            {"/v1/webhooks"},
        )
        self.assertEqual(
            extract_surfaces_from_line("Docs mention /v1/webhooks/{webhook_id}/deliveries."),
            {"/v1/webhooks/{webhook_id}/deliveries"},
        )
        self.assertEqual(
            extract_surfaces_from_line('f"/repos/{owner}/{repo}/installation"'),
            {"/repos/{owner}/{repo}/installation"},
        )

    def test_extract_surfaces_from_line_ignores_markup_and_trims_attribute_quotes(self):
        self.assertEqual(extract_surfaces_from_line("</span>"), set())
        self.assertEqual(extract_surfaces_from_line("<Link href='/pricing'>Pricing</Link>"), {"/pricing"})

    def test_broad_docs_need_structural_support_to_outrank_specific_docs(self):
        patch = """diff --git a/src/pages/Errors.tsx b/src/pages/Errors.tsx
index 1111111..2222222 100644
--- a/src/pages/Errors.tsx
+++ b/src/pages/Errors.tsx
@@ -1,0 +1,3 @@
+renderErrorState();
+showErrorReference();
+// update copy around error states
"""
        docs = [
            {
                "path": "docs/errors.md",
                "relative_path": "errors.md",
                "content": "# Error Reference\n\nHow to interpret product error states and troubleshooting steps.",
            },
            {
                "path": "docs/changelog.md",
                "relative_path": "changelog.md",
                "content": "# Changelog\n\nGeneral release log and historical updates.",
            },
            {
                "path": "docs/index.md",
                "relative_path": "index.md",
                "content": "# Documentation Home\n\nOverview of the documentation set.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/novyx-site")

        self.assertEqual(result["recommendations"][0]["relative_path"], "errors.md")
        broad_targets = {
            item["relative_path"]: item
            for item in result["recommendations"]
            if item["relative_path"] in {"changelog.md", "index.md"}
        }
        self.assertEqual(broad_targets, {})

    def test_analyze_patch_prefers_docs_with_exact_surface_matches(self):
        result = analyze_patch(PATCH, docs=DOCS, repository="acme/app")

        self.assertEqual(result["summary"]["changed_surfaces"], ["/v1/search", "/v1/search/reindex"])
        self.assertEqual(result["recommendations"][0]["relative_path"], "search-reference.md")
        self.assertTrue(
            any("Mentions changed routes or APIs" in line for line in result["recommendations"][0]["evidence"])
        )
        self.assertTrue(
            any("routes and APIs" in line for line in result["recommendations"][0]["update_focus"])
        )

    def test_exact_surface_docs_outrank_broad_historical_matches(self):
        patch = """diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 1111111..2222222 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,4 @@
+# POST /v1/webhooks.
+# Webhook event notifications should stay explicit here.
+# This GitHub handler verifies webhook signatures before pull_request processing.
+# It keeps delivery behavior separate from memory.created events.
"""
        docs = [
            {
                "path": "docs/changelog.md",
                "relative_path": "changelog.md",
                "content": "# Changelog\n\nGeneral release log for product updates and events.",
            },
            {
                "path": "docs/api-reference/webhooks.md",
                "relative_path": "api-reference/webhooks.md",
                "content": "# Webhooks\n\n## POST /v1/webhooks\n\nRegister webhook event notifications.",
            },
        ]
        result = analyze_patch(
            patch,
            docs=docs,
            repository="novyxlabs/change-intelligence",
            patterns=[
                {"observation": "change_intelligence/server.py changed -> changelog.md was predicted for docs review"},
                {"observation": "change_intelligence/server.py changed -> changelog.md was predicted for docs review"},
                {"observation": "change_intelligence/server.py changed -> api-reference/webhooks.md was predicted for docs review"},
            ],
        )

        self.assertEqual(result["summary"]["changed_surfaces"], ["/v1/webhooks"])
        self.assertEqual(result["recommendations"][0]["relative_path"], "api-reference/webhooks.md")
        self.assertTrue(
            any("exact route/API matches outrank broad historical-pattern matches" in line for line in result["recommendations"][0]["evidence"])
        )

    def test_delivery_history_surface_prefers_webhooks_reference(self):
        patch = """diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 2222222..3333333 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,4 @@
+request("GET /v1/webhooks/{webhook_id}/deliveries?limit=10")
+# Delivery history should stay explicit for webhook debugging.
+# The webhook endpoint remains separate from generic audit events.
+# Keep delivery surfaces aligned with the public API docs.
"""
        docs = [
            {
                "path": "docs/api-reference/webhooks.md",
                "relative_path": "api-reference/webhooks.md",
                "content": "# Webhooks\n\n## GET /v1/webhooks/{webhook_id}/deliveries\n\nView recent delivery attempts for a webhook.",
            },
            {
                "path": "docs/api-reference/audit.md",
                "relative_path": "api-reference/audit.md",
                "content": "# Audit\n\nTrack system audit trails and operational events.",
            },
        ]
        result = analyze_patch(
            patch,
            docs=docs,
            repository="novyxlabs/change-intelligence",
        )

        self.assertEqual(result["summary"]["changed_surfaces"], ["/v1/webhooks/{webhook_id}/deliveries"])
        self.assertEqual(result["recommendations"][0]["relative_path"], "api-reference/webhooks.md")
        self.assertTrue(
            any("Mentions changed routes or APIs" in line for line in result["recommendations"][0]["evidence"])
        )

    def test_test_file_routes_do_not_outrank_real_product_surfaces(self):
        patch = """diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 1111111..2222222 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,2 @@
+# POST /v1/webhooks
+# GET /v1/webhooks/{webhook_id}/deliveries
diff --git a/tests/test_service.py b/tests/test_service.py
index 2222222..3333333 100644
--- a/tests/test_service.py
+++ b/tests/test_service.py
@@ -1,0 +1,2 @@
+request(\"GET /v1/search\")
+request(\"POST /v1/search/reindex\")
"""
        docs = [
            {
                "path": "docs/api-reference/webhooks.md",
                "relative_path": "api-reference/webhooks.md",
                "content": "# Webhooks\n\n## POST /v1/webhooks\n\nCreate webhook.\n\n## GET /v1/webhooks/{webhook_id}/deliveries\n\nDelivery history.",
            },
            {
                "path": "docs/api-reference/search.md",
                "relative_path": "api-reference/search.md",
                "content": "# Search\n\n## GET /v1/search\n\nSearch.\n\n## POST /v1/search/reindex\n\nReindex.",
            },
        ]
        result = analyze_patch(patch, docs=docs, repository="novyxlabs/change-intelligence")

        self.assertEqual(result["recommendations"][0]["relative_path"], "api-reference/webhooks.md")
        self.assertEqual(
            result["summary"]["changed_surfaces"],
            ["/v1/webhooks", "/v1/webhooks/{webhook_id}/deliveries"],
        )

    def test_doc_relevant_surfaces_hide_internal_routes_and_landing_pages(self):
        patch = """diff --git a/change_intelligence/github_client.py b/change_intelligence/github_client.py
index 1111111..2222222 100644
--- a/change_intelligence/github_client.py
+++ b/change_intelligence/github_client.py
@@ -1,0 +1,3 @@
+response = self._request("GET", f"/repos/{owner}/{repo}/installation")
diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 2222222..3333333 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,8 @@
+# POST /v1/webhooks
+# GET /v1/webhooks/{webhook_id}/deliveries
+if self.path in {"/api/dashboard", "/api/ops-dashboard"}:
+    pass
+if self.path in {"/dashboard", "/ops-dashboard"}:
+    pass
"""
        docs = [
            {
                "path": "docs/index.md",
                "relative_path": "index.md",
                "content": "# Novyx Documentation\n\nAPI Reference, SDKs, guides, and dashboards overview.",
            },
            {
                "path": "docs/sdks/cli.md",
                "relative_path": "sdks/cli.md",
                "content": "# CLI\n\nInstall the CLI and authenticate to manage agents.",
            },
            {
                "path": "docs/errors.md",
                "relative_path": "errors.md",
                "content": "# Error Reference\n\nCommon auth and request failures.",
            },
            {
                "path": "docs/api-reference/webhooks.md",
                "relative_path": "api-reference/webhooks.md",
                "content": "# Webhooks\n\n## POST /v1/webhooks\n\nCreate a webhook.\n\n## GET /v1/webhooks/{webhook_id}/deliveries\n\nInspect delivery history.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/change-intelligence")

        self.assertEqual(
            result["summary"]["changed_surfaces"],
            ["/v1/webhooks", "/v1/webhooks/{webhook_id}/deliveries"],
        )
        self.assertEqual(result["recommendations"][0]["relative_path"], "api-reference/webhooks.md")
        self.assertNotIn("/{repo}", result["markdown"])
        self.assertNotIn("/repos/{owner}/{repo}/installation", result["markdown"])
        self.assertNotIn("/api/dashboard", result["markdown"])

    def test_security_narrowing_keeps_top_ranked_exact_surface_docs(self):
        patch = """diff --git a/change_intelligence/github_client.py b/change_intelligence/github_client.py
index 1111111..2222222 100644
--- a/change_intelligence/github_client.py
+++ b/change_intelligence/github_client.py
@@ -1,0 +1,2 @@
+token = response.json()["token"]
+request("GET /repos/{owner}/{repo}/installation")
diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 2222222..3333333 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,3 @@
+# POST /v1/webhooks
+# GET /v1/webhooks/{webhook_id}
+# GET /v1/webhooks/{webhook_id}/deliveries
"""
        docs = [
            {
                "path": "docs/sdks/cli.md",
                "relative_path": "sdks/cli.md",
                "content": "# CLI\n\nAuthenticate with an API key and manage tokens from the command line.",
            },
            {
                "path": "docs/errors.md",
                "relative_path": "errors.md",
                "content": "# Error Reference\n\nTroubleshoot auth, token, and request failures.",
            },
            {
                "path": "docs/api-reference/webhooks.md",
                "relative_path": "api-reference/webhooks.md",
                "content": "# Webhooks\n\n## POST /v1/webhooks\n\nCreate a webhook.\n\n## GET /v1/webhooks/{webhook_id}\n\nRead a webhook.\n\n## GET /v1/webhooks/{webhook_id}/deliveries\n\nInspect delivery history.",
            },
            {
                "path": "docs/index.md",
                "relative_path": "index.md",
                "content": "# Novyx Documentation\n\nOverview of APIs, SDKs, and guides.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/change-intelligence")

        self.assertEqual(result["recommendations"][0]["relative_path"], "api-reference/webhooks.md")
        self.assertEqual(result["recommendations"][0]["confidence"], 100)

    def test_docs_with_more_exact_surface_coverage_outrank_parent_route_mentions(self):
        patch = """diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 1111111..2222222 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,3 @@
+# POST /v1/webhooks
+# GET /v1/webhooks/{webhook_id}
+# GET /v1/webhooks/{webhook_id}/deliveries
"""
        docs = [
            {
                "path": "docs/api-reference/anomalies.md",
                "relative_path": "api-reference/anomalies.md",
                "content": "# Anomalies\n\nWatch webhook anomalies from `/v1/webhooks`.",
            },
            {
                "path": "docs/api-reference/webhooks.md",
                "relative_path": "api-reference/webhooks.md",
                "content": "# Webhooks\n\n## POST /v1/webhooks\n\nCreate a webhook.\n\n## GET /v1/webhooks/{webhook_id}\n\nRead a webhook.\n\n## GET /v1/webhooks/{webhook_id}/deliveries\n\nInspect delivery history.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/change-intelligence")

        self.assertEqual(result["recommendations"][0]["relative_path"], "api-reference/webhooks.md")
        self.assertTrue(
            any(
                "docs covering more of the changed API surface outrank broad parent-route mentions" in line
                for line in result["recommendations"][0]["evidence"]
            )
        )

    def test_exact_surface_coverage_outranks_higher_confidence_stale_memory_match(self):
        patch = """diff --git a/change_intelligence/server.py b/change_intelligence/server.py
index 1111111..2222222 100644
--- a/change_intelligence/server.py
+++ b/change_intelligence/server.py
@@ -1,0 +1,3 @@
+# POST /v1/webhooks
+# GET /v1/webhooks/{webhook_id}
+# GET /v1/webhooks/{webhook_id}/deliveries
"""
        docs = [
            {
                "path": "docs/api-reference/anomalies.md",
                "relative_path": "api-reference/anomalies.md",
                "content": "# Anomalies\n\nWatch webhook anomalies from `/v1/webhooks`.",
            },
            {
                "path": "docs/api-reference/webhooks.md",
                "relative_path": "api-reference/webhooks.md",
                "content": "# Webhooks\n\n## POST /v1/webhooks\n\nCreate a webhook.\n\n## GET /v1/webhooks/{webhook_id}\n\nRead a webhook.\n\n## GET /v1/webhooks/{webhook_id}/deliveries\n\nInspect delivery history.",
            },
        ]
        learned_signals = {
            "api-reference/anomalies.md": {"graph_hits": 6, "accepted_hits": 5, "rejected_hits": 0},
            "api-reference/webhooks.md": {"graph_hits": 0, "accepted_hits": 0, "rejected_hits": 1},
        }

        result = analyze_patch(
            patch,
            docs=docs,
            repository="novyxlabs/change-intelligence",
            learned_signals=learned_signals,
        )

        self.assertEqual(result["recommendations"][0]["relative_path"], "api-reference/webhooks.md")
        self.assertGreater(result["recommendations"][0]["score"], result["recommendations"][1]["score"])

    def test_copy_only_marketing_changes_do_not_clear_comment_threshold_from_weak_overlap(self):
        patch = """diff --git a/src/pages/GetStarted.tsx b/src/pages/GetStarted.tsx
index 1111111..2222222 100644
--- a/src/pages/GetStarted.tsx
+++ b/src/pages/GetStarted.tsx
@@ -1,0 +1,4 @@
+<section>
+  <span>Keep session continuity across devices.</span>
+  <Link href='/pricing'>View pricing</Link>
+</section>
"""
        docs = [
            {
                "path": "docs/index.md",
                "relative_path": "index.md",
                "content": "# Novyx Documentation\n\nOverview of agents, memory, rollback, and pricing.",
            },
            {
                "path": "docs/changelog.md",
                "relative_path": "changelog.md",
                "content": "# Changelog\n\nTrack product updates for pricing and onboarding.",
            },
            {
                "path": "docs/sdks/python.md",
                "relative_path": "sdks/python.md",
                "content": "# Python SDK\n\nStore memory, recall context, and manage agent sessions.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/novyx-site")

        self.assertEqual(result["summary"]["changed_surfaces"], [])
        self.assertTrue(result["recommendations"])
        self.assertLess(max(item["confidence"] for item in result["recommendations"]), 60)
        self.assertTrue(
            any(
                "only matched weak term overlap without a structural doc signal" in line
                for line in result["recommendations"][0]["evidence"]
            )
        )

    def test_camel_case_guide_pages_match_slugged_guide_docs(self):
        patch = """diff --git a/src/pages/GuideClaudeCode.tsx b/src/pages/GuideClaudeCode.tsx
index 1111111..2222222 100644
--- a/src/pages/GuideClaudeCode.tsx
+++ b/src/pages/GuideClaudeCode.tsx
@@ -1,0 +1,3 @@
+Claude Code now replays prior decisions across sessions.
+Shared context keeps project history synced across machines.
+Rollback history is available when the coding agent goes off track.
"""
        docs = [
            {
                "path": "docs/guides/claude-code.md",
                "relative_path": "guides/claude-code.md",
                "content": "# Claude Code + Novyx\n\nAdd persistent memory, shared context, and rollback history to Claude Code.",
            },
            {
                "path": "docs/changelog.md",
                "relative_path": "changelog.md",
                "content": "# Changelog\n\nRecent platform updates.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/novyx-site")

        self.assertEqual(result["recommendations"][0]["relative_path"], "guides/claude-code.md")
        self.assertEqual(len(result["recommendations"]), 1)

    def test_errors_page_prefers_errors_doc_after_slug_and_path_overlap(self):
        patch = """diff --git a/src/pages/Errors.tsx b/src/pages/Errors.tsx
index 1111111..2222222 100644
--- a/src/pages/Errors.tsx
+++ b/src/pages/Errors.tsx
@@ -1,0 +1,3 @@
+retry_after_seconds helps clients back off after 429 responses.
+request_id should be included when reporting 500 errors.
+The error reference now explains rollback quota failures in more detail.
"""
        docs = [
            {
                "path": "docs/errors.md",
                "relative_path": "errors.md",
                "content": "# Error Reference\n\nHandle 429 responses, request_id tracing, and rollback quota failures.",
            },
            {
                "path": "docs/sdks/python.md",
                "relative_path": "sdks/python.md",
                "content": "# Python SDK\n\nCall the API and handle retries in Python.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/novyx-site")

        self.assertEqual(result["recommendations"][0]["relative_path"], "errors.md")

    def test_error_reference_page_outranks_api_docs_for_troubleshooting_copy(self):
        patch = """diff --git a/src/pages/Errors.tsx b/src/pages/Errors.tsx
index 1111111..2222222 100644
--- a/src/pages/Errors.tsx
+++ b/src/pages/Errors.tsx
@@ -1,0 +1,4 @@
+retry_after_seconds helps clients back off after 429 responses.
+request_id should be included when reporting 500 errors.
+Rollback quota failures now point users to the troubleshooting flow.
+This page explains common API errors and how to fix them.
"""
        docs = [
            {
                "path": "docs/errors.md",
                "relative_path": "errors.md",
                "content": "# Error Reference\n\nTroubleshoot 429 retries, request_id tracing, rollback quota failures, and common API errors.",
            },
            {
                "path": "docs/api-reference/memories.md",
                "relative_path": "api-reference/memories.md",
                "content": "# Memories API\n\nStore observations and handle write conflicts.",
            },
            {
                "path": "docs/api-reference/replay.md",
                "relative_path": "api-reference/replay.md",
                "content": "# Replay API\n\nReplay history and rollback state changes.",
            },
        ]

        result = analyze_patch(patch, docs=docs, repository="novyxlabs/novyx-site")

        self.assertEqual(result["recommendations"][0]["relative_path"], "errors.md")

if __name__ == "__main__":
    unittest.main()

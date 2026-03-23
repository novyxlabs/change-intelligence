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


if __name__ == "__main__":
    unittest.main()

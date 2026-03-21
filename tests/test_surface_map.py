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


if __name__ == "__main__":
    unittest.main()

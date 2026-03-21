import unittest

from change_intelligence.analysis import analyze_patch


HIGH_SIGNAL_PATCH = """diff --git a/src/api/search.py b/src/api/search.py
index 1111111..2222222 100644
--- a/src/api/search.py
+++ b/src/api/search.py
@@ -10,0 +11,4 @@
+@router.get("/v1/search")
+def search():
+    pass
+app.post("/v1/search/reindex")
"""

LOW_SIGNAL_PATCH = """diff --git a/src/internal/cache.py b/src/internal/cache.py
index 1111111..2222222 100644
--- a/src/internal/cache.py
+++ b/src/internal/cache.py
@@ -1,0 +1,2 @@
+value = 1
+other = 2
"""

HIGH_SIGNAL_DOCS = [
    {
        "path": "docs/search-reference.md",
        "relative_path": "search-reference.md",
        "content": "# Search API\n\n## GET /v1/search\n\nUse `/v1/search`.\n\n## POST /v1/search/reindex\n\nRebuild the index.",
    }
]

LOW_SIGNAL_DOCS = [
    {
        "path": "docs/overview.md",
        "relative_path": "overview.md",
        "content": "# Overview\n\nGeneral product overview with no cache implementation details.",
    }
]


class ReleaseNotesTests(unittest.TestCase):
    def test_analyze_patch_emits_release_notes_for_high_confidence_changes(self):
        result = analyze_patch(HIGH_SIGNAL_PATCH, docs=HIGH_SIGNAL_DOCS, repository="acme/app")

        self.assertTrue(result["release_notes"]["included_in_report"])
        self.assertEqual(result["release_notes"]["affected_surfaces"], ["/v1/search", "/v1/search/reindex"])
        self.assertIn("Release Notes Draft", result["markdown"])

    def test_analyze_patch_suppresses_release_notes_for_low_confidence_changes(self):
        result = analyze_patch(LOW_SIGNAL_PATCH, docs=LOW_SIGNAL_DOCS, repository="acme/app")

        self.assertFalse(result["release_notes"]["included_in_report"])
        self.assertEqual(
            result["release_notes"]["suppressed_reason"],
            "Top recommendation confidence below release-note threshold.",
        )
        self.assertNotIn("Release Notes Draft", result["markdown"])


if __name__ == "__main__":
    unittest.main()

import unittest

from change_intelligence.analysis import analyze_patch


HIGH_SIGNAL_PATCH = """diff --git a/src/api/search.py b/src/api/search.py
index 1111111..2222222 100644
--- a/src/api/search.py
+++ b/src/api/search.py
@@ -10,0 +11,5 @@
+@router.get("/v1/search")
+def search():
+    pass
+app.post("/v1/search/reindex")
+def login_setup():
"""

HIGH_SIGNAL_DOCS = [
    {
        "path": "docs/search-reference.md",
        "relative_path": "search-reference.md",
        "content": "# Search API\n\n## GET /v1/search\n\nUse `/v1/search`.\n\n## POST /v1/search/reindex\n\nRebuild the index.",
    },
    {
        "path": "docs/support/search-faq.md",
        "relative_path": "support/search-faq.md",
        "content": "# Search FAQ\n\n## /v1/search errors\n\nTroubleshooting search and reindex support cases.",
    },
    {
        "path": "docs/onboarding/search-quickstart.md",
        "relative_path": "onboarding/search-quickstart.md",
        "content": "# Search Quickstart\n\n## Login setup\n\nGetting started with search and reindex setup.",
    },
]

LOW_SIGNAL_PATCH = """diff --git a/src/internal/cache.py b/src/internal/cache.py
index 1111111..2222222 100644
--- a/src/internal/cache.py
+++ b/src/internal/cache.py
@@ -1,0 +1,2 @@
+value = 1
+other = 2
"""

LOW_SIGNAL_DOCS = [
    {
        "path": "docs/overview.md",
        "relative_path": "overview.md",
        "content": "# Overview\n\nGeneral product overview.",
    }
]


class KnowledgeUpdatesTests(unittest.TestCase):
    def test_analyze_patch_emits_support_and_onboarding_updates(self):
        result = analyze_patch(HIGH_SIGNAL_PATCH, docs=HIGH_SIGNAL_DOCS, repository="acme/app")

        self.assertTrue(result["support_updates"]["included_in_report"])
        self.assertEqual(result["support_updates"]["recommended_docs"][0], "support/search-faq.md")
        self.assertTrue(result["onboarding_updates"]["included_in_report"])
        self.assertEqual(result["onboarding_updates"]["recommended_docs"][0], "onboarding/search-quickstart.md")
        self.assertIn("Support Knowledge Update", result["markdown"])
        self.assertIn("Onboarding/Tour Update", result["markdown"])

    def test_analyze_patch_suppresses_missing_adjacent_knowledge_updates(self):
        result = analyze_patch(LOW_SIGNAL_PATCH, docs=LOW_SIGNAL_DOCS, repository="acme/app")

        self.assertFalse(result["support_updates"]["included_in_report"])
        self.assertEqual(
            result["support_updates"]["suppressed_reason"],
            "No support-oriented docs ranked above the adjacent-update threshold.",
        )
        self.assertFalse(result["onboarding_updates"]["included_in_report"])
        self.assertEqual(
            result["onboarding_updates"]["suppressed_reason"],
            "No onboarding-oriented docs ranked above the adjacent-update threshold.",
        )
        self.assertNotIn("Support Knowledge Update", result["markdown"])
        self.assertNotIn("Onboarding/Tour Update", result["markdown"])


if __name__ == "__main__":
    unittest.main()

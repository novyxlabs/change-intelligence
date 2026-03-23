import unittest

from change_intelligence.analysis import analyze_patch


PATCH = """diff --git a/src/billing/createCheckoutSession.ts b/src/billing/createCheckoutSession.ts
index 1111111..2222222 100644
--- a/src/billing/createCheckoutSession.ts
+++ b/src/billing/createCheckoutSession.ts
@@ -1,0 +1,3 @@
+export async function createCheckoutSession(planId) {
+  return { planId };
+}
"""

DOCS = [
    {
        "path": "docs/billing.md",
        "relative_path": "billing.md",
        "content": "# Billing Guide\n\n## Checkout\n\nUse createCheckoutSession to start checkout.",
    },
    {
        "path": "docs/api.md",
        "relative_path": "api.md",
        "content": "# API\n\nGeneral API guide with checkout and billing concepts.",
    },
]


class MemoryRankingTests(unittest.TestCase):
    def test_repo_specific_memory_boosts_confirmed_doc_target(self):
        result = analyze_patch(
            PATCH,
            docs=DOCS,
            learned_signals={
                "billing.md": {
                    "graph_hits": 1,
                    "accepted_hits": 2,
                    "rejected_hits": 0,
                    "missed_hits": 0,
                    "exact_file_hits": 1,
                }
            },
        )

        self.assertEqual(result["recommendations"][0]["relative_path"], "billing.md")
        self.assertGreaterEqual(result["recommendations"][0]["confidence"], 72)
        self.assertTrue(
            any("Novyx remembers this exact changed file mapping" in line for line in result["recommendations"][0]["evidence"])
        )


if __name__ == "__main__":
    unittest.main()

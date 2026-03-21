import json
import tempfile
import unittest
from pathlib import Path

from change_intelligence.analysis import analyze_patch


PATCH = """diff --git a/src/billing/retries.py b/src/billing/retries.py
index 1111111..2222222 100644
--- a/src/billing/retries.py
+++ b/src/billing/retries.py
@@ -0,0 +1,2 @@
+def sync_invoice_retry_window():
+    return True
"""


DOCS = [
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


class OwnershipRuleTests(unittest.TestCase):
    def write_rules(self, payload) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        with handle:
            json.dump(payload, handle)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_ownership_rule_boosts_owned_doc_above_symbol_match(self):
        rules_path = self.write_rules(
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
            }
        )

        result = analyze_patch(
            PATCH,
            docs=DOCS,
            repository="acme/app",
            ownership_rules_path=rules_path,
        )

        self.assertEqual(result["recommendations"][0]["relative_path"], "billing.md")
        self.assertTrue(
            any("Ownership rule matched" in line for line in result["recommendations"][0]["evidence"])
        )

    def test_missing_repository_rule_leaves_symbol_match_on_top(self):
        rules_path = self.write_rules(
            {
                "repositories": {
                    "other/repo": [
                        {
                            "code_prefix": "src/billing/",
                            "doc_prefix": "billing.md",
                            "score_boost": 32,
                        }
                    ]
                }
            }
        )

        result = analyze_patch(
            PATCH,
            docs=DOCS,
            repository="acme/app",
            ownership_rules_path=rules_path,
        )

        self.assertEqual(result["recommendations"][0]["relative_path"], "ops.md")


if __name__ == "__main__":
    unittest.main()

import unittest

from change_intelligence.backfill import parse_analysis_comment, parse_pr_number
from change_intelligence.github_client import COMMENT_MARKER


class BackfillTests(unittest.TestCase):
    def test_parse_pr_number(self):
        self.assertEqual(
            parse_pr_number("https://api.github.com/repos/novyxlabs/novyx-site/issues/6"),
            6,
        )
        self.assertIsNone(parse_pr_number("https://api.github.com/repos/novyxlabs/novyx-site/pulls/6"))

    def test_parse_analysis_comment_extracts_top_doc_and_changed_files(self):
        body = "\n".join(
            [
                COMMENT_MARKER,
                "## Change Intelligence",
                "",
                "Repository: `novyxlabs/novyx-site`",
                "Pull request: #6",
                "Confidence threshold: `60`",
                "Tier: `high-confidence`",
                "",
                "# Change Intelligence Report",
                "",
                "## Changed Files",
                "",
                "- `src/pages/Errors.tsx`",
                "- `src/lib/errors.ts`",
                "",
                "## Recommended Docs",
                "",
                "### errors.md",
                "",
                "Confidence: **91**",
                "Score: **123**",
                "",
                "Evidence:",
                "- exact route match",
            ]
        )

        parsed = parse_analysis_comment(body)

        self.assertEqual(parsed["confidence_tier"], "high-confidence")
        self.assertEqual(parsed["top_doc"], "errors.md")
        self.assertEqual(parsed["top_confidence"], 91)
        self.assertEqual(parsed["changed_files"], ["src/pages/Errors.tsx", "src/lib/errors.ts"])


if __name__ == "__main__":
    unittest.main()

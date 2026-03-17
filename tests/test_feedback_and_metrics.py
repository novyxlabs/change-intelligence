import unittest

from change_intelligence.feedback import parse_feedback_command
from change_intelligence.metrics import compute_metrics


class FakeStore:
    def __init__(self, feedback, runs):
        self.feedback = feedback
        self.runs = runs

    def list_memories(self, tags, limit=500):
        if tags == ["ci-feedback"]:
            return self.feedback
        if tags == ["analysis-run"]:
            return self.runs
        return []


class FeedbackAndMetricsTests(unittest.TestCase):
    def test_parse_feedback_command(self):
        self.assertEqual(parse_feedback_command("/ci correct"), "/ci correct")
        self.assertEqual(parse_feedback_command("Looks good\n/ci wrong-doc"), "/ci wrong-doc")
        self.assertIsNone(parse_feedback_command("thanks"))

    def test_compute_metrics(self):
        store = FakeStore(
            feedback=[
                {"tags": ["ci-feedback", "correct"]},
                {"tags": ["ci-feedback", "wrong-doc"]},
                {"tags": ["ci-feedback", "missed-doc"]},
            ],
            runs=[
                {"tags": ["analysis-run", "commented"]},
                {"tags": ["analysis-run", "commented"]},
                {"tags": ["analysis-run", "suppressed"]},
            ],
        )
        metrics = compute_metrics(store)
        self.assertEqual(metrics["feedback_total"], 3)
        self.assertEqual(metrics["analysis_runs"], 3)
        self.assertAlmostEqual(metrics["top_1_rate"], 1 / 3)
        self.assertAlmostEqual(metrics["comment_rate"], 2 / 3)
        self.assertAlmostEqual(metrics["false_positive_rate"], 1 / 2)


if __name__ == "__main__":
    unittest.main()

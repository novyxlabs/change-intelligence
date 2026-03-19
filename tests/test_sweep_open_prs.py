import unittest

from change_intelligence.sweep_open_prs import already_analyzed_current_head, sweep


class FakeGitHubClient:
    def __init__(self):
        self.dispatched = []

    def pull_requests(self, owner, repo, state="open", per_page=50):
        return [
            {"number": 1, "head": {"sha": "abc123"}},
            {"number": 2, "head": {"sha": "def456"}},
        ]


class FakeStore:
    def __init__(self, latest):
        self.latest = latest

    def latest_analysis_for_pr(self, repository, pull_request_number):
        return self.latest.get((repository, pull_request_number))


class SweepTests(unittest.TestCase):
    def test_already_analyzed_current_head_matches_sha(self):
        store = FakeStore(
            {
                ("acme/app", 1): {
                    "metadata": {"head_sha": "abc123"},
                }
            }
        )
        self.assertTrue(
            already_analyzed_current_head(
                store,
                "acme/app",
                {"number": 1, "head": {"sha": "abc123"}},
            )
        )
        self.assertFalse(
            already_analyzed_current_head(
                store,
                "acme/app",
                {"number": 1, "head": {"sha": "zzz999"}},
            )
        )

    def test_sweep_skips_current_sha_and_dispatches_missing(self):
        github = FakeGitHubClient()
        store = FakeStore(
            {
                ("acme/app", 1): {
                    "metadata": {"head_sha": "abc123"},
                }
            }
        )

        import change_intelligence.sweep_open_prs as module

        original_has_comment = module.has_change_intelligence_comment
        original_dispatch = module.dispatch_analysis
        try:
            module.has_change_intelligence_comment = lambda github, owner, repo, issue_number: False
            module.dispatch_analysis = lambda github, repository, pull_request: github.dispatched.append(
                (repository, int(pull_request["number"]))
            )

            result = sweep(github, ["acme/app"], store=store)
        finally:
            module.has_change_intelligence_comment = original_has_comment
            module.dispatch_analysis = original_dispatch

        self.assertEqual(github.dispatched, [("acme/app", 2)])
        self.assertEqual(result["skipped"][0]["reason"], "already-analyzed-head")


if __name__ == "__main__":
    unittest.main()

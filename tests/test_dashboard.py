import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from typing import Optional

from change_intelligence.dashboard import (
    build_dashboard_payload,
    build_public_proof_payload,
    render_dashboard_html,
    render_public_proof_html,
)
from change_intelligence.server import AppHandler
from change_intelligence.service import ServiceConfig
from change_intelligence.github_client import GitHubClient, GitHubConfig


class FakeStore:
    def __init__(self):
        self.feedback = [
            {
                "tags": ["ci-feedback", "correct"],
                "context": "novyxlabs/novyx-core#12",
                "created_at": "2026-03-22T12:01:00Z",
                "metadata": {
                    "repository": "novyxlabs/novyx-core",
                    "docs_repo": "novyxlabs/novyx-docs",
                    "docs_path": "handbook",
                    "pull_request_number": 12,
                    "feedback": "correct",
                    "commenter": "blake",
                    "comment_url": "https://example.test/comment/2",
                    "analysis_memory_id": "mem_run_1",
                },
            }
        ]
        self.runs = [
            {
                "tags": ["analysis-run", "review-recommended", "commented"],
                "context": "novyxlabs/novyx-core#12",
                "created_at": "2026-03-22T12:00:00Z",
                "metadata": {
                    "repository": "novyxlabs/novyx-core",
                    "docs_repo": "novyxlabs/novyx-docs",
                    "docs_path": "handbook",
                    "pull_request_number": 12,
                    "head_sha": "abc123def456",
                    "top_doc": "billing.md",
                    "top_confidence": 84,
                    "confidence_tier": "review-recommended",
                    "comment_suppressed": False,
                    "recommendation_count": 3,
                    "changed_files": ["src/billing/createCheckoutSession.ts"],
                    "github_comment_status": "commented",
                    "novyx_record_status": "recorded",
                    "auth_mode": "token",
                },
            }
        ]

    def list_memories(self, tags, limit=500):
        if tags == ["ci-feedback"]:
            return self.feedback[:limit]
        if tags == ["analysis-run"]:
            return self.runs[:limit]
        return []

    def evaluation_history(self, limit=10):
        return {"history": [{"health_score": 97, "timestamp": "2026-03-22T12:02:00Z"}]}

    def evaluation_drift(self, days=7):
        return {"drift_score": 0.03, "days": days}

    def feedback_audit(self, limit=50):
        return [{"operation": "CREATE", "artifact_id": "mem_feedback_1"}]


class BrokenDashboardStore(FakeStore):
    def list_memories(self, tags, limit=500):
        if tags == ["analysis-run"]:
            raise RuntimeError("analysis history unavailable")
        return super().list_memories(tags, limit=limit)


class DashboardTests(unittest.TestCase):
    def test_build_dashboard_payload_normalizes_recent_items(self):
        payload = build_dashboard_payload(FakeStore(), limit=10)
        self.assertEqual(payload["metrics"]["analysis_runs"], 1)
        self.assertEqual(payload["recent_runs"][0]["top_doc"], "billing.md")
        self.assertEqual(payload["recent_feedback"][0]["feedback"], "correct")
        self.assertEqual(payload["metrics"]["hotspots"][0]["area"], "src/billing")
        self.assertEqual(payload["metrics"]["hotspots"][0]["top_doc"], "billing.md")
        self.assertEqual(payload["metrics"]["confidence_tiers"]["counts"]["review_recommended"], 1)
        self.assertEqual(payload["metrics"]["case_studies"][0]["top_doc"], "billing.md")
        self.assertEqual(payload["metrics"]["side_effects"]["counts"]["token_auth_runs"], 1)
        self.assertEqual(payload["auth_mode"], "none")
        self.assertEqual(payload["setup"]["docs_path"], "handbook")
        self.assertEqual(payload["setup"]["checks"][0]["label"], "GitHub auth")
        self.assertEqual(payload["errors"], [])

    def test_build_dashboard_payload_surfaces_partial_errors(self):
        payload = build_dashboard_payload(BrokenDashboardStore(), limit=10)
        self.assertEqual(payload["metrics"], {})
        self.assertEqual(payload["recent_runs"], [])
        self.assertEqual(payload["recent_feedback"][0]["feedback"], "correct")
        self.assertIn("metrics: analysis history unavailable", payload["errors"])
        self.assertIn("recent_runs: analysis history unavailable", payload["errors"])

    def test_render_dashboard_html_includes_core_sections(self):
        html = render_dashboard_html(
            build_dashboard_payload(
                FakeStore(),
                limit=10,
                service_config=ServiceConfig(
                    docs_root=".",
                    novyx_store=FakeStore(),
                    github_client=GitHubClient(GitHubConfig(token="gho_example")),
                ),
            )
        )
        self.assertIn("Change Intelligence Dashboard", html)
        self.assertIn("Recent Analysis Runs", html)
        self.assertIn("Drift Hotspots", html)
        self.assertIn("Proof Candidates", html)
        self.assertIn("Production Alerts", html)
        self.assertIn("Setup Status", html)
        self.assertIn("GitHub auth mode: token", html)
        self.assertIn("novyxlabs/novyx-docs", html)
        self.assertIn("Recent confidence mix", html)
        self.assertIn("novyxlabs/novyx-core", html)
        self.assertIn("billing.md", html)

    def test_public_proof_payload_and_html_include_case_studies(self):
        payload = build_public_proof_payload(FakeStore(), limit=10)
        self.assertEqual(payload["case_studies"][0]["top_doc"], "billing.md")
        html = render_public_proof_html(payload)
        self.assertIn("Change Intelligence Proof", html)
        self.assertIn("Accepted Proof Points", html)
        self.assertIn("billing.md", html)

    def test_server_serves_dashboard_json_and_html(self):
        def invoke(path: str, dashboard_secret: str = "", provided_secret: Optional[str] = None) -> tuple[int, dict[str, str], bytes]:
            handler = AppHandler.__new__(AppHandler)
            handler.path = path
            handler.config = ServiceConfig(docs_root=".", novyx_store=FakeStore(), dashboard_secret=dashboard_secret)
            handler.wfile = BytesIO()
            handler.headers = SimpleNamespace(get=lambda key, default=None: provided_secret if key == "X-Dashboard-Secret" else default)
            status = {"code": None}
            headers: dict[str, str] = {}
            handler.send_response = lambda code: status.__setitem__("code", code)
            handler.send_header = lambda key, value: headers.__setitem__(key, value)
            handler.end_headers = lambda: None
            handler.do_GET()
            return status["code"], headers, handler.wfile.getvalue()

        status, headers, body = invoke("/api/dashboard")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf8"))
        self.assertEqual(payload["recent_runs"][0]["top_doc"], "billing.md")
        self.assertIn("application/json", headers["Content-Type"])

        status, headers, body = invoke("/dashboard")
        self.assertEqual(status, 200)
        html = body.decode("utf8")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("Recent Feedback", html)

        status, headers, body = invoke("/api/proof")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf8"))
        self.assertEqual(payload["case_studies"][0]["top_doc"], "billing.md")

        status, headers, body = invoke("/proof")
        self.assertEqual(status, 200)
        html = body.decode("utf8")
        self.assertIn("Accepted Proof Points", html)

    def test_server_rejects_dashboard_without_secret_header(self):
        def invoke(path: str, provided_secret: Optional[str] = None) -> tuple[int, dict[str, str], bytes]:
            handler = AppHandler.__new__(AppHandler)
            handler.path = path
            handler.config = ServiceConfig(docs_root=".", novyx_store=FakeStore(), dashboard_secret="top-secret")
            handler.wfile = BytesIO()
            handler.headers = SimpleNamespace(get=lambda key, default=None: provided_secret if key == "X-Dashboard-Secret" else default)
            status = {"code": None}
            headers: dict[str, str] = {}
            handler.send_response = lambda code: status.__setitem__("code", code)
            handler.send_header = lambda key, value: headers.__setitem__(key, value)
            handler.end_headers = lambda: None
            handler.do_GET()
            return status["code"], headers, handler.wfile.getvalue()

        status, headers, body = invoke("/api/dashboard")
        self.assertEqual(status, 401)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body.decode("utf8"))["error"], "Unauthorized")

        status, _, _ = invoke("/dashboard")
        self.assertEqual(status, 401)

        status, headers, body = invoke("/api/dashboard", provided_secret="top-secret")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body.decode("utf8"))["recent_runs"][0]["top_doc"], "billing.md")


if __name__ == "__main__":
    unittest.main()

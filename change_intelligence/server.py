from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path

from .dashboard import build_dashboard_payload, render_dashboard_html
from .github_client import GitHubClient
from .novyx_store import NovyxConfig, NovyxStore
from .service import ServiceConfig, process_github_event


class AppHandler(BaseHTTPRequestHandler):
    config: ServiceConfig

    def _json(self, status_code: int, payload):
        body = json.dumps(payload, indent=2).encode("utf8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status_code: int, body_text: str):
        body = body_text.encode("utf8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if self.path == "/api/dashboard":
            self._json(200, build_dashboard_payload(self.config.novyx_store))
            return
        if self.path == "/dashboard":
            payload = build_dashboard_payload(self.config.novyx_store)
            self._html(200, render_dashboard_html(payload))
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/webhooks/github":
            self._json(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf8")
        result = process_github_event(
            raw_body,
            self.headers.get("X-Hub-Signature-256"),
            self.config,
        )
        self._json(result["status_code"], result["payload"])


def build_config() -> ServiceConfig:
    docs_root = Path(os.environ.get("DOCS_ROOT", "docs")).resolve()
    docs_repo = os.environ.get("DOCS_REPO")
    docs_path = os.environ.get("DOCS_PATH", "docs")
    ownership_rules_path = os.environ.get("DOC_OWNERSHIP_RULES_PATH")
    confidence_threshold = int(os.environ.get("CONFIDENCE_THRESHOLD", "60"))
    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    novyx_key = os.environ.get("NOVYX_API_KEY")
    novyx_url = os.environ.get("NOVYX_API_URL")
    novyx_agent_id = os.environ.get("NOVYX_AGENT_ID", "change-intelligence")
    github_client = GitHubClient.from_env()
    store = None
    if novyx_key:
        store = NovyxStore(
            NovyxConfig(
                api_key=novyx_key,
                api_url=novyx_url,
                agent_id=novyx_agent_id,
            )
        )
    return ServiceConfig(
        docs_root=docs_root,
        docs_repo=docs_repo,
        docs_path=docs_path,
        ownership_rules_path=Path(ownership_rules_path).resolve() if ownership_rules_path else None,
        webhook_secret=webhook_secret,
        novyx_store=store,
        github_client=github_client,
        confidence_threshold=confidence_threshold,
    )


def run() -> None:
    port = int(os.environ.get("PORT", "3030"))
    handler = AppHandler
    handler.config = build_config()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"change-intelligence python server listening on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()

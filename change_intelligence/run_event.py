from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .github_client import GitHubClient
from .novyx_store import NovyxConfig, NovyxStore
from .service import ServiceConfig, process_github_event


def build_config() -> ServiceConfig:
    github_client = GitHubClient.from_env()
    novyx_key = os.environ.get("NOVYX_API_KEY")
    novyx_url = os.environ.get("NOVYX_API_URL")
    novyx_agent_id = os.environ.get("NOVYX_AGENT_ID", "change-intelligence")
    docs_root = Path(os.environ.get("DOCS_ROOT", "docs")).resolve()
    docs_repo = os.environ.get("DOCS_REPO")
    docs_path = os.environ.get("DOCS_PATH", "docs")
    threshold = int(os.environ.get("CONFIDENCE_THRESHOLD", "60"))

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
        novyx_store=store,
        github_client=github_client,
        confidence_threshold=threshold,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run change-intelligence against a GitHub event payload.")
    parser.add_argument("--event-path", required=True, help="Path to a JSON file containing the event payload")
    args = parser.parse_args()

    raw_body = Path(args.event_path).read_text(encoding="utf8")
    result = process_github_event(raw_body, None, build_config())
    print(json.dumps(result["payload"], indent=2))


if __name__ == "__main__":
    main()

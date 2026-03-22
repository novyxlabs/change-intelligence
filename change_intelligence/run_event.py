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
    ownership_rules_path = os.environ.get("DOC_OWNERSHIP_RULES_PATH")
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
        ownership_rules_path=Path(ownership_rules_path).resolve() if ownership_rules_path else None,
        novyx_store=store,
        github_client=github_client,
        confidence_threshold=threshold,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run change-intelligence against a GitHub event payload.")
    parser.add_argument("--event-path", required=True, help="Path to a JSON file containing the event payload")
    parser.add_argument("--output-path", help="Optional path to write the JSON payload result")
    args = parser.parse_args()

    raw_body = Path(args.event_path).read_text(encoding="utf8")
    result = process_github_event(raw_body, None, build_config())
    rendered = json.dumps(result["payload"], indent=2)
    if args.output_path:
        Path(args.output_path).write_text(rendered, encoding="utf8")
    print(rendered)


if __name__ == "__main__":
    main()

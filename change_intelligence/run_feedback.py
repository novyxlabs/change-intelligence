from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .feedback import process_feedback_event
from .github_client import GitHubClient
from .novyx_store import NovyxConfig, NovyxStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a GitHub issue_comment payload for CI feedback.")
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--output-path")
    args = parser.parse_args()

    store = NovyxStore(
        NovyxConfig(
            api_key=os.environ["NOVYX_API_KEY"],
            api_url=os.environ.get("NOVYX_API_URL"),
            agent_id=os.environ.get("NOVYX_AGENT_ID", "change-intelligence"),
        )
    )
    if GitHubClient.from_env() is None:
        raise SystemExit("GITHUB_TOKEN or GitHub App credentials are required for trusted feedback capture.")
    payload = process_feedback_event(Path(args.event_path).read_text(encoding="utf8"), store)
    rendered = json.dumps(payload, indent=2)
    if args.output_path:
        Path(args.output_path).write_text(rendered, encoding="utf8")
    print(rendered)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List

from .github_client import COMMENT_MARKER, GitHubClient


def parse_repositories(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def has_change_intelligence_comment(github: GitHubClient, owner: str, repo: str, issue_number: int) -> bool:
    token = github._installation_token(None)
    response = github._request(
        "GET",
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        token=token,
        params={"per_page": 100},
    )
    comments = response.json()
    return any(COMMENT_MARKER in (item.get("body") or "") for item in comments)


def dispatch_analysis(github: GitHubClient, repository: str, pull_request: Dict[str, object]) -> None:
    owner, repo = repository.split("/", 1)
    token = github._installation_token(None)
    github._request(
        "POST",
        "/repos/novyxlabs/change-intelligence/dispatches",
        token=token,
        json_data={
            "event_type": "analyze-pr",
            "client_payload": {
                "action": "opened",
                "repository": {"full_name": repository},
                "pull_request": {
                    "number": int(pull_request["number"]),
                    "title": pull_request.get("title", ""),
                    "html_url": pull_request.get("html_url", ""),
                    "merged_at": pull_request.get("merged_at"),
                    "head": {"sha": ((pull_request.get("head") or {}).get("sha") or "")},
                },
            },
        },
    )


def sweep(github: GitHubClient, repositories: List[str]) -> Dict[str, object]:
    dispatched = []
    skipped = []

    for repository in repositories:
        owner, repo = repository.split("/", 1)
        pulls = github.pull_requests(owner, repo, state="open", per_page=50)
        for pull in pulls:
            number = int(pull["number"])
            if has_change_intelligence_comment(github, owner, repo, number):
                skipped.append({"repository": repository, "pull_request": number, "reason": "already-commented"})
                continue
            dispatch_analysis(github, repository, pull)
            dispatched.append({"repository": repository, "pull_request": number})

    return {"repositories": repositories, "dispatched": dispatched, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch Change Intelligence for open PRs missing comments.")
    parser.add_argument(
        "--repositories",
        default=os.environ.get(
            "CHANGE_INTELLIGENCE_SWEEP_REPOS",
            "novyxlabs/novyx-core,novyxlabs/novyx-mcp,novyxlabs/novyx-starter-kit,novyxlabs/novyx-memory-skill,novyxlabs/novyx-vault,novyxlabs/novyx-site",
        ),
    )
    args = parser.parse_args()

    github = GitHubClient.from_env()
    if github is None:
        raise SystemExit("GITHUB_TOKEN or GitHub App credentials are required.")

    result = sweep(github, parse_repositories(args.repositories))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

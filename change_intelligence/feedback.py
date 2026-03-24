from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .github_client import COMMENT_MARKER, GitHubClient
from .novyx_store import NovyxStore


VALID_COMMANDS = {"/ci correct", "/ci wrong-doc", "/ci missed-doc"}
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
TRUSTED_PERMISSIONS = {"write", "maintain", "admin"}


def parse_feedback_command(body: str) -> Optional[str]:
    for line in body.splitlines():
        normalized = line.strip().lower()
        if normalized in VALID_COMMANDS:
            return normalized
    return None


def process_feedback_event(raw_body: str, store: NovyxStore) -> dict[str, object]:
    payload = json.loads(raw_body)
    repository = (payload.get("repository") or {}).get("full_name") or "unknown/repo"
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    command = parse_feedback_command(comment.get("body") or "")

    if not issue.get("pull_request"):
        return {"ok": False, "ignored": True, "reason": "not-a-pull-request-comment"}
    if not command:
        return {"ok": False, "ignored": True, "reason": "no-feedback-command"}
    if not is_trusted_feedback(payload):
        return {"ok": False, "ignored": True, "reason": "untrusted-feedback"}

    result = store.record_feedback(
        repository=repository,
        pull_request_number=int(issue.get("number") or 0),
        command=command,
        commenter=((comment.get("user") or {}).get("login") or "unknown"),
        comment_url=comment.get("html_url") or "",
    )
    return {
        "ok": True,
        "repository": repository,
        "pull_request_number": int(issue.get("number") or 0),
        "feedback": result["feedback"],
        "comment_url": comment.get("html_url"),
        "graph_update": result.get("graph_update"),
        "audit_entries": result.get("audit_entries"),
    }


def is_trusted_feedback(payload: dict[str, object]) -> bool:
    repository = (payload.get("repository") or {}).get("full_name") or ""
    if "/" not in repository:
        return False
    owner, repo = repository.split("/", 1)
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    issue_number = int(issue.get("number") or 0)
    comment_url = comment.get("html_url") or ""
    commenter = ((comment.get("user") or {}).get("login") or "").strip()
    if not issue_number or not comment_url or not commenter:
        return False

    github = GitHubClient.from_env()
    if github is None:
        return False

    installation_id = (payload.get("installation") or {}).get("id")
    if not isinstance(installation_id, int) and getattr(github, "auth_mode", lambda: "none")() == "app":
        installation_id = github.repository_installation_id(owner, repo)

    comments = github.issue_comments(owner, repo, issue_number, installation_id=installation_id)
    ci_comment_present = any(COMMENT_MARKER in (item.get("body") or "") for item in comments)
    if not ci_comment_present:
        return False

    matching = next((item for item in comments if item.get("html_url") == comment_url), None)
    if matching is None:
        return False

    author = (matching.get("user") or {}).get("login") or ""
    if author.lower() != commenter.lower():
        return False

    association = str(matching.get("author_association") or "").upper()
    if association in TRUSTED_ASSOCIATIONS:
        return True

    permission = github.user_permission(owner, repo, commenter, installation_id=installation_id)
    return permission in TRUSTED_PERMISSIONS


def write_json(path: str, payload: dict[str, object]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf8")

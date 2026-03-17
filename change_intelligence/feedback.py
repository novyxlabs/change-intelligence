from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .novyx_store import NovyxStore


VALID_COMMANDS = {"/ci correct", "/ci wrong-doc", "/ci missed-doc"}


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
    }


def write_json(path: str, payload: dict[str, object]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf8")

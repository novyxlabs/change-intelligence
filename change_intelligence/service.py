from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import hmac
import json
from typing import Dict, List, Optional, Sequence, Set

from .analysis import analyze_patch, render_markdown
from .github_client import GitHubClient, build_patch_from_files
from .novyx_store import NovyxStore


@dataclass
class ServiceConfig:
    docs_root: Path
    docs_repo: Optional[str] = None
    docs_path: str = "docs"
    webhook_secret: str = ""
    novyx_store: Optional[NovyxStore] = None
    github_client: Optional[GitHubClient] = None
    confidence_threshold: int = 60


def verify_signature(secret: str, raw_body: str, header: Optional[str]) -> bool:
    if not secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf8"),
        raw_body.encode("utf8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, header)


def split_repository(full_name: str) -> tuple[str, str]:
    owner, repo = full_name.split("/", 1)
    return owner, repo


def is_doc_path(path: str, docs_path: str) -> bool:
    normalized = docs_path.strip("/")
    return path.startswith(f"{normalized}/") and path.lower().endswith((".md", ".mdx", ".txt"))


def normalize_doc_path(path: str, docs_path: str) -> str:
    normalized = docs_path.strip("/")
    if path.startswith(f"{normalized}/"):
        return path[len(normalized) + 1 :]
    return Path(path).name


def filter_comment_recommendations(recommendations: Sequence[Dict[str, object]], threshold: int) -> List[Dict[str, object]]:
    return [item for item in recommendations if int(item.get("confidence", 0)) >= threshold]


def apply_learning_feedback(
    learned_signals: Dict[str, Dict[str, object]],
    learning_feedback: Optional[Dict[str, Sequence[str]]],
) -> Dict[str, Dict[str, object]]:
    signals = {
        key: {
            "graph_hits": int(value.get("graph_hits", 0)),
            "accepted_hits": int(value.get("accepted_hits", 0)),
            "rejected_hits": int(value.get("rejected_hits", 0)),
        }
        for key, value in learned_signals.items()
    }
    if not learning_feedback:
        return signals

    for doc in learning_feedback.get("accepted", []):
        bucket = signals.setdefault(doc, {"graph_hits": 0, "accepted_hits": 0, "rejected_hits": 0})
        bucket["graph_hits"] += 1
        bucket["accepted_hits"] += 1

    for doc in learning_feedback.get("missed", []):
        bucket = signals.setdefault(doc, {"graph_hits": 0, "accepted_hits": 0, "rejected_hits": 0})
        bucket["graph_hits"] += 1
        bucket["accepted_hits"] += 1

    for doc in learning_feedback.get("rejected", []):
        bucket = signals.setdefault(doc, {"graph_hits": 0, "accepted_hits": 0, "rejected_hits": 0})
        bucket["rejected_hits"] += 1

    return signals


def build_comment(
    repository: str,
    pull_request_number: int,
    summary: Dict[str, object],
    recommendations: Sequence[Dict[str, object]],
    patterns: Sequence[Dict[str, object]],
    threshold: int,
) -> str:
    lines = [
        "## Change Intelligence",
        "",
        f"Repository: `{repository}`",
        f"Pull request: #{pull_request_number}",
        f"Confidence threshold: `{threshold}`",
        "",
    ]
    if patterns:
        lines.extend(["### Similar Historical Patterns", ""])
        for item in patterns[:5]:
            lines.append(
                f"- {item['observation']}"
                + (f" (score: {item['score']})" if item.get("score") is not None else "")
            )
        lines.append("")
    lines.append(render_markdown(summary, recommendations))
    lines.extend(
        [
            "",
            "---",
            "<!-- ci-feedback: pending -->",
            "Reply with `/ci correct`, `/ci wrong-doc`, or `/ci missed-doc`.",
        ]
    )
    return "\n".join(lines)


def process_github_event(raw_body: str, signature: Optional[str], config: ServiceConfig) -> Dict[str, object]:
    if not verify_signature(config.webhook_secret, raw_body, signature):
        return {"status_code": 401, "payload": {"error": "Invalid signature"}}

    payload = json.loads(raw_body)
    action = payload.get("action")
    pull_request = payload.get("pull_request") or {}
    repository = (payload.get("repository") or {}).get("full_name") or "unknown/repo"
    pull_request_number = pull_request.get("number") or 0
    head_sha = ((pull_request.get("head") or {}).get("sha")) or None
    owner, repo = split_repository(repository)
    docs_repo = config.docs_repo or repository
    docs_owner, docs_repo_name = split_repository(docs_repo)
    installation_id = (payload.get("installation") or {}).get("id")
    patch = pull_request.get("patch") or payload.get("patch")

    files: List[Dict[str, object]] = []
    code_files: List[Dict[str, object]] = []
    docs = None
    if config.github_client is not None:
        ref = ((pull_request.get("head") or {}).get("sha")) or None
        docs = config.github_client.repo_docs(
            docs_owner,
            docs_repo_name,
            config.docs_path,
            None if docs_repo != repository else ref,
            installation_id,
        )
        files = config.github_client.pull_request_files(
            owner,
            repo,
            pull_request_number,
            installation_id,
        )
        code_files = [
            item
            for item in files
            if item.get("filename") and not is_doc_path(str(item["filename"]), config.docs_path)
        ]
        if not patch:
            patch = build_patch_from_files(code_files)

    if not patch:
        return {
            "status_code": 400,
            "payload": {
                "error": "Missing patch text. Provide pull_request.patch, patch, or configure GitHub API access."
            },
        }

    actual_docs_changed = {
        normalize_doc_path(str(item["filename"]), config.docs_path)
        for item in files
        if item.get("filename") and is_doc_path(str(item["filename"]), config.docs_path)
    }

    changed_file_names = [str(item["filename"]) for item in code_files if item.get("filename")]
    module_terms = [
        Path(path).parts[1] if len(Path(path).parts) > 1 else Path(path).stem
        for path in changed_file_names
    ]
    query = f"{repository} changed modules: {', '.join(module_terms[:3])}"

    patterns: List[Dict[str, object]] = []
    learned_signals: Dict[str, Dict[str, object]] = {}
    if config.novyx_store is not None:
        try:
            patterns = config.novyx_store.recall_patterns(query)
        except Exception:
            patterns = []
        try:
            learned_signals = config.novyx_store.rank_signals(repository, changed_file_names)
        except Exception:
            learned_signals = {}

    analysis = analyze_patch(
        patch,
        docs_root=config.docs_root,
        docs=docs,
        learned_signals=learned_signals,
        patterns=patterns,
        actual_docs_changed=actual_docs_changed if pull_request.get("merged_at") else None,
    )

    learning_feedback = None
    if config.novyx_store is not None and pull_request.get("merged_at"):
        try:
            learning_feedback = config.novyx_store.learn_from_merge(
                repository,
                pull_request_number,
                analysis["summary"]["changed_files"],
                [item["relative_path"] for item in analysis["recommendations"]],
                sorted(actual_docs_changed),
            )
        except Exception:
            learning_feedback = None
        try:
            patterns = config.novyx_store.recall_patterns(query)
        except Exception:
            patterns = patterns
        try:
            learned_signals = apply_learning_feedback(
                config.novyx_store.rank_signals(repository, changed_file_names),
                learning_feedback,
            )
        except Exception:
            learned_signals = apply_learning_feedback(learned_signals, learning_feedback)
        analysis = analyze_patch(
            patch,
            docs_root=config.docs_root,
            docs=docs,
            learned_signals=learned_signals,
            patterns=patterns,
            actual_docs_changed=actual_docs_changed,
        )

    comment_recommendations = filter_comment_recommendations(
        analysis["recommendations"],
        config.confidence_threshold,
    )
    comment_suppressed = len(comment_recommendations) == 0
    comment_body = None
    comment = None

    trace = None
    if config.novyx_store is not None:
        try:
            trace = config.novyx_store.record_analysis(
                repository,
                pull_request_number,
                analysis["summary"]["changed_files"],
                analysis["recommendations"],
                comment_suppressed=comment_suppressed,
                head_sha=head_sha,
            )
        except Exception:
            trace = None

    if not comment_suppressed:
        comment_body = build_comment(
            repository,
            pull_request_number,
            analysis["summary"],
            comment_recommendations,
            patterns,
            config.confidence_threshold,
        )
        if config.github_client is not None and pull_request_number:
            comment = config.github_client.upsert_issue_comment(
                owner,
                repo,
                pull_request_number,
                installation_id,
                comment_body,
            )
    elif config.github_client is not None and pull_request_number:
        comment = config.github_client.clear_issue_comment(
            owner,
            repo,
            pull_request_number,
            installation_id,
        )

    return {
        "status_code": 200,
        "payload": {
            "ok": True,
            "action": action,
            "repository": repository,
            "pull_request_number": pull_request_number,
            "summary": analysis["summary"],
            "recommendations": analysis["recommendations"],
            "historical_patterns": patterns,
            "learned_signals": learned_signals,
            "learning_feedback": learning_feedback,
            "trace": trace,
            "comment_body": comment_body,
            "comment": comment,
            "comment_suppressed": comment_suppressed,
            "confidence_threshold": config.confidence_threshold,
        },
    }

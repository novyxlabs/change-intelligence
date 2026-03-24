from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import hmac
import json
import requests
from typing import Dict, List, Optional, Sequence, Set

from .analysis import analyze_patch, render_markdown
from .feedback import process_feedback_event
from .github_client import GitHubClient, build_patch_from_files
from .novyx_store import NovyxStore


@dataclass
class ServiceConfig:
    docs_root: Path
    docs_repo: Optional[str] = None
    docs_path: str = "docs"
    ownership_rules_path: Optional[Path] = None
    webhook_secret: str = ""
    dashboard_secret: str = ""
    novyx_store: Optional[NovyxStore] = None
    github_client: Optional[GitHubClient] = None
    confidence_threshold: int = 60


@dataclass
class EventContext:
    action: Optional[str]
    repository: str
    pull_request: Dict[str, object]
    pull_request_number: int
    head_sha: Optional[str]
    owner: str
    repo: str
    installation_id: Optional[int]
    patch: Optional[str]
    files: List[Dict[str, object]]
    code_files: List[Dict[str, object]]
    docs: Optional[Sequence[Dict[str, str]]]
    docs_path_used: str
    actual_docs_changed: Set[str]
    changed_file_names: List[str]
    query: str


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
    eligible = [item for item in recommendations if int(item.get("confidence", 0)) >= threshold]
    if not eligible:
        return []

    top_confidence = int(eligible[0].get("confidence", 0) or 0)
    top_surface_count = int(eligible[0].get("surface_match_count", 0) or 0)
    if top_surface_count > 0:
        exact_matches = [
            item
            for item in eligible
            if int(item.get("surface_match_count", 0) or 0) > 0
        ]
        viable_exact_matches = [
            item
            for item in exact_matches
            if int(item.get("score", 0) or 0) > 0
        ]
        if viable_exact_matches:
            return viable_exact_matches[:3]
        if exact_matches:
            return exact_matches[:3]

    pruned: List[Dict[str, object]] = []
    for item in eligible:
        confidence = int(item.get("confidence", 0) or 0)
        evidence = item.get("evidence") or []
        has_exact_surface = any("Mentions changed routes or APIs:" in str(line) for line in evidence)
        if item is eligible[0] or has_exact_surface or confidence >= top_confidence - 12:
            pruned.append(item)
        if len(pruned) >= 5:
            break
    return pruned


def filter_comment_patterns(
    patterns: Sequence[Dict[str, object]],
    recommendations: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    if not patterns:
        return []
    if not recommendations:
        return list(patterns[:3])

    target_paths = {
        str(item.get("relative_path") or "")
        for item in recommendations
        if str(item.get("relative_path") or "")
    }
    target_names = {Path(path).name for path in target_paths}
    top_surface_count = int(recommendations[0].get("surface_match_count", 0) or 0)
    filtered = [
        item
        for item in patterns
        if any(target in str(item.get("observation") or "") for target in [*target_paths, *target_names])
    ]

    if top_surface_count > 0:
        return filtered[:3]
    if filtered:
        return filtered[:3]
    return list(patterns[:3])


def classify_confidence_tier(recommendations: Sequence[Dict[str, object]], threshold: int) -> str:
    top_confidence = int((recommendations[0].get("confidence", 0) if recommendations else 0) or 0)
    if top_confidence >= max(85, threshold + 15):
        return "high-confidence"
    if top_confidence >= threshold:
        return "review-recommended"
    return "silent"


def apply_learning_feedback(
    learned_signals: Dict[str, Dict[str, object]],
    learning_feedback: Optional[Dict[str, Sequence[str]]],
) -> Dict[str, Dict[str, object]]:
    signals = {
        key: {
            "graph_hits": int(value.get("graph_hits", 0)),
            "accepted_hits": int(value.get("accepted_hits", 0)),
            "rejected_hits": int(value.get("rejected_hits", 0)),
            "missed_hits": int(value.get("missed_hits", 0)),
            "exact_file_hits": int(value.get("exact_file_hits", 0)),
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
        bucket["missed_hits"] = int(bucket.get("missed_hits", 0)) + 1

    for doc in learning_feedback.get("rejected", []):
        bucket = signals.setdefault(doc, {"graph_hits": 0, "accepted_hits": 0, "rejected_hits": 0})
        bucket["rejected_hits"] += 1

    return signals


def summarize_change_shape(
    summary: Dict[str, object],
    support_updates: Dict[str, object],
    onboarding_updates: Dict[str, object],
) -> List[str]:
    bullets: List[str] = []
    changed_surfaces = summary.get("changed_surfaces", [])
    changed_symbols = summary.get("changed_symbols", [])

    if changed_surfaces:
        bullets.append(
            "API or route behavior changed: "
            + ", ".join(f"`{item}`" for item in changed_surfaces[:3])
            + "."
        )
    if onboarding_updates.get("included_in_report"):
        bullets.append("Onboarding or setup guidance is likely affected by this PR.")
    if support_updates.get("included_in_report"):
        bullets.append("Support-facing answers or troubleshooting docs are likely affected.")
    if not bullets and changed_symbols:
        bullets.append(
            "Implementation behavior changed in: "
            + ", ".join(f"`{item}`" for item in changed_symbols[:4])
            + "."
        )
    if not bullets:
        bullets.append("Product behavior changed in a way that may have left docs behind.")
    return bullets[:3]


def summarize_confidence_reasons(recommendations: Sequence[Dict[str, object]]) -> List[str]:
    if not recommendations:
        return []

    evidence = recommendations[0].get("evidence", [])
    reasons: List[str] = []

    if any("Mentions changed routes or APIs:" in item for item in evidence):
        reasons.append("Exact route or API surface matches were found in the top doc.")
    if any("Mentions changed symbols:" in item for item in evidence):
        reasons.append("The top doc mentions the changed symbols directly.")
    if any("Ownership rule matched" in item for item in evidence):
        reasons.append("Repo-specific ownership rules map this code area to the doc target.")
    if any("Learned Novyx graph links" in item or "Past merged PRs reinforced" in item for item in evidence):
        reasons.append("Novyx memory reinforced this doc target from prior repo history.")
    if any("Shared path terms" in item or "Shared change terms" in item for item in evidence):
        reasons.append("The diff language overlaps strongly with the doc content.")

    if not reasons:
        reasons.append("The ranking combined diff overlap, symbol matches, and repo history into a strong target.")
    return reasons[:3]


def summarize_risk_if_ignored(
    summary: Dict[str, object],
    recommendations: Sequence[Dict[str, object]],
    support_updates: Dict[str, object],
    onboarding_updates: Dict[str, object],
) -> List[str]:
    risks: List[str] = []
    changed_surfaces = summary.get("changed_surfaces", [])

    if recommendations:
        top_doc = recommendations[0]["relative_path"]
        if changed_surfaces:
            risks.append(
                f"`{top_doc}` is likely now misleading about "
                + ", ".join(f"`{item}`" for item in changed_surfaces[:3])
                + "."
            )
        else:
            risks.append(f"`{top_doc}` is likely now out of sync with the current product behavior.")
    if onboarding_updates.get("included_in_report"):
        risks.append("New users may hit outdated setup or first-run guidance.")
    if support_updates.get("included_in_report"):
        risks.append("Support may answer from stale troubleshooting or FAQ content.")
    if not risks:
        risks.append("Reviewers may merge a product change while leaving the written behavior behind.")
    return risks[:3]


def summarize_trust_signals(
    recommendations: Sequence[Dict[str, object]],
    threshold: int,
) -> List[str]:
    if not recommendations:
        return [f"No doc cleared the comment threshold of `{threshold}`."]

    top = recommendations[0]
    signals: List[str] = []
    surface_match_count = int(top.get("surface_match_count", 0) or 0)
    accepted_hits = int(top.get("accepted_hits", 0) or 0)
    exact_file_hits = int(top.get("exact_file_hits", 0) or 0)
    rejected_hits = int(top.get("rejected_hits", 0) or 0)
    confidence = int(top.get("confidence", 0) or 0)

    if surface_match_count > 0:
        signals.append(f"Top doc covers `{surface_match_count}` changed API surfaces directly.")
    if accepted_hits > 0 or exact_file_hits > 0:
        signals.append(
            f"Repo memory contributed `{accepted_hits}` accepted confirmations and `{exact_file_hits}` exact file-to-doc matches."
        )
    if rejected_hits > 0:
        signals.append(f"Negative memory is present too: `{rejected_hits}` similar rejections were considered.")
    signals.append(f"Comment cleared the gate at `{confidence}` confidence against a `{threshold}` threshold.")
    signals.append(f"Only `{len(recommendations)}` doc target{'s' if len(recommendations) != 1 else ''} survived comment pruning.")
    return signals[:4]


def build_comment(
    repository: str,
    pull_request_number: int,
    summary: Dict[str, object],
    recommendations: Sequence[Dict[str, object]],
    patterns: Sequence[Dict[str, object]],
    threshold: int,
    support_updates: Dict[str, object],
    onboarding_updates: Dict[str, object],
) -> str:
    lines = [
        "## Change Intelligence",
        "",
        f"Repository: `{repository}`",
        f"Pull request: #{pull_request_number}",
        f"Confidence threshold: `{threshold}`",
        f"Tier: `{classify_confidence_tier(recommendations, threshold)}`",
        "",
    ]
    lines.extend(["### What Changed", ""])
    for bullet in summarize_change_shape(summary, support_updates, onboarding_updates):
        lines.append(f"- {bullet}")
    lines.append("")

    lines.extend(["### Why This Is High Confidence", ""])
    for bullet in summarize_confidence_reasons(recommendations):
        lines.append(f"- {bullet}")
    lines.append("")

    lines.extend(["### Risk If Ignored", ""])
    for bullet in summarize_risk_if_ignored(summary, recommendations, support_updates, onboarding_updates):
        lines.append(f"- {bullet}")
    lines.append("")

    lines.extend(["### Trust Signals", ""])
    for bullet in summarize_trust_signals(recommendations, threshold):
        lines.append(f"- {bullet}")
    lines.append("")

    if patterns:
        lines.extend(["### Similar Historical Patterns", ""])
        for item in patterns[:3]:
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


def collect_event_context(payload: Dict[str, object], config: ServiceConfig) -> EventContext:
    action = payload.get("action")
    pull_request = payload.get("pull_request") or {}
    repository = (payload.get("repository") or {}).get("full_name") or "unknown/repo"
    pull_request_number = int(pull_request.get("number") or payload.get("number") or 0)
    head_sha = ((pull_request.get("head") or {}).get("sha")) or None
    owner, repo = split_repository(repository)
    docs_repo = config.docs_repo or repository
    docs_owner, docs_repo_name = split_repository(docs_repo)
    docs_path_used = config.docs_path
    installation_id = (payload.get("installation") or {}).get("id")
    if installation_id is None and config.github_client is not None and config.github_client.auth_mode() == "app":
        installation_id = config.github_client.repository_installation_id(owner, repo)
    patch = pull_request.get("patch") or payload.get("patch")

    files: List[Dict[str, object]] = []
    code_files: List[Dict[str, object]] = []
    docs = None
    if config.github_client is not None:
        ref = ((pull_request.get("head") or {}).get("sha")) or None
        docs_ref = None if docs_repo != repository else ref
        try:
            docs = config.github_client.repo_docs(
                docs_owner,
                docs_repo_name,
                config.docs_path,
                docs_ref,
                installation_id,
            )
        except requests.HTTPError as error:
            can_autodetect = (
                error.response is not None
                and error.response.status_code == 404
                and config.docs_path.strip("/") == "docs"
            )
            if not can_autodetect:
                raise
            detected_path = config.github_client.discover_docs_path(
                docs_owner,
                docs_repo_name,
                installation_id,
                docs_ref,
                preferred=config.docs_path,
            )
            if not detected_path or detected_path == config.docs_path.strip("/"):
                raise
            docs_path_used = detected_path
            docs = config.github_client.repo_docs(
                docs_owner,
                docs_repo_name,
                docs_path_used,
                docs_ref,
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
            if item.get("filename") and not is_doc_path(str(item["filename"]), docs_path_used)
        ]
        if not patch:
            patch = build_patch_from_files(code_files)

    actual_docs_changed = {
        normalize_doc_path(str(item["filename"]), docs_path_used)
        for item in files
        if item.get("filename") and is_doc_path(str(item["filename"]), docs_path_used)
    }

    changed_file_names = [str(item["filename"]) for item in code_files if item.get("filename")]
    module_terms = [
        Path(path).parts[1] if len(Path(path).parts) > 1 else Path(path).stem
        for path in changed_file_names
    ]
    query = f"{repository} changed modules: {', '.join(module_terms[:3])}"

    return EventContext(
        action=action,
        repository=repository,
        pull_request=pull_request,
        pull_request_number=pull_request_number,
        head_sha=head_sha,
        owner=owner,
        repo=repo,
        installation_id=installation_id,
        patch=patch,
        files=files,
        code_files=code_files,
        docs=docs,
        docs_path_used=docs_path_used,
        actual_docs_changed=actual_docs_changed,
        changed_file_names=changed_file_names,
        query=query,
    )


def run_analysis_cycle(
    context: EventContext,
    config: ServiceConfig,
) -> tuple[Dict[str, object], List[Dict[str, object]], Dict[str, Dict[str, object]], Optional[Dict[str, Sequence[str]]]]:
    patterns: List[Dict[str, object]] = []
    learned_signals: Dict[str, Dict[str, object]] = {}

    if config.novyx_store is not None:
        try:
            patterns = config.novyx_store.recall_patterns(context.query)
        except Exception:
            patterns = []
        try:
            learned_signals = config.novyx_store.rank_signals(
                context.repository,
                context.changed_file_names,
            )
        except Exception:
            learned_signals = {}

    analysis = analyze_patch(
        context.patch or "",
        docs_root=config.docs_root,
        docs=context.docs,
        learned_signals=learned_signals,
        patterns=patterns,
        actual_docs_changed=context.actual_docs_changed if context.pull_request.get("merged_at") else None,
        repository=context.repository,
        ownership_rules_path=config.ownership_rules_path,
    )

    learning_feedback = None
    if config.novyx_store is not None and context.pull_request.get("merged_at"):
        try:
            learning_feedback = config.novyx_store.learn_from_merge(
                context.repository,
                context.pull_request_number,
                analysis["summary"]["changed_files"],
                [item["relative_path"] for item in analysis["recommendations"]],
                sorted(context.actual_docs_changed),
            )
        except Exception:
            learning_feedback = None
        try:
            patterns = config.novyx_store.recall_patterns(context.query)
        except Exception:
            pass
        try:
            learned_signals = apply_learning_feedback(
                config.novyx_store.rank_signals(context.repository, context.changed_file_names),
                learning_feedback,
            )
        except Exception:
            learned_signals = apply_learning_feedback(learned_signals, learning_feedback)
        analysis = analyze_patch(
            context.patch or "",
            docs_root=config.docs_root,
            docs=context.docs,
            learned_signals=learned_signals,
            patterns=patterns,
            actual_docs_changed=context.actual_docs_changed,
            repository=context.repository,
            ownership_rules_path=config.ownership_rules_path,
        )

    return analysis, patterns, learned_signals, learning_feedback


def finalize_event_response(
    context: EventContext,
    config: ServiceConfig,
    analysis: Dict[str, object],
    patterns: Sequence[Dict[str, object]],
    learned_signals: Dict[str, Dict[str, object]],
    learning_feedback: Optional[Dict[str, Sequence[str]]],
) -> Dict[str, object]:
    confidence_tier = classify_confidence_tier(analysis["recommendations"], config.confidence_threshold)
    comment_recommendations = filter_comment_recommendations(
        analysis["recommendations"],
        config.confidence_threshold,
    )
    comment_patterns = filter_comment_patterns(patterns, comment_recommendations)
    comment_suppressed = len(comment_recommendations) == 0
    comment_body = None
    comment = None
    side_effects = {
        "novyx_record": {"ok": config.novyx_store is None, "status": "disabled" if config.novyx_store is None else "pending"},
        "github_comment": {"ok": config.github_client is None, "status": "disabled" if config.github_client is None else "pending"},
    }

    trace = None
    if config.novyx_store is not None:
        try:
            trace = config.novyx_store.record_analysis(
                context.repository,
                context.pull_request_number,
                analysis["summary"]["changed_files"],
                analysis["recommendations"],
                confidence_tier=confidence_tier,
                comment_suppressed=comment_suppressed,
                head_sha=context.head_sha,
                docs_repo=config.docs_repo or context.repository,
                docs_path=context.docs_path_used,
                action=context.action,
                patterns=patterns,
                learned_signals=learned_signals,
                learning_feedback=learning_feedback,
                release_notes=analysis["release_notes"],
                support_updates=analysis["support_updates"],
                onboarding_updates=analysis["onboarding_updates"],
                summary=analysis["summary"],
                side_effects=side_effects,
            )
            side_effects["novyx_record"] = {"ok": True, "status": "recorded"}
        except Exception:
            trace = None
            side_effects["novyx_record"] = {"ok": False, "status": "failed", "error": "record_analysis_failed"}

    if not comment_suppressed:
        comment_body = build_comment(
            context.repository,
            context.pull_request_number,
            analysis["summary"],
            comment_recommendations,
            comment_patterns,
            config.confidence_threshold,
            analysis["support_updates"],
            analysis["onboarding_updates"],
        )
        if config.github_client is not None and context.pull_request_number:
            try:
                comment = config.github_client.upsert_issue_comment(
                    context.owner,
                    context.repo,
                    context.pull_request_number,
                    context.installation_id,
                    comment_body,
                )
                side_effects["github_comment"] = {"ok": True, "status": "commented"}
            except Exception as error:
                comment = None
                side_effects["github_comment"] = {"ok": False, "status": "failed", "error": str(error)}
    elif config.github_client is not None and context.pull_request_number:
        try:
            comment = config.github_client.clear_issue_comment(
                context.owner,
                context.repo,
                context.pull_request_number,
                context.installation_id,
            )
            side_effects["github_comment"] = {"ok": True, "status": "cleared" if comment else "no-comment"}
        except Exception as error:
            comment = None
            side_effects["github_comment"] = {"ok": False, "status": "failed", "error": str(error)}
    elif config.github_client is None:
        side_effects["github_comment"] = {"ok": True, "status": "disabled"}

    return {
        "status_code": 200,
        "payload": {
            "ok": True,
            "action": context.action,
            "repository": context.repository,
            "docs_repo": config.docs_repo or context.repository,
            "docs_path": context.docs_path_used,
            "pull_request_number": context.pull_request_number,
            "summary": analysis["summary"],
            "recommendations": analysis["recommendations"],
            "release_notes": analysis["release_notes"],
            "support_updates": analysis["support_updates"],
            "onboarding_updates": analysis["onboarding_updates"],
            "historical_patterns": patterns,
            "learned_signals": learned_signals,
            "learning_feedback": learning_feedback,
            "trace": trace,
            "comment_body": comment_body,
            "comment": comment,
            "comment_suppressed": comment_suppressed,
            "confidence_tier": confidence_tier,
            "confidence_threshold": config.confidence_threshold,
            "side_effects": side_effects,
            "auth_mode": config.github_client.auth_mode() if config.github_client is not None else "none",
        },
    }


def process_github_event(raw_body: str, signature: Optional[str], config: ServiceConfig) -> Dict[str, object]:
    if not verify_signature(config.webhook_secret, raw_body, signature):
        return {"status_code": 401, "payload": {"error": "Invalid signature"}}

    payload = json.loads(raw_body)
    if (payload.get("issue") or {}).get("pull_request") and payload.get("comment"):
        if config.novyx_store is None:
            return {"status_code": 200, "payload": {"ok": False, "ignored": True, "reason": "feedback-store-unavailable"}}
        feedback_payload = process_feedback_event(
            raw_body,
            config.novyx_store,
            github_client=config.github_client,
        )
        return {"status_code": 200, "payload": feedback_payload}

    context = collect_event_context(payload, config)

    if not context.patch:
        return {
            "status_code": 400,
            "payload": {
                "error": "Missing patch text. Provide pull_request.patch, patch, or configure GitHub API access."
            },
        }

    analysis, patterns, learned_signals, learning_feedback = run_analysis_cycle(context, config)
    return finalize_event_response(
        context,
        config,
        analysis,
        patterns,
        learned_signals,
        learning_feedback,
    )

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List

from .novyx_store import NovyxConfig, NovyxStore


def repository_for(memory: Dict[str, object]) -> str:
    metadata = memory.get("metadata")
    if isinstance(metadata, dict):
        repository = metadata.get("repository")
        if isinstance(repository, str) and repository:
            return repository

    context = memory.get("context")
    if isinstance(context, str) and "#" in context:
        return context.split("#", 1)[0]

    return "unknown"


def compute_rate(numerator: int, denominator: int) -> float:
    return (numerator / denominator) if denominator else 0.0


def memory_sort_key(memory: Dict[str, object]) -> str:
    for key in ("created_at", "timestamp", "updated_at"):
        value = memory.get(key)
        if isinstance(value, str):
            return value
    return ""


def metadata_for(memory: Dict[str, object]) -> Dict[str, object]:
    metadata = memory.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def is_restored_backfill_run(memory: Dict[str, object]) -> bool:
    metadata = metadata_for(memory)
    return bool(metadata.get("metadata_restored")) or metadata.get("source") == "github-comment-backfill"


def is_broad_public_doc(doc: object) -> bool:
    if not isinstance(doc, str):
        return False
    path = doc.lower()
    return (
        path == "index.md"
        or path.endswith("/index.md")
        or path == "changelog.md"
        or path.endswith("/changelog.md")
        or path.startswith("sdks/")
    )


def area_for_changed_files(changed_files: object) -> str:
    if not isinstance(changed_files, list) or not changed_files:
        return "unknown"
    path = next((item for item in changed_files if isinstance(item, str) and item), "")
    if not path:
        return "unknown"
    parts = Path(path).parts
    if len(parts) >= 2:
        return "/".join(parts[:2])
    if parts:
        return parts[0]
    return "unknown"


def collapse_latest_by_context(memories: Iterable[Dict[str, object]]) -> list[Dict[str, object]]:
    grouped: Dict[str, Dict[str, object]] = {}
    for item in memories:
        context = item.get("context")
        if not isinstance(context, str) or not context:
            continue
        current = grouped.get(context)
        if current is None or memory_sort_key(item) >= memory_sort_key(current):
            grouped[context] = item
    return list(grouped.values())


def summarize(feedback: Iterable[Dict[str, object]], runs: Iterable[Dict[str, object]]) -> dict[str, object]:
    feedback = collapse_latest_by_context(feedback)
    runs = collapse_latest_by_context(runs)

    correct = sum(1 for item in feedback if "correct" in (item.get("tags") or []))
    wrong_doc = sum(1 for item in feedback if "wrong-doc" in (item.get("tags") or []))
    missed_doc = sum(1 for item in feedback if "missed-doc" in (item.get("tags") or []))
    feedback_total = correct + wrong_doc + missed_doc

    commented = sum(1 for item in runs if "commented" in (item.get("tags") or []))
    suppressed = sum(1 for item in runs if "suppressed" in (item.get("tags") or []))
    run_total = commented + suppressed

    return {
        "feedback_total": feedback_total,
        "analysis_runs": run_total,
        "unique_prs": run_total,
        "top_1_rate": compute_rate(correct, feedback_total),
        "comment_rate": compute_rate(commented, run_total),
        "false_positive_rate": compute_rate(wrong_doc, commented),
        "counts": {
            "correct": correct,
            "wrong_doc": wrong_doc,
            "missed_doc": missed_doc,
            "commented": commented,
            "suppressed": suppressed,
        },
    }


def summarize_confidence_tiers(runs: Iterable[Dict[str, object]]) -> Dict[str, object]:
    runs = collapse_latest_by_context(runs)
    total = len(runs)
    high = sum(1 for item in runs if "high-confidence" in (item.get("tags") or []))
    review = sum(1 for item in runs if "review-recommended" in (item.get("tags") or []))
    silent = sum(1 for item in runs if "silent" in (item.get("tags") or []))
    return {
        "high_confidence_rate": compute_rate(high, total),
        "review_rate": compute_rate(review, total),
        "silent_rate": compute_rate(silent, total),
        "counts": {
            "high_confidence": high,
            "review_recommended": review,
            "silent": silent,
        },
    }


def summarize_side_effects(runs: Iterable[Dict[str, object]]) -> Dict[str, object]:
    runs = collapse_latest_by_context(runs)
    total = len(runs)
    comment_failures = 0
    novyx_failures = 0
    token_auth_runs = 0
    for item in runs:
        tags = set(item.get("tags") or [])
        metadata = metadata_for(item)
        if "github-comment-failed" in tags or metadata.get("github_comment_status") == "failed":
            comment_failures += 1
        if "novyx-record-failed" in tags or metadata.get("novyx_record_status") == "failed":
            novyx_failures += 1
        if metadata.get("auth_mode") == "token":
            token_auth_runs += 1
    return {
        "comment_failure_rate": compute_rate(comment_failures, total),
        "novyx_failure_rate": compute_rate(novyx_failures, total),
        "token_auth_rate": compute_rate(token_auth_runs, total),
        "counts": {
            "comment_failures": comment_failures,
            "novyx_failures": novyx_failures,
            "token_auth_runs": token_auth_runs,
        },
    }


def summarize_alerts(metrics: Dict[str, object]) -> List[Dict[str, object]]:
    alerts: List[Dict[str, object]] = []
    side_effects = metrics.get("side_effects") or {}
    if isinstance(side_effects, dict):
        counts = side_effects.get("counts") or {}
        if int(counts.get("comment_failures", 0) or 0) > 0:
            alerts.append({"severity": "high", "message": "GitHub comment writes failed on recent analysis runs."})
        if int(counts.get("novyx_failures", 0) or 0) > 0:
            alerts.append({"severity": "medium", "message": "Novyx recording failed on recent analysis runs."})
        if int(counts.get("token_auth_runs", 0) or 0) > 0:
            alerts.append({"severity": "medium", "message": "Runtime is using token auth; GitHub App auth is preferred for production."})
    if float(metrics.get("false_positive_rate", 0.0) or 0.0) >= 0.35:
        alerts.append({"severity": "medium", "message": "False-positive rate is still high enough to erode trust."})
    if float(metrics.get("top_1_rate", 0.0) or 0.0) < 0.5 and int(metrics.get("feedback_total", 0) or 0) >= 5:
        alerts.append({"severity": "medium", "message": "Top-1 correctness is still below the trust threshold."})
    return alerts[:5]


def summarize_trust(metrics: Dict[str, object]) -> Dict[str, object]:
    top_1 = float(metrics.get("top_1_rate", 0.0) or 0.0)
    comment_rate = float(metrics.get("comment_rate", 0.0) or 0.0)
    false_positive = float(metrics.get("false_positive_rate", 0.0) or 0.0)
    tiers = metrics.get("confidence_tiers") if isinstance(metrics.get("confidence_tiers"), dict) else {}
    high_confidence = float((tiers or {}).get("high_confidence_rate", 0.0) or 0.0)
    score = max(0.0, min(100.0, (top_1 * 55) + (comment_rate * 15) + ((1 - false_positive) * 20) + (high_confidence * 10)))
    label = "early"
    if score >= 80:
        label = "strong"
    elif score >= 65:
        label = "building"
    return {
        "score": round(score, 1),
        "label": label,
        "summary": f"{label.capitalize()} trust: top-1 {top_1 * 100:.0f}%, false-positive {false_positive * 100:.0f}%, comment rate {comment_rate * 100:.0f}%.",
    }


def metric_delta_label(recent: float, baseline: float) -> str:
    delta = recent - baseline
    if abs(delta) < 0.001:
        return "flat"
    direction = "up" if delta > 0 else "down"
    return f"{direction} {abs(delta) * 100:.0f} pts"


def summarize_trend(feedback: Iterable[Dict[str, object]], runs: Iterable[Dict[str, object]]) -> Dict[str, str]:
    latest_feedback = collapse_latest_by_context(feedback)
    latest_runs = collapse_latest_by_context(runs)
    latest_feedback.sort(key=memory_sort_key, reverse=True)
    latest_runs.sort(key=memory_sort_key, reverse=True)

    recent_feedback = latest_feedback[:10]
    baseline_feedback = latest_feedback[10:20]
    recent_runs = latest_runs[:10]
    baseline_runs = latest_runs[10:20]

    recent = summarize(recent_feedback, recent_runs)
    baseline = summarize(baseline_feedback, baseline_runs) if baseline_runs or baseline_feedback else recent

    return {
        "top_1_rate": metric_delta_label(float(recent["top_1_rate"]), float(baseline["top_1_rate"])),
        "false_positive_rate": metric_delta_label(float(recent["false_positive_rate"]), float(baseline["false_positive_rate"])),
        "miss_rate": metric_delta_label(
            compute_rate(int(recent["counts"]["missed_doc"]), int(recent["analysis_runs"])),
            compute_rate(int(baseline["counts"]["missed_doc"]), int(baseline["analysis_runs"])),
        ),
    }


def summarize_case_studies(feedback: Iterable[Dict[str, object]], runs: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    latest_feedback = collapse_latest_by_context(feedback)
    latest_runs = collapse_latest_by_context(runs)
    run_by_context = {
        item.get("context"): item
        for item in latest_runs
        if isinstance(item.get("context"), str)
    }
    case_studies: List[Dict[str, object]] = []

    for item in latest_feedback:
        tags = set(item.get("tags") or [])
        if "correct" not in tags:
            continue
        context = item.get("context")
        run = run_by_context.get(context)
        if not run:
            continue
        run_tags = set(run.get("tags") or [])
        if "commented" not in run_tags:
            continue
        metadata = metadata_for(run)
        changed_files = metadata.get("changed_files")
        top_doc = metadata.get("top_doc")
        repository = repository_for(run)
        if not isinstance(top_doc, str) or not top_doc:
            continue
        if is_restored_backfill_run(run) and is_broad_public_doc(top_doc):
            continue
        case_studies.append(
            {
                "repository": repository,
                "pull_request_number": metadata.get("pull_request_number"),
                "area": area_for_changed_files(changed_files),
                "changed_file": changed_files[0] if isinstance(changed_files, list) and changed_files else None,
                "top_doc": top_doc,
                "top_confidence": metadata.get("top_confidence"),
                "confidence_tier": metadata.get("confidence_tier"),
                "commenter": metadata_for(item).get("commenter"),
                "created_at": memory_sort_key(item) or memory_sort_key(run),
            }
        )

    case_studies.sort(
        key=lambda item: (
            int(item.get("top_confidence") or 0),
            str(item.get("created_at") or ""),
        ),
        reverse=True,
    )
    return case_studies[:5]


def summarize_hotspots(feedback: Iterable[Dict[str, object]], runs: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    latest_feedback = collapse_latest_by_context(feedback)
    latest_runs = collapse_latest_by_context(runs)
    feedback_by_context = {
        item.get("context"): item
        for item in latest_feedback
        if isinstance(item.get("context"), str)
    }

    hotspots: Dict[str, Dict[str, object]] = {}
    for run in latest_runs:
        if is_restored_backfill_run(run):
            continue
        context = run.get("context")
        metadata = metadata_for(run)
        area = area_for_changed_files(metadata.get("changed_files"))
        bucket = hotspots.setdefault(
            area,
            {
                "area": area,
                "repository": repository_for(run),
                "runs": 0,
                "commented": 0,
                "suppressed": 0,
                "correct": 0,
                "wrong_doc": 0,
                "missed_doc": 0,
                "top_docs": {},
            },
        )
        bucket["runs"] += 1
        if "commented" in (run.get("tags") or []):
            bucket["commented"] += 1
        if "suppressed" in (run.get("tags") or []):
            bucket["suppressed"] += 1
        top_doc = metadata.get("top_doc")
        if isinstance(top_doc, str) and top_doc:
            top_docs = bucket["top_docs"]
            top_docs[top_doc] = top_docs.get(top_doc, 0) + 1

        feedback_item = feedback_by_context.get(context)
        if not feedback_item:
            continue
        tags = set(feedback_item.get("tags") or [])
        if "correct" in tags:
            bucket["correct"] += 1
        if "wrong-doc" in tags:
            bucket["wrong_doc"] += 1
        if "missed-doc" in tags:
            bucket["missed_doc"] += 1

    results: List[Dict[str, object]] = []
    for item in hotspots.values():
        top_docs = item.pop("top_docs")
        common_doc = None
        if isinstance(top_docs, dict) and top_docs:
            common_doc = max(sorted(top_docs), key=lambda key: top_docs[key])
        item["false_positive_rate"] = compute_rate(int(item["wrong_doc"]), int(item["commented"]))
        item["miss_rate"] = compute_rate(int(item["missed_doc"]), int(item["runs"]))
        item["top_doc"] = common_doc
        results.append(item)

    results.sort(
        key=lambda item: (
            int(item["wrong_doc"]) + int(item["missed_doc"]),
            int(item["runs"]),
            str(item["area"]),
        ),
        reverse=True,
    )
    return results[:10]


def render_case_studies_markdown(case_studies: Iterable[Dict[str, object]]) -> str:
    items = list(case_studies)
    lines = [
        "# Change Intelligence Case Studies",
        "",
        "Accepted proof points pulled from real analysis runs and reviewer feedback.",
        "",
    ]
    if not items:
        lines.append("No accepted proof points yet.")
        return "\n".join(lines)

    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item.get('repository')} #{item.get('pull_request_number')}",
                "",
                f"- Changed file: `{item.get('changed_file') or '-'}`",
                f"- Top doc: `{item.get('top_doc') or '-'}`",
                f"- Confidence: `{item.get('top_confidence') or '-'}`",
                f"- Tier: `{item.get('confidence_tier') or '-'}`",
                f"- Area: `{item.get('area') or '-'}`",
                f"- Verified: `{item.get('created_at') or '-'}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def render_founder_digest_markdown(metrics: Dict[str, object]) -> str:
    case_studies = metrics.get("case_studies") or []
    trend = metrics.get("trend") or {}
    tiers = metrics.get("confidence_tiers") or {}
    hotspots = metrics.get("hotspots") or []
    proof_window = metrics.get("proof_window") or {}

    top_case = case_studies[0] if isinstance(case_studies, list) and case_studies else None
    top_hotspot = hotspots[0] if isinstance(hotspots, list) and hotspots else None
    counts = tiers.get("counts") if isinstance(tiers, dict) else {}
    lines = [
        "# Change Intelligence Founder Digest",
        "",
        "Short weekly narrative generated from real runs, reviewer feedback, and Novyx-backed quality signals.",
        "",
        "## This Week",
        "",
        f"- Analysis runs: `{metrics.get('analysis_runs', 0)}`",
        f"- Reviewer feedback events: `{metrics.get('feedback_total', 0)}`",
        f"- Top-1 correctness: `{float(metrics.get('top_1_rate', 0.0)) * 100:.0f}%`",
        f"- False-positive rate: `{float(metrics.get('false_positive_rate', 0.0)) * 100:.0f}%`",
        "",
        "## Strongest Proof",
        "",
    ]

    if isinstance(top_case, dict):
        lines.extend(
            [
                f"Best accepted example this week came from `{top_case.get('repository')}` PR `#{top_case.get('pull_request_number')}`.",
                f"A change in `{top_case.get('changed_file') or '-'}` correctly pointed to `{top_case.get('top_doc') or '-'}` with confidence `{top_case.get('top_confidence') or '-'}` in tier `{top_case.get('confidence_tier') or '-'}`.",
                "",
            ]
        )
    else:
        remaining = int(proof_window.get("remaining_to_minimum") or 0)
        lines.extend(
            [
                "No accepted proof candidate yet.",
                f"Need `{remaining}` more analysis runs to hit the minimum proof window.",
                "",
            ]
        )

    lines.extend(
        [
            "## Trust Signals",
            "",
            f"- Top-1 trend: `{trend.get('top_1_rate', 'flat')}`",
            f"- False-positive trend: `{trend.get('false_positive_rate', 'flat')}`",
            f"- Miss trend: `{trend.get('miss_rate', 'flat')}`",
            f"- Confidence mix: `{counts.get('high_confidence', 0) if isinstance(counts, dict) else 0}` high-confidence, `{counts.get('review_recommended', 0) if isinstance(counts, dict) else 0}` review-recommended, `{counts.get('silent', 0) if isinstance(counts, dict) else 0}` silent",
            "",
            "## Where It Is Still Noisy",
            "",
        ]
    )

    if isinstance(top_hotspot, dict) and int(top_hotspot.get("wrong_doc", 0)) + int(top_hotspot.get("missed_doc", 0)) > 0:
        lines.extend(
            [
                f"Noisiest area right now is `{top_hotspot.get('area')}` in `{top_hotspot.get('repository')}`.",
                f"It has `{top_hotspot.get('runs', 0)}` runs, false-positive rate `{float(top_hotspot.get('false_positive_rate', 0.0)) * 100:.0f}%`, miss rate `{float(top_hotspot.get('miss_rate', 0.0)) * 100:.0f}%`, and most often points at `{top_hotspot.get('top_doc') or '-'}`.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No noisy hotspot is standing out yet.",
                "",
            ]
        )

    lines.extend(
        [
            "## Read On It",
            "",
            "Change Intelligence is getting stronger when accepted repo-specific patterns overpower shallow lexical overlap. The product still needs more accepted runs and fewer noisy hotspots before broad claims about reliability.",
        ]
    )
    return "\n".join(lines).rstrip()


def compute_metrics(store: NovyxStore, limit: int = 500) -> dict[str, object]:
    feedback = store.list_memories(["ci-feedback"], limit=limit)
    runs = store.list_memories(["analysis-run"], limit=limit)

    metrics = summarize(feedback, runs)
    metrics["confidence_tiers"] = summarize_confidence_tiers(runs)
    metrics["side_effects"] = summarize_side_effects(runs)
    metrics["trend"] = summarize_trend(feedback, runs)
    metrics["case_studies"] = summarize_case_studies(feedback, runs)
    metrics["trust"] = summarize_trust(metrics)
    metrics["novyx"] = {
        "eval": {},
        "audit": {},
    }

    if hasattr(store, "evaluation_history"):
        try:
            history = store.evaluation_history(limit=10)
        except Exception as error:
            history = {}
            metrics["novyx"]["eval"]["history_error"] = str(error)
        if isinstance(history, dict):
            entries = history.get("history") or history.get("items") or history.get("results") or []
            metrics["novyx"]["eval"]["history_count"] = len(entries) if isinstance(entries, list) else 0
            if isinstance(entries, list) and entries:
                latest = entries[0] if isinstance(entries[0], dict) else {}
                if isinstance(latest, dict):
                    metrics["novyx"]["eval"]["latest"] = latest
    else:
        metrics["novyx"]["eval"]["history_unavailable"] = True

    if hasattr(store, "evaluation_drift"):
        try:
            drift = store.evaluation_drift(days=7)
        except Exception as error:
            drift = {}
            metrics["novyx"]["eval"]["drift_error"] = str(error)
        if isinstance(drift, dict):
            metrics["novyx"]["eval"]["drift"] = drift
    else:
        metrics["novyx"]["eval"]["drift_unavailable"] = True

    if hasattr(store, "feedback_audit"):
        try:
            audit_entries = store.feedback_audit(limit=min(limit, 100))
        except Exception as error:
            audit_entries = []
            metrics["novyx"]["audit"]["error"] = str(error)
        if isinstance(audit_entries, list):
            metrics["novyx"]["audit"] = {
                "entry_count": len(audit_entries),
                "create_operations": sum(
                    1 for item in audit_entries
                    if isinstance(item, dict) and str(item.get("operation") or "").upper() == "CREATE"
                ),
                "latest_entry": audit_entries[0] if audit_entries else None,
                **({"error": metrics["novyx"]["audit"]["error"]} if "error" in metrics["novyx"]["audit"] else {}),
            }
    else:
        metrics["novyx"]["audit"]["unavailable"] = True

    repositories = sorted({repository_for(item) for item in [*feedback, *runs]})
    metrics["repositories"] = {}
    for repository in repositories:
        repo_feedback = [item for item in feedback if repository_for(item) == repository]
        repo_runs = [item for item in runs if repository_for(item) == repository]
        metrics["repositories"][repository] = summarize(repo_feedback, repo_runs)
    metrics["hotspots"] = summarize_hotspots(feedback, runs)

    analysis_runs = int(metrics["analysis_runs"])
    feedback_total = int(metrics["feedback_total"])
    minimum_feedback = 10
    metrics["proof_window"] = {
        "minimum_prs": 20,
        "maximum_prs": 30,
        "minimum_feedback": minimum_feedback,
        "analysis_runs": analysis_runs,
        "unique_prs": analysis_runs,
        "feedback_total": feedback_total,
        "remaining_to_minimum": max(0, 20 - analysis_runs),
        "remaining_feedback_to_minimum": max(0, minimum_feedback - feedback_total),
        "ready_for_case_study": analysis_runs >= 20,
        "ready_for_public_metrics": analysis_runs >= 20 and feedback_total >= minimum_feedback,
        "window_complete": 20 <= analysis_runs <= 30,
    }
    metrics["alerts"] = summarize_alerts(metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute daily change-intelligence metrics from Novyx.")
    parser.add_argument("--output-path")
    parser.add_argument("--case-studies-path", help="Optional path to write markdown case studies from accepted runs")
    parser.add_argument("--founder-digest-path", help="Optional path to write a short founder-style weekly digest")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    store = NovyxStore(
        NovyxConfig(
            api_key=os.environ["NOVYX_API_KEY"],
            api_url=os.environ.get("NOVYX_API_URL"),
            agent_id=os.environ.get("NOVYX_AGENT_ID", "change-intelligence"),
        )
    )
    metrics = compute_metrics(store, limit=args.limit)
    rendered = json.dumps(metrics, indent=2)
    if args.output_path:
        Path(args.output_path).write_text(rendered, encoding="utf8")
    if args.case_studies_path:
        Path(args.case_studies_path).write_text(
            render_case_studies_markdown(metrics.get("case_studies") or []),
            encoding="utf8",
        )
    if args.founder_digest_path:
        Path(args.founder_digest_path).write_text(
            render_founder_digest_markdown(metrics),
            encoding="utf8",
        )
    print(rendered)


if __name__ == "__main__":
    main()

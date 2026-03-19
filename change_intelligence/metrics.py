from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Iterable

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


def compute_metrics(store: NovyxStore, limit: int = 500) -> dict[str, object]:
    feedback = store.list_memories(["ci-feedback"], limit=limit)
    runs = store.list_memories(["analysis-run"], limit=limit)

    metrics = summarize(feedback, runs)

    repositories = sorted({repository_for(item) for item in [*feedback, *runs]})
    metrics["repositories"] = {}
    for repository in repositories:
        repo_feedback = [item for item in feedback if repository_for(item) == repository]
        repo_runs = [item for item in runs if repository_for(item) == repository]
        metrics["repositories"][repository] = summarize(repo_feedback, repo_runs)

    analysis_runs = int(metrics["analysis_runs"])
    metrics["proof_window"] = {
        "minimum_prs": 20,
        "maximum_prs": 30,
        "analysis_runs": analysis_runs,
        "unique_prs": analysis_runs,
        "remaining_to_minimum": max(0, 20 - analysis_runs),
        "ready_for_case_study": analysis_runs >= 20,
        "window_complete": 20 <= analysis_runs <= 30,
    }
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute daily change-intelligence metrics from Novyx.")
    parser.add_argument("--output-path")
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
    print(rendered)


if __name__ == "__main__":
    main()

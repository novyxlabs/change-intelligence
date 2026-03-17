from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .novyx_store import NovyxConfig, NovyxStore


def compute_metrics(store: NovyxStore, limit: int = 500) -> dict[str, object]:
    feedback = store.list_memories(["ci-feedback"], limit=limit)
    runs = store.list_memories(["analysis-run"], limit=limit)

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
        "top_1_rate": (correct / feedback_total) if feedback_total else 0.0,
        "comment_rate": (commented / run_total) if run_total else 0.0,
        "false_positive_rate": (wrong_doc / commented) if commented else 0.0,
        "counts": {
            "correct": correct,
            "wrong_doc": wrong_doc,
            "missed_doc": missed_doc,
            "commented": commented,
            "suppressed": suppressed,
        },
    }


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

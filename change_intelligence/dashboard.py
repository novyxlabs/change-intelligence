from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Dict, List, Optional

from .metrics import compute_metrics


def _memory_sort_key(memory: Dict[str, object]) -> str:
    for key in ("created_at", "timestamp", "updated_at"):
        value = memory.get(key)
        if isinstance(value, str):
            return value
    return ""


def _metadata(memory: Dict[str, object]) -> Dict[str, object]:
    metadata = memory.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _normalize_run(memory: Dict[str, object]) -> Dict[str, object]:
    metadata = _metadata(memory)
    return {
        "repository": metadata.get("repository"),
        "pull_request_number": metadata.get("pull_request_number"),
        "head_sha": metadata.get("head_sha"),
        "top_doc": metadata.get("top_doc"),
        "top_confidence": metadata.get("top_confidence"),
        "comment_suppressed": bool(metadata.get("comment_suppressed")),
        "recommendation_count": metadata.get("recommendation_count"),
        "created_at": _memory_sort_key(memory) or None,
        "context": memory.get("context"),
    }


def _normalize_feedback(memory: Dict[str, object]) -> Dict[str, object]:
    metadata = _metadata(memory)
    return {
        "repository": metadata.get("repository"),
        "pull_request_number": metadata.get("pull_request_number"),
        "feedback": metadata.get("feedback"),
        "commenter": metadata.get("commenter"),
        "comment_url": metadata.get("comment_url"),
        "analysis_memory_id": metadata.get("analysis_memory_id"),
        "created_at": _memory_sort_key(memory) or None,
        "context": memory.get("context"),
    }


def _safe_list_memories(store, tags: List[str], limit: int, label: str, errors: List[str]) -> List[Dict[str, object]]:
    try:
        memories = store.list_memories(tags, limit=limit)
    except Exception as error:
        errors.append(f"{label}: {error}")
        return []
    return [item for item in memories if isinstance(item, dict)]


def build_dashboard_payload(store, limit: int = 25) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).isoformat()

    if store is None:
        return {
            "generated_at": generated_at,
            "metrics": {},
            "recent_runs": [],
            "recent_feedback": [],
            "errors": ["novyx store unavailable"],
        }

    errors: List[str] = []
    metrics: dict[str, object]
    try:
        metrics = compute_metrics(store, limit=max(limit, 100))
    except Exception as error:
        metrics = {}
        errors.append(f"metrics: {error}")

    runs = _safe_list_memories(store, ["analysis-run"], limit, "recent_runs", errors)
    feedback = _safe_list_memories(store, ["ci-feedback"], limit, "recent_feedback", errors)

    normalized_runs = [_normalize_run(item) for item in sorted(runs, key=_memory_sort_key, reverse=True)]
    normalized_feedback = [_normalize_feedback(item) for item in sorted(feedback, key=_memory_sort_key, reverse=True)]

    return {
        "generated_at": generated_at,
        "metrics": metrics,
        "recent_runs": normalized_runs,
        "recent_feedback": normalized_feedback,
        "errors": errors,
    }


def _format_percent(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.0f}%"
    return "-"


def _format_value(value: object) -> str:
    if value in (None, ""):
        return "-"
    return escape(str(value))


def _render_summary_cards(metrics: Dict[str, object]) -> str:
    proof_window = metrics.get("proof_window") if isinstance(metrics.get("proof_window"), dict) else {}
    cards = [
        ("Top-1 rate", _format_percent(metrics.get("top_1_rate"))),
        ("Comment rate", _format_percent(metrics.get("comment_rate"))),
        ("False-positive rate", _format_percent(metrics.get("false_positive_rate"))),
        ("Proof window", f"{proof_window.get('analysis_runs', 0)}/20"),
    ]
    return "".join(
        f"<section class='card'><h2>{escape(label)}</h2><p>{escape(value)}</p></section>"
        for label, value in cards
    )


def _render_repo_rows(repositories: object) -> str:
    if not isinstance(repositories, dict) or not repositories:
        return "<tr><td colspan='5'>No repository metrics yet.</td></tr>"

    rows = []
    for repository, stats in sorted(repositories.items()):
        repo_stats = stats if isinstance(stats, dict) else {}
        rows.append(
            "<tr>"
            f"<td>{escape(str(repository))}</td>"
            f"<td>{_format_value(repo_stats.get('analysis_runs'))}</td>"
            f"<td>{_format_percent(repo_stats.get('top_1_rate'))}</td>"
            f"<td>{_format_percent(repo_stats.get('comment_rate'))}</td>"
            f"<td>{_format_percent(repo_stats.get('false_positive_rate'))}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_run_rows(runs: List[Dict[str, object]]) -> str:
    if not runs:
        return "<tr><td colspan='6'>No analysis runs yet.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{_format_value(item.get('repository'))}</td>"
        f"<td>{_format_value(item.get('pull_request_number'))}</td>"
        f"<td>{_format_value(item.get('top_doc'))}</td>"
        f"<td>{_format_value(item.get('top_confidence'))}</td>"
        f"<td>{'yes' if item.get('comment_suppressed') else 'no'}</td>"
        f"<td>{_format_value(item.get('created_at'))}</td>"
        "</tr>"
        for item in runs
    )


def _render_feedback_rows(feedback: List[Dict[str, object]]) -> str:
    if not feedback:
        return "<tr><td colspan='5'>No feedback yet.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{_format_value(item.get('repository'))}</td>"
        f"<td>{_format_value(item.get('pull_request_number'))}</td>"
        f"<td>{_format_value(item.get('feedback'))}</td>"
        f"<td>{_format_value(item.get('commenter'))}</td>"
        f"<td>{_format_value(item.get('created_at'))}</td>"
        "</tr>"
        for item in feedback
    )


def render_dashboard_html(payload: Dict[str, object]) -> str:
    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    errors = payload.get("errors")
    errors = errors if isinstance(errors, list) else []
    novyx = metrics.get("novyx")
    novyx = novyx if isinstance(novyx, dict) else {}
    proof_window = metrics.get("proof_window")
    proof_window = proof_window if isinstance(proof_window, dict) else {}

    error_html = ""
    if errors:
        items = "".join(f"<li>{escape(str(item))}</li>" for item in errors)
        error_html = f"<section class='errors'><h2>Partial data</h2><ul>{items}</ul></section>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Change Intelligence Dashboard</title>
  <style>
    :root {{ color-scheme: light; --bg: #f5f1e8; --panel: #fffdf8; --ink: #1c1a17; --muted: #6a6257; --line: #d9cfbf; --accent: #8b3d2e; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: linear-gradient(180deg, #efe6d5 0%, var(--bg) 35%, #f7f4ed 100%); color: var(--ink); }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    p, li, td, th {{ line-height: 1.4; }}
    .lede {{ color: var(--muted); margin-bottom: 24px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .card, .panel, .errors {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: 0 8px 24px rgba(28, 26, 23, 0.05); }}
    .card p {{ font-size: 28px; margin: 0; }}
    .errors {{ border-color: #c06f5e; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 10px 8px; border-top: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font-weight: normal; }}
    .meta {{ color: var(--muted); font-size: 14px; }}
    @media (max-width: 720px) {{ main {{ padding: 20px 14px 32px; }} .card p {{ font-size: 22px; }} th, td {{ font-size: 14px; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Change Intelligence Dashboard</h1>
    <p class="lede">Generated at {_format_value(payload.get("generated_at"))}. Internal ops view over ranking quality, proof-window progress, and Novyx health.</p>
    {error_html}
    <div class="cards">{_render_summary_cards(metrics)}</div>
    <div class="grid">
      <section class="panel">
        <h2>Proof Window</h2>
        <p>Runs: {_format_value(proof_window.get("analysis_runs"))}. Remaining to 20: {_format_value(proof_window.get("remaining_to_minimum"))}. Ready: {_format_value(proof_window.get("ready_for_case_study"))}.</p>
      </section>
      <section class="panel">
        <h2>Novyx Health</h2>
        <p>Eval history: {_format_value((novyx.get("eval") or {}).get("history_count"))}. Audit entries: {_format_value((novyx.get("audit") or {}).get("entry_count"))}.</p>
        <p class="meta">Latest eval: {_format_value((novyx.get("eval") or {}).get("latest"))}</p>
        <p class="meta">Drift: {_format_value((novyx.get("eval") or {}).get("drift"))}</p>
      </section>
      <section class="panel">
        <h2>Per-Repo Metrics</h2>
        <table>
          <thead><tr><th>Repository</th><th>Runs</th><th>Top-1</th><th>Comment</th><th>False-positive</th></tr></thead>
          <tbody>{_render_repo_rows(metrics.get("repositories"))}</tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Recent Analysis Runs</h2>
        <table>
          <thead><tr><th>Repository</th><th>PR</th><th>Top doc</th><th>Confidence</th><th>Suppressed</th><th>Created</th></tr></thead>
          <tbody>{_render_run_rows(payload.get("recent_runs") if isinstance(payload.get("recent_runs"), list) else [])}</tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Recent Feedback</h2>
        <table>
          <thead><tr><th>Repository</th><th>PR</th><th>Feedback</th><th>Commenter</th><th>Created</th></tr></thead>
          <tbody>{_render_feedback_rows(payload.get("recent_feedback") if isinstance(payload.get("recent_feedback"), list) else [])}</tbody>
        </table>
      </section>
    </div>
  </main>
</body>
</html>
"""

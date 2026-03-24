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
        "docs_repo": metadata.get("docs_repo"),
        "docs_path": metadata.get("docs_path"),
        "pull_request_number": metadata.get("pull_request_number"),
        "head_sha": metadata.get("head_sha"),
        "top_doc": metadata.get("top_doc"),
        "top_confidence": metadata.get("top_confidence"),
        "confidence_tier": metadata.get("confidence_tier"),
        "comment_suppressed": bool(metadata.get("comment_suppressed")),
        "recommendation_count": metadata.get("recommendation_count"),
        "changed_files": metadata.get("changed_files"),
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


def build_dashboard_payload(store, limit: int = 25, service_config=None) -> dict[str, object]:
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

    setup = build_setup_status(service_config, metrics, normalized_runs)

    return {
        "generated_at": generated_at,
        "metrics": metrics,
        "recent_runs": normalized_runs,
        "recent_feedback": normalized_feedback,
        "errors": errors,
        "auth_mode": service_config.github_client.auth_mode() if service_config and service_config.github_client else "none",
        "setup": setup,
    }


def build_public_proof_payload(store, limit: int = 25) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).isoformat()
    if store is None:
        return {
            "generated_at": generated_at,
            "headline": "No public proof available yet.",
            "metrics": {},
            "case_studies": [],
            "hotspots": [],
            "proof_window": {},
            "errors": ["novyx store unavailable"],
        }

    errors: List[str] = []
    try:
        metrics = compute_metrics(store, limit=max(limit, 100))
    except Exception as error:
        metrics = {}
        errors.append(f"metrics: {error}")

    proof_window = metrics.get("proof_window") if isinstance(metrics, dict) else {}
    proof_window = proof_window if isinstance(proof_window, dict) else {}
    case_studies = metrics.get("case_studies") if isinstance(metrics, dict) else []
    case_studies = case_studies if isinstance(case_studies, list) else []
    headline = (
        f"{int(metrics.get('analysis_runs', 0) or 0)} analysis runs, "
        f"{float(metrics.get('top_1_rate', 0.0) or 0.0) * 100:.0f}% top-1 correctness, "
        f"{float(metrics.get('comment_rate', 0.0) or 0.0) * 100:.0f}% comment rate."
        if metrics
        else "No public proof available yet."
    )
    return {
        "generated_at": generated_at,
        "headline": headline,
        "metrics": metrics,
        "case_studies": case_studies[:3],
        "hotspots": (metrics.get("hotspots") or [])[:3] if isinstance(metrics, dict) else [],
        "proof_window": proof_window,
        "errors": errors,
    }


def build_setup_status(service_config, metrics: Dict[str, object], recent_runs: List[Dict[str, object]]) -> Dict[str, object]:
    auth_mode = service_config.github_client.auth_mode() if service_config and service_config.github_client else "none"
    configured_docs_repo = getattr(service_config, "docs_repo", None) if service_config else None
    configured_docs_path = getattr(service_config, "docs_path", "docs") if service_config else "docs"
    latest_run = recent_runs[0] if recent_runs else {}
    latest_docs_repo = latest_run.get("docs_repo") if isinstance(latest_run, dict) else None
    latest_doc_path = latest_run.get("docs_path") if isinstance(latest_run, dict) else None
    latest_created = latest_run.get("created_at") if isinstance(latest_run, dict) else None
    latest_pr = latest_run.get("pull_request_number") if isinstance(latest_run, dict) else None
    latest_repo = latest_run.get("repository") if isinstance(latest_run, dict) else None
    latest_top_doc = latest_run.get("top_doc") if isinstance(latest_run, dict) else None
    docs_repo_used = configured_docs_repo or latest_docs_repo or latest_repo
    docs_path_used = latest_doc_path or configured_docs_path
    proof_window = metrics.get("proof_window") if isinstance(metrics, dict) else {}
    proof_window = proof_window if isinstance(proof_window, dict) else {}

    checks = [
        {
            "label": "GitHub auth",
            "status": "ready" if auth_mode in {"app", "token"} else "missing",
            "detail": f"Runtime auth mode: {auth_mode}.",
        },
        {
            "label": "Novyx memory",
            "status": "ready" if getattr(service_config, "novyx_store", None) is not None else "missing",
            "detail": "Novyx-backed learning and proof export are enabled." if getattr(service_config, "novyx_store", None) is not None else "NOVYX_API_KEY is not configured.",
        },
        {
            "label": "Docs source",
            "status": "ready",
            "detail": f"Using {docs_repo_used or '-'} at `{docs_path_used}`.",
        },
        {
            "label": "Live traffic",
            "status": "ready" if latest_created else "waiting",
            "detail": f"Last analyzed PR: {latest_repo or '-'}#{latest_pr or '-'} at {latest_created or '-'}."
            if latest_created
            else "No analysis run recorded yet.",
        },
        {
            "label": "Proof window",
            "status": "ready" if bool(proof_window.get('ready_for_case_study')) else "building",
            "detail": f"{proof_window.get('analysis_runs', 0)} runs collected; {proof_window.get('remaining_to_minimum', 0)} to minimum public proof."
            if proof_window
            else "No proof window yet.",
        },
    ]
    return {
        "docs_repo": docs_repo_used,
        "docs_path": docs_path_used,
        "latest_run": {
            "repository": latest_repo,
            "pull_request_number": latest_pr,
            "created_at": latest_created,
            "top_doc": latest_top_doc,
        },
        "checks": checks,
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
    trust = metrics.get("trust") if isinstance(metrics.get("trust"), dict) else {}
    cards = [
        ("Trust score", _format_value(trust.get("score"))),
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
        return "<tr><td colspan='7'>No analysis runs yet.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{_format_value(item.get('repository'))}</td>"
        f"<td>{_format_value(item.get('pull_request_number'))}</td>"
        f"<td>{_format_value(item.get('top_doc'))}</td>"
        f"<td>{_format_value(item.get('top_confidence'))}</td>"
        f"<td>{_format_value(item.get('confidence_tier'))}</td>"
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


def _render_hotspot_rows(hotspots: object) -> str:
    if not isinstance(hotspots, list) or not hotspots:
        return "<tr><td colspan='8'>No hotspot data yet.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{_format_value(item.get('repository'))}</td>"
        f"<td>{_format_value(item.get('area'))}</td>"
        f"<td>{_format_value(item.get('runs'))}</td>"
        f"<td>{_format_value(item.get('top_doc'))}</td>"
        f"<td>{_format_percent(item.get('false_positive_rate'))}</td>"
        f"<td>{_format_percent(item.get('miss_rate'))}</td>"
        f"<td>{_format_value(item.get('wrong_doc'))}</td>"
        f"<td>{_format_value(item.get('missed_doc'))}</td>"
        "</tr>"
        for item in hotspots[:10]
    )


def _render_case_study_rows(case_studies: object) -> str:
    if not isinstance(case_studies, list) or not case_studies:
        return "<tr><td colspan='7'>No accepted proof points yet.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{_format_value(item.get('repository'))}</td>"
        f"<td>{_format_value(item.get('pull_request_number'))}</td>"
        f"<td>{_format_value(item.get('changed_file'))}</td>"
        f"<td>{_format_value(item.get('top_doc'))}</td>"
        f"<td>{_format_value(item.get('top_confidence'))}</td>"
        f"<td>{_format_value(item.get('confidence_tier'))}</td>"
        f"<td>{_format_value(item.get('created_at'))}</td>"
        "</tr>"
        for item in case_studies[:5]
    )


def _render_alerts(alerts: object) -> str:
    if not isinstance(alerts, list) or not alerts:
        return "<p class='meta'>No current production alerts.</p>"
    items = []
    for item in alerts[:5]:
        if not isinstance(item, dict):
            continue
        items.append(
            f"<li><strong>{escape(str(item.get('severity', 'info')).upper())}</strong>: {escape(str(item.get('message', '')))}</li>"
        )
    return "<ul>" + "".join(items) + "</ul>" if items else "<p class='meta'>No current production alerts.</p>"


def _render_setup_checks(setup: object) -> str:
    if not isinstance(setup, dict):
        return "<li><strong>WAITING</strong>: No setup data yet.</li>"
    checks = setup.get("checks")
    if not isinstance(checks, list) or not checks:
        return "<li><strong>WAITING</strong>: No setup data yet.</li>"
    items = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        items.append(
            f"<li><strong>{escape(str(item.get('status', 'waiting')).upper())}</strong> {escape(str(item.get('label', '')))}: {escape(str(item.get('detail', '')))}</li>"
        )
    return "".join(items) or "<li><strong>WAITING</strong>: No setup data yet.</li>"


def _render_public_case_studies(case_studies: object) -> str:
    if not isinstance(case_studies, list) or not case_studies:
        return "<p class='meta'>No accepted proof points yet.</p>"
    blocks = []
    for item in case_studies[:3]:
        if not isinstance(item, dict):
            continue
        blocks.append(
            "<article class='card'>"
            f"<h2>{escape(str(item.get('repository', '-')))} #{escape(str(item.get('pull_request_number', '-')))}</h2>"
            f"<p><strong>Changed file:</strong> {escape(str(item.get('changed_file') or '-'))}</p>"
            f"<p><strong>Top doc:</strong> {escape(str(item.get('top_doc') or '-'))}</p>"
            f"<p class='meta'>Confidence {_format_value(item.get('top_confidence'))} • Tier {_format_value(item.get('confidence_tier'))}</p>"
            "</article>"
        )
    return "".join(blocks) or "<p class='meta'>No accepted proof points yet.</p>"


def render_dashboard_html(payload: Dict[str, object]) -> str:
    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    errors = payload.get("errors")
    errors = errors if isinstance(errors, list) else []
    novyx = metrics.get("novyx")
    novyx = novyx if isinstance(novyx, dict) else {}
    trust = metrics.get("trust")
    trust = trust if isinstance(trust, dict) else {}
    proof_window = metrics.get("proof_window")
    proof_window = proof_window if isinstance(proof_window, dict) else {}
    auth_mode = payload.get("auth_mode")
    setup = payload.get("setup")

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
        <h2>Trust Summary</h2>
        <p>{_format_value(trust.get("summary"))}</p>
        <p class="meta">Trust label: {_format_value(trust.get("label"))}. Score: {_format_value(trust.get("score"))}.</p>
      </section>
      <section class="panel">
        <h2>Setup Status</h2>
        <ul>{_render_setup_checks(setup)}</ul>
        <p class="meta">Current docs source: {_format_value((setup or {}).get("docs_repo"))} at {_format_value((setup or {}).get("docs_path"))}.</p>
      </section>
      <section class="panel">
        <h2>Proof Window</h2>
        <p>Runs: {_format_value(proof_window.get("analysis_runs"))}. Remaining to 20: {_format_value(proof_window.get("remaining_to_minimum"))}. Ready: {_format_value(proof_window.get("ready_for_case_study"))}.</p>
        <p class="meta">Recent confidence mix: high {_format_percent((metrics.get("confidence_tiers") or {}).get("high_confidence_rate"))}, review {_format_percent((metrics.get("confidence_tiers") or {}).get("review_rate"))}, silent {_format_percent((metrics.get("confidence_tiers") or {}).get("silent_rate"))}.</p>
        <p class="meta">Trend: top-1 {_format_value((metrics.get("trend") or {}).get("top_1_rate"))}, false-positive {_format_value((metrics.get("trend") or {}).get("false_positive_rate"))}, miss {_format_value((metrics.get("trend") or {}).get("miss_rate"))}.</p>
      </section>
      <section class="panel">
        <h2>Novyx Health</h2>
        <p>Eval history: {_format_value((novyx.get("eval") or {}).get("history_count"))}. Audit entries: {_format_value((novyx.get("audit") or {}).get("entry_count"))}.</p>
        <p class="meta">Latest eval: {_format_value((novyx.get("eval") or {}).get("latest"))}</p>
        <p class="meta">Drift: {_format_value((novyx.get("eval") or {}).get("drift"))}</p>
      </section>
      <section class="panel">
        <h2>Production Alerts</h2>
        {_render_alerts(metrics.get("alerts"))}
        <p class="meta">GitHub auth mode: {_format_value(auth_mode)}. GitHub App auth is preferred for production comment writes.</p>
        <p class="meta">Recent side-effect failures: GitHub comment {_format_percent((metrics.get("side_effects") or {}).get("comment_failure_rate"))}, Novyx record {_format_percent((metrics.get("side_effects") or {}).get("novyx_failure_rate"))}.</p>
      </section>
      <section class="panel">
        <h2>Per-Repo Metrics</h2>
        <table>
          <thead><tr><th>Repository</th><th>Runs</th><th>Top-1</th><th>Comment</th><th>False-positive</th></tr></thead>
          <tbody>{_render_repo_rows(metrics.get("repositories"))}</tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Drift Hotspots</h2>
        <table>
          <thead><tr><th>Repository</th><th>Area</th><th>Runs</th><th>Common doc</th><th>False-positive</th><th>Miss rate</th><th>Wrong doc</th><th>Missed doc</th></tr></thead>
          <tbody>{_render_hotspot_rows(metrics.get("hotspots"))}</tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Proof Candidates</h2>
        <table>
          <thead><tr><th>Repository</th><th>PR</th><th>Changed file</th><th>Top doc</th><th>Confidence</th><th>Tier</th><th>Verified</th></tr></thead>
          <tbody>{_render_case_study_rows(metrics.get("case_studies"))}</tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Recent Analysis Runs</h2>
        <table>
          <thead><tr><th>Repository</th><th>PR</th><th>Top doc</th><th>Confidence</th><th>Tier</th><th>Suppressed</th><th>Created</th></tr></thead>
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


def render_public_proof_html(payload: Dict[str, object]) -> str:
    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    proof_window = payload.get("proof_window")
    proof_window = proof_window if isinstance(proof_window, dict) else {}
    trust = metrics.get("trust")
    trust = trust if isinstance(trust, dict) else {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Change Intelligence Proof</title>
  <style>
    :root {{ color-scheme: light; --bg: #f7f4ed; --panel: #fffdf8; --ink: #1c1a17; --muted: #6a6257; --line: #d9cfbf; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: var(--bg); color: var(--ink); }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 48px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }}
    .card, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; }}
    .meta {{ color: var(--muted); font-size: 14px; }}
  </style>
</head>
<body>
  <main>
    <h1>Change Intelligence Proof</h1>
    <p>{escape(str(payload.get("headline") or ""))}</p>
    <p class="meta">Generated at {_format_value(payload.get("generated_at"))}. Public proof view over real analysis runs and accepted examples.</p>
    <div class="cards">
      <section class="card"><h2>Trust score</h2><p>{_format_value(trust.get("score"))}</p></section>
      <section class="card"><h2>Analysis runs</h2><p>{_format_value(metrics.get("analysis_runs"))}</p></section>
      <section class="card"><h2>Top-1 correctness</h2><p>{_format_percent(metrics.get("top_1_rate"))}</p></section>
      <section class="card"><h2>Comment rate</h2><p>{_format_percent(metrics.get("comment_rate"))}</p></section>
      <section class="card"><h2>Proof progress</h2><p>{_format_value(proof_window.get("analysis_runs"))}/20</p></section>
    </div>
    <section class="panel">
      <h2>Trust Summary</h2>
      <p>{_format_value(trust.get("summary"))}</p>
    </section>
    <section class="panel">
      <h2>Accepted Proof Points</h2>
      <div class="cards">{_render_public_case_studies(payload.get("case_studies"))}</div>
    </section>
  </main>
</body>
</html>
"""

# Change Intelligence Dashboard Plan

## Status

DONE

No prior design doc exists for this branch. This plan is the source of truth for a first internal dashboard.

## Step 0: Scope Challenge

### Existing code that already solves parts of the problem

- [change_intelligence/metrics.py](/Users/blakeheron/Desktop/demo/change_intelligence/metrics.py) already computes the core KPI model:
  - `top_1_rate`
  - `comment_rate`
  - `false_positive_rate`
  - per-repo breakdown
  - proof-window progress
  - Novyx eval/audit summary
- [change_intelligence/novyx_store.py](/Users/blakeheron/Desktop/demo/change_intelligence/novyx_store.py) already exposes the memory-backed sources needed for richer dashboard context:
  - feedback memories
  - analysis-run memories
  - audit snapshots
  - eval history / drift
- [change_intelligence/server.py](/Users/blakeheron/Desktop/demo/change_intelligence/server.py) already hosts a Python HTTP server. We do not need a new web framework to ship an internal dashboard.

### Minimum change that achieves the goal

Build an internal read-only dashboard served from the existing Python server.

The minimum useful version is:
- `GET /dashboard` returns server-rendered HTML
- `GET /api/dashboard` returns JSON
- both are backed by one dashboard service function that composes:
  - `compute_metrics(store)`
  - recent analysis runs
  - recent feedback events

Do not build:
- a SPA
- auth system changes
- charts library integration
- persistent dashboard-specific storage

### Complexity check

This should stay under 8 touched files and 2 new modules.

Recommended file set:
- `change_intelligence/dashboard.py` new
- `change_intelligence/server.py`
- `change_intelligence/novyx_store.py`
- `change_intelligence/metrics.py`
- `tests/test_dashboard.py` new
- maybe `README.md` if usage needs one short note

That is engineered enough and still a minimal diff.

### Completeness check

This should be the complete MVP, not a shortcut:
- HTML dashboard plus JSON endpoint
- recent-event context, not just aggregate numbers
- explicit empty/error states for missing Novyx data
- tests for both JSON and HTML paths

## Recommendation

Build an internal ops dashboard in the existing Python service, not a new frontend app.

Why:
- boring technology
- minimal diff
- fastest route to dogfooding
- uses the metrics and Novyx signals already in the codebase

## Architecture

### Recommended routes

- `GET /health`
- `GET /api/dashboard`
- `GET /dashboard`
- existing `POST /webhooks/github`

### Data flow

```text
Browser
  |
  +--> GET /dashboard
  |      |
  |      +--> dashboard.build_dashboard_payload()
  |                |
  |                +--> compute_metrics(store)
  |                +--> store.list_memories(["analysis-run"])
  |                +--> store.list_memories(["ci-feedback"])
  |                +--> normalize recent items
  |      |
  |      +--> render HTML string
  |
  +--> GET /api/dashboard
         |
         +--> same payload builder
         +--> JSON response
```

### Module shape

#### `change_intelligence/dashboard.py`

Responsibilities:
- build one normalized dashboard payload
- render HTML for that payload
- contain no HTTP wiring

Functions:
- `build_dashboard_payload(store, limit=50) -> dict`
- `render_dashboard_html(payload) -> str`
- small helpers for recent-run and recent-feedback normalization

#### `change_intelligence/server.py`

Responsibilities:
- route `GET /dashboard`
- route `GET /api/dashboard`
- preserve existing webhook behavior unchanged

### Payload shape

```json
{
  "generated_at": "2026-03-22T12:00:00Z",
  "metrics": {
    "feedback_total": 12,
    "analysis_runs": 24,
    "top_1_rate": 0.67,
    "comment_rate": 0.79,
    "false_positive_rate": 0.18,
    "proof_window": {
      "analysis_runs": 24,
      "remaining_to_minimum": 0,
      "ready_for_case_study": true
    },
    "repositories": {},
    "novyx": {}
  },
  "recent_runs": [
    {
      "repository": "novyxlabs/novyx-core",
      "pull_request_number": 42,
      "head_sha": "abc123",
      "top_doc": "api-reference/search.md",
      "top_confidence": 84,
      "comment_suppressed": false,
      "created_at": "2026-03-22T11:30:00Z"
    }
  ],
  "recent_feedback": [
    {
      "repository": "novyxlabs/novyx-core",
      "pull_request_number": 42,
      "feedback": "correct",
      "commenter": "blake",
      "created_at": "2026-03-22T11:40:00Z"
    }
  ],
  "errors": []
}
```

### HTML structure

Keep it server-rendered and plain:

```text
Dashboard
  Summary cards
    top-1 rate
    comment rate
    false-positive rate
    proof-window progress
  Proof-window section
    runs completed
    remaining to 20
    publish/freeze status
  Per-repo table
  Novyx health section
    eval latest
    drift
    audit latest
    any unavailable/error states
  Recent analysis runs table
  Recent feedback table
```

## Production Failure Scenarios

### 1. Novyx unavailable

Failure:
- dashboard request times out or returns partial data

Plan:
- dashboard payload builder should catch store failures and populate `errors`
- HTML must show partial data plus a clear unavailable banner
- JSON should still return `200` with explicit error fields unless the whole payload cannot be assembled

### 2. Large memory history

Failure:
- dashboard gets slow because it tries to fetch too many memories every request

Plan:
- keep a tight recent-item limit like `25` or `50`
- do not hydrate full traces for the dashboard
- use existing aggregate metrics plus shallow recent lists only

### 3. Missing metadata on older memories

Failure:
- older runs do not contain newer fields like `head_sha` or `top_doc`

Plan:
- normalization layer fills `null`
- HTML renders blanks instead of crashing

## Code Quality Review

### Recommendation

Keep the dashboard builder as a pure composition layer.

Do not put HTML generation inside `metrics.py`.
Do not put data normalization inside `server.py`.
Do not add a template engine yet.

That keeps:
- metrics reusable
- HTTP wiring simple
- dashboard logic easy to test

## Test Review

### Test diagram

```text
GET /api/dashboard
  |
  +--> metrics available
  |      +--> returns KPI payload
  |
  +--> novyx partial failure
  |      +--> returns payload with explicit errors
  |
  +--> empty memories
         +--> returns zeros and empty recent lists

GET /dashboard
  |
  +--> normal payload
  |      +--> renders summary cards and recent sections
  |
  +--> partial novyx failure
         +--> renders error/unavailable banner
```

### Required tests

#### `tests/test_dashboard.py`

- `test_build_dashboard_payload_includes_metrics_recent_runs_and_feedback`
- `test_build_dashboard_payload_surfaces_store_errors`
- `test_render_dashboard_html_includes_summary_and_recent_sections`
- `test_render_dashboard_html_handles_empty_state`
- `test_server_returns_dashboard_json`
- `test_server_returns_dashboard_html`

### Test plan artifact

For `/qa` later, the critical flows are:
- `GET /api/dashboard`
- `GET /dashboard`
- partial Novyx failure mode
- empty-state rendering

## Performance Review

### Recommendation

Do not build background caching in v1.

The payload is small enough if you:
- cap recent runs
- cap recent feedback
- reuse `compute_metrics()`

If latency becomes noticeable later, add a short in-process cache with a 30-60 second TTL. That is a second-step optimization, not day-one architecture.

## Implementation Order

1. Add `change_intelligence/dashboard.py`
2. Add payload builder using existing metrics plus recent memory fetches
3. Add HTML renderer
4. Wire `GET /api/dashboard` and `GET /dashboard` into `server.py`
5. Add dashboard tests
6. Add one short README note if needed

## Final Recommendation

Build the internal dashboard now, in the Python server, with server-rendered HTML plus a JSON endpoint.

This is the right next move because it productizes the signals you already have without spending an innovation token on frontend infrastructure.

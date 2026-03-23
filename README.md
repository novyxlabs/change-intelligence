# Change Intelligence

Product code changes.
Docs go stale.
Usually nobody notices until users do.

`change-intelligence` exists to catch that in the pull request.

Want the concrete evidence first:
- [PROOF.md](/Users/blakeheron/Desktop/demo/PROOF.md)

The Python service under `change_intelligence/` is the only production runtime.
The earlier Node implementation in `src/` remains as a reference CLI and fixture harness for the ranking logic, not as a deployed server.

## Why It Exists

Most teams do not have a docs writing problem.
They have a change detection problem.

Checkout changes.
Auth changes.
Search changes.
Onboarding changes.

Somewhere in the repo, docs, setup guides, support answers, and release notes are now wrong.

This reads the diff, finds the likely blast radius, and shows the evidence.

## The Wedge

This is not a generic docs chatbot.
This is not "AI for content."

This is one narrow product:

- product code changes
- docs drift appears immediately
- the system points at the likely stale docs
- the reviewer sees why

That is enough to be useful by itself.
It is also the right primitive for release notes, support updates, onboarding drift, and memory-backed learning later.

## What A User Sees

On a pull request, Change Intelligence can post a brief like:

- these docs are probably stale
- these files, symbols, routes, or API surfaces caused the match
- here is the evidence
- here is a draft follow-up when confidence is high

The point is not to auto-publish text.
The point is to make docs drift visible while the PR is still open.

Example PR comment:

```md
## Change Intelligence

Repository: `acme/app`
Pull request: #42
Confidence threshold: `60`

### Similar Historical Patterns

- `src/billing/createCheckoutSession.ts` changed -> `docs/billing.md` was accepted after merge (score: 0.9)

### Likely Stale Docs

1. `docs/billing.md`
   - matched changed file path: `src/billing/createCheckoutSession.ts`
   - matched symbol: `createCheckoutSession`
   - matched route/API surface: `/checkout/session`

### Update Focus

- explain coupon behavior in checkout flow
- note new request fields and API behavior
- update setup or support docs if coupon support changes failure modes

---
Reply with `/ci correct`, `/ci wrong-doc`, or `/ci missed-doc`.
```

## Why Novyx Is Here

The base product works as a deterministic scorer.
Novyx Core Memory is here because over time the system should remember:

- which predicted docs were actually correct
- which suggestions reviewers rejected
- which kinds of changes tend to affect support or onboarding
- which code areas map to which docs in this repo

That turns it from a stateless checker into a repo-specific system that gets sharper over time.

## Who This Is For

- teams with product or API docs living near the code
- repos where PRs frequently change behavior without updating docs
- teams that want evidence-first review signals before they trust anything more automatic

## What It Does

- Reads a unified git diff or patch file
- Extracts changed files and changed symbols
- Extracts changed routes and API surfaces from diff lines
- Scans a docs tree for matching headings and terminology
- Ranks the most likely docs pages affected
- Generates a markdown report with evidence, confidence scores, and draft patch suggestions
- Generates a structured release-note draft when recommendation confidence is strong
- Generates adjacent support-knowledge and onboarding/tour update drafts when the repo has those audience-specific docs
- Stores patterns, triples, and audit traces in Novyx so the system gets smarter over time
- Emits the same result as JSON for GitHub webhook integration

## Try It In Two Minutes

Install the runtime:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Run the strongest local demo:

```bash
npm run demo:python
```

That demo exercises the production Python path and shows:

- primary docs impact
- release-note draft generation
- support knowledge updates
- onboarding/tour drift detection

Run the test suite:

```bash
npm test
```

## Run The Service

Start the Python webhook service locally:

```bash
.venv/bin/python -m change_intelligence.server
```

Run the production server with credentials:

```bash
GITHUB_WEBHOOK_SECRET=dev-secret NOVYX_API_KEY=nram_your_key GITHUB_TOKEN=ghp_your_token .venv/bin/python -m change_intelligence.server
```

The webhook endpoint is:

```bash
POST /webhooks/github
```

## Example Input

```json
{
  "action": "opened",
  "number": 42,
  "repository": { "full_name": "acme/app" },
  "pull_request": {
    "title": "Add coupon support to checkout",
    "patch": "diff --git a/src/example.ts b/src/example.ts\n..."
  }
}
```

## Example Output

The markdown brief includes:

- changed files
- extracted symbols
- ranked affected docs
- evidence for each match
- exact route/API surface matches when present
- recommended update focus areas

When confidence is strong enough, it can also include:

- release-note draft
- support-knowledge update draft
- onboarding or setup update draft

## Deploying To Fly.io

This repo now ships with a Fly.io deploy path for the Python webhook service.

Files:

- `Dockerfile` builds the production image
- `fly.toml` defines the Fly app, port, and `/health` check

Typical setup:

```bash
fly apps create change-intelligence-demo
fly secrets set GITHUB_WEBHOOK_SECRET=dev-secret NOVYX_API_KEY=nram_your_key
fly deploy
```

If you use GitHub App auth instead of a personal token, also set:

```bash
fly secrets set GITHUB_APP_ID=123456 GITHUB_APP_PRIVATE_KEY="$(cat /path/to/private-key.pem)"
```

Optional runtime config:

- `DASHBOARD_SECRET` to protect `/dashboard` and `/api/dashboard`
- `DOCS_REPO` and `DOCS_PATH` when docs are fetched from another repository
- `CONFIDENCE_THRESHOLD` to tune when the app comments on pull requests

## GitHub Integration

The repo includes a Python webhook service at `POST /webhooks/github`.

Current behavior:

- verifies `X-Hub-Signature-256` when `GITHUB_WEBHOOK_SECRET` is set
- accepts GitHub pull request webhook payloads
- fetches docs directly from the GitHub repo when GitHub credentials are configured
- fetches PR file patches from GitHub when patch text is not included in the webhook payload
- separates product/code changes from docs changes
- runs the analysis engine with a default confidence threshold of `60`
- upserts a marker-based PR comment on GitHub only when confidence clears the threshold
- deletes the marker comment when a rerun drops below the threshold

Dashboard endpoints:

- `GET /dashboard` returns a read-only internal HTML dashboard
- `GET /api/dashboard` returns the same operational view as JSON
- both surfaces expose aggregate KPIs, proof-window progress, recent analysis runs, recent feedback, and explicit Novyx partial-failure errors
- set `DASHBOARD_SECRET` to require the `X-Dashboard-Secret` header on both routes

## Learning Loop

Beyond the basic docs-drift detection flow, the app can also:

- recall similar historical change patterns from Novyx
- learn from merged PRs by comparing predicted docs with actual docs changed
- store mappings and memories for future ranking improvements
- create an audit trace in Novyx for every analyzed PR
- return adjacent support and onboarding update drafts when the repo contains those docs

Reviewer feedback is part of the live loop:

- every posted Change Intelligence comment includes `Reply with /ci correct, /ci wrong-doc, or /ci missed-doc`
- `feedback.yml` captures those commands and writes them into Novyx as explicit feedback memories
- only trusted repo participants count: the feedback workflow verifies that a Change Intelligence comment exists on the PR and that the feedback came from an `OWNER`, `MEMBER`, `COLLABORATOR`, or another user with GitHub write-level permission
- `daily-metrics.yml` computes the proof-point KPIs from that feedback and the analysis-run records

Novyx usage in the current app:

- `recall()` to fetch similar historical change patterns
- `triple()` to store code-to-doc mappings and rejection edges discovered during analysis
- `remember()` to save predictions and merged-PR feedback patterns for future PRs
- `trace_create()`, `trace_step()`, and `trace_complete()` for auditable recommendation traces

GitHub auth options:

- `GITHUB_TOKEN` for a simple bearer-token setup
- or `GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY` / `GITHUB_APP_PRIVATE_KEY_PATH` for real GitHub App installation auth

Optional configuration:

- `DOCS_PATH` to change the docs folder fetched from GitHub, default `docs`
- `DOC_OWNERSHIP_RULES_PATH` to override the repository-to-doc ownership rules file, default `change_intelligence/seeds/doc_ownership.json`
- `GITHUB_API_URL` for GitHub Enterprise or testing
- `CONFIDENCE_THRESHOLD` to tune when the app comments, default `60`

Reference Node CLI usage:

```bash
node ./src/cli.js --diff ./test/fixtures/sample.patch --docs ./test/fixtures/repo/docs --code ./test/fixtures/repo/src
```

Doc ownership rules:

- ownership rules map repository-specific code prefixes to docs prefixes
- matching rules add deterministic ranking weight and explicit evidence to recommendations
- the default rules file ships at `change_intelligence/seeds/doc_ownership.json`

Reference monitoring plan:

- [MONITORING.md](/Users/blakeheron/Desktop/demo/MONITORING.md)

## Roadmap

Near-term:

- doc ownership rules
- route and API surface mapping
- release-note generation

Later:

- onboarding and tour drift detection
- support knowledge updates
- product-change impact dashboard beyond the internal ops view

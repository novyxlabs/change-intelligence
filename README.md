# Change Intelligence

`change-intelligence` is a standalone GitHub App for product-change intelligence backed by Novyx.

The first job is narrow and useful:

> When product code changes, identify likely affected docs and generate a reviewable update brief with evidence.

This repo follows the useful part of the `gstack` pattern: a constrained workflow, explicit specialist output, and docs tied directly to source changes instead of vague "AI docs" promises.

The Python service under `change_intelligence/` is the only production runtime.
The earlier Node implementation in `src/` remains as a reference CLI and fixture harness for the ranking logic, not as a deployed server.

## What It Does

- Reads a unified git diff or patch file
- Extracts changed files and changed symbols
- Extracts changed routes and API surfaces from diff lines
- Scans a docs tree for matching headings and terminology
- Ranks the most likely docs pages affected
- Generates a markdown report with evidence, confidence scores, and draft patch suggestions
- Generates a structured release-note draft when recommendation confidence is strong
- Stores patterns, triples, and audit traces in Novyx so the system gets smarter over time
- Emits the same result as JSON for GitHub webhook integration

## Why This Wedge

Most repos can generate docs. Fewer can tell you which docs are now stale and why. That is the highest-leverage primitive for a broader system that later updates:

- docs
- changelogs
- onboarding tours
- support answers
- release notes

## Usage

Install the production runtime and test tooling:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Run the Python webhook service:

```bash
.venv/bin/python -m change_intelligence.server
```

Run the full test suite:

```bash
npm test
```

Analyze a patch file with the reference Node CLI:

```bash
node ./src/cli.js --diff ./test/fixtures/sample.patch --docs ./test/fixtures/repo/docs --code ./test/fixtures/repo/src
```

Analyze the current git working tree from a repo with the reference Node CLI:

```bash
node ./src/cli.js --repo /path/to/repo --docs /path/to/repo/docs
```

Emit JSON with the reference Node CLI:

```bash
node ./src/cli.js --diff ./change.patch --docs ./docs --json
```

Run the production server with credentials:

```bash
GITHUB_WEBHOOK_SECRET=dev-secret NOVYX_API_KEY=nram_your_key GITHUB_TOKEN=ghp_your_token .venv/bin/python -m change_intelligence.server
```

## Output

The markdown report includes:

- changed files
- extracted symbols
- ranked affected docs
- evidence for each match
- exact route/API surface matches when present
- recommended update focus areas
- release-note draft when confidence clears the threshold

## GitHub App Wrapper

The repo includes a Python webhook service at `POST /webhooks/github`.

Current behavior:

- verifies `X-Hub-Signature-256` when `GITHUB_WEBHOOK_SECRET` is set
- accepts a pull-request-style JSON payload
- fetches docs directly from the GitHub repo when GitHub credentials are configured
- fetches PR file patches from GitHub when patch text is not included in the webhook payload
- separates product/code changes from docs changes
- runs the analysis engine with a default confidence threshold of `60`
- recalls similar change patterns from Novyx
- learns from merged PRs by comparing predicted docs with actual docs changed
- stores new mappings and memories in Novyx
- creates an audit trace in Novyx for every analyzed PR
- upserts a marker-based PR comment on GitHub only when confidence clears the threshold
- deletes the marker comment when a rerun drops below the threshold
- returns the comment body and structured recommendations

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

Doc ownership rules:

- ownership rules map repository-specific code prefixes to docs prefixes
- matching rules add deterministic ranking weight and explicit evidence to recommendations
- the default rules file ships at `change_intelligence/seeds/doc_ownership.json`

Reference monitoring plan:

- [MONITORING.md](/Users/blakeheron/Desktop/demo/MONITORING.md)

Example payload:

```json
{
  "action": "opened",
  "repository": { "full_name": "acme/app" },
  "pull_request": {
    "number": 42,
    "title": "Add coupon support to checkout",
    "patch": "diff --git a/src/example.ts b/src/example.ts\n..."
  }
}
```

## Roadmap

Near-term:

- doc ownership rules
- route and API surface mapping
- release-note generation

Later:

- onboarding and tour drift detection
- support knowledge updates
- product-change impact dashboard

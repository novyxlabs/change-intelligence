# Architecture

The production system is intentionally small and Python-first.
The Node code under `src/` is kept only as a reference CLI for the original ranking logic and test fixtures.

## Pipeline

1. Accept a GitHub webhook event in `change_intelligence/server.py`
2. Verify the webhook signature
3. Collect patch text, PR files, and docs content from either the payload or GitHub
4. Parse changed files and changed lines
5. Extract probable symbols plus route/API surfaces from added and removed lines
6. Build a docs index from markdown-like files
7. Score docs against changed paths, filenames, tokens, symbols, and exact route/API surface matches
8. Produce:
   - ranked recommendations
   - a markdown brief
   - structured JSON
9. Optionally learn from merged PRs, persist traces in Novyx, and upsert or clear the PR comment

## Design Choices

- No external dependencies: easier to audit, easier to run in CI, no install friction
- Deterministic scoring: useful before introducing any LLM layer
- Evidence-first output: every recommendation should cite a concrete reason
- Repository-specific ownership rules can bias ranking without changing the webhook contract

## Extension Points

- Replace the heuristic scorer with a learned or LLM-backed ranker
- Add source-code ownership and metadata rules
- Add docs templates for automatic patch generation

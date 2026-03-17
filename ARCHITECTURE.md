# Architecture

The current system is intentionally small.

## Pipeline

1. Load a diff from either:
   - `git diff --unified=0`
   - a `.patch` or `.diff` file
2. Parse changed files and changed lines
3. Extract probable symbols from added and removed lines
4. Build a docs index from markdown-like files
5. Score docs against changed paths, filenames, tokens, and symbols
6. Produce:
   - ranked recommendations
   - a markdown brief
   - structured JSON
7. Optionally wrap the result in a GitHub webhook response for PR comments

## Design Choices

- No external dependencies: easier to audit, easier to run in CI, no install friction
- Deterministic scoring: useful before introducing any LLM layer
- Evidence-first output: every recommendation should cite a concrete reason

## Extension Points

- Replace the heuristic scorer with a learned or LLM-backed ranker
- Add a GitHub App wrapper that opens comments or PRs
- Exchange the current local webhook wrapper for a real installation-token GitHub App
- Add source-code ownership and metadata rules
- Add docs templates for automatic patch generation

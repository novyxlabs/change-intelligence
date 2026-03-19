# Change Intelligence Monitoring Window

This project tracks a formal `20-30 PR` monitoring window across the live repos where Change Intelligence is installed.

The proof-point KPIs are:

- `top-1 correct rate`: `correct / (correct + wrong-doc + missed-doc)`
- `comment rate`: `commented / (commented + suppressed)`
- `false-positive rate`: `wrong-doc / commented`

Feedback source:

- reviewers reply on PRs with `/ci correct`
- reviewers reply on PRs with `/ci wrong-doc`
- reviewers reply on PRs with `/ci missed-doc`

System of record:

- explicit reviewer feedback is stored in Novyx by `change_intelligence/feedback.py`
- analysis-run outcomes are stored in Novyx by `change_intelligence/novyx_store.py`
- daily KPI computation runs from `change_intelligence/metrics.py`

Reporting rule:

- do not quote metrics publicly until the window has at least `20` analyzed PRs
- once the window reaches `20-30` PRs, freeze the numbers and use that snapshot for the "Built on Novyx Core" proof point

Current installation set:

- `novyxlabs/novyx-core`
- `novyxlabs/novyx-mcp`
- `novyxlabs/novyx-starter-kit`
- `novyxlabs/novyx-memory-skill`
- `novyxlabs/novyx-vault`
- `novyxlabs/novyx-site`

Reporting format:

- overall metrics from all installed repos
- per-repo breakdown for internal review
- only freeze and publish the overall snapshot once the combined window reaches `20-30` analyzed PRs

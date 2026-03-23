# Proof

This project should earn belief with concrete examples, not category words.

Below are three small but believable examples from the repo's own fixtures and live integration work.

## 1. Billing Change -> Billing Doc

Input change:

- file changed: `src/billing/createCheckoutSession.ts`
- symbol changed: `createCheckoutSession`

Expected docs target:

- `docs/billing.md`

Observed result from the fixture analyzer:

- top recommendation: `billing.md`
- evidence:
  - shared path terms with `src/billing/createCheckoutSession.ts`
  - shared change terms including `createCheckoutSession`
  - matched changed symbol: `createCheckoutSession`

Why this matters:

- this is the core wedge in one screen
- product code changed in billing
- the system pointed at the billing doc, not a random markdown file

Reference command:

```bash
node ./src/cli.js --diff ./test/fixtures/sample.patch --docs ./test/fixtures/repo/docs --code ./test/fixtures/repo/src --json
```

## 2. Search API Change -> Docs + Support + Onboarding

Input change:

- file changed: `src/api/search.py`
- surfaces changed:
  - `/v1/search`
  - `/v1/search/reindex`
- symbols changed:
  - `search`
  - `login_setup`

Observed result from the production Python path:

- top docs recommendation: `search-reference.md`
- adjacent docs recommendation: `onboarding/search-quickstart.md`
- support docs recommendation: `support/search-faq.md`
- release note generated
- support update generated
- onboarding update generated

Why this matters:

- it shows the real expansion path for Change Intelligence
- not just "what doc is stale"
- also "what support and onboarding surfaces are now suspect"

Reference command:

```bash
npm run demo:python
```

## 3. Real Webhook Round Trip

What happened:

- the live Fly deployment received real `pull_request` webhook events from GitHub
- the first live test exposed a production bug: GitHub's real event shape uses top-level `number`, while the app was reading `pull_request.number`
- the bug was fixed in production and merged into `main`
- a regression test was added so the parser now matches the real GitHub payload shape

Why this matters:

- this is not just fixtureware
- the deployed webhook path was exercised against a real GitHub repo
- public users benefit from a bug that was found the hard way and fixed immediately

Relevant fix:

- [`change_intelligence/service.py`](/Users/blakeheron/Desktop/demo/change_intelligence/service.py)
- [`tests/test_service.py`](/Users/blakeheron/Desktop/demo/tests/test_service.py)

## What These Examples Show

- the narrow wedge works: code change -> likely stale docs
- route and API surfaces make the ranking better
- adjacent audiences matter: support and onboarding drift are real
- Novyx Core Memory makes sense here because repo-specific memory can reinforce correct predictions over time

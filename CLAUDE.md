# Deploy

Platform: Fly.io

Production runtime:
- Python service launched with `python -m change_intelligence.server`

Deploy config:
- App config: `fly.toml`
- Container build: `Dockerfile`
- Health endpoint: `GET /health`
- Default internal port: `8080`

Required secrets before deploy:
- `GITHUB_WEBHOOK_SECRET`
- `NOVYX_API_KEY`

Optional secrets and config:
- `GITHUB_TOKEN`
- `GITHUB_APP_ID`
- `GITHUB_APP_PRIVATE_KEY`
- `DOCS_REPO`
- `DOCS_PATH`
- `DOC_OWNERSHIP_RULES_PATH`
- `CONFIDENCE_THRESHOLD`
- `DASHBOARD_SECRET`
- `NOVYX_API_URL`
- `NOVYX_AGENT_ID`

Useful commands:
- `fly status`
- `fly deploy`
- `fly logs`
- `fly secrets set GITHUB_WEBHOOK_SECRET=... NOVYX_API_KEY=...`

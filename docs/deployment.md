# Deployment

## Target

Render, deployed from the Docker image defined in `docs/adr/0004-containerization.md`, with Render's managed PostgreSQL. See `docs/adr/0005-deployment-platform.md` for why Render over Railway/Fly.io/self-hosting.

## Environments

- **Local:** `docker compose up` runs the application and a local Postgres instance together — the same Dockerfile used in production, for real dev/prod parity.
- **Production:** Render web service + managed Postgres, environment variables configured in Render's dashboard, never in the repository.

## Configuration and secrets

All configuration is via environment variables (see `.env.example` for the full list). Locally, `.env` (git-ignored) supplies them via `python-dotenv`; in production, Render's own environment-variable configuration supplies them. No secrets manager (Vault, AWS Secrets Manager) is used — disproportionate for a single-tenant app with one deployment target.

## What "production-grade" means for this project, honestly

**Means:** correct handling of the failure modes in `docs/reliability.md`, no silent data loss, idempotent/duplicate-safe by design, every decision auditable (`docs/data-model.md`), financial logic that's actually arithmetic-checked, and honest boundaries — the mocked accounting ledger is clearly labeled as mocked, everywhere it's mentioned.

**Does not mean, and is never claimed:** "enterprise-ready," any specific throughput figure never actually tested, "integrated with your ERP" before it actually is one (see `docs/architecture.md` on the mock ledger), "compliant" with any framework (no compliance work has been done), or a guarantee of extraction accuracy.

## Deployment sequencing

Deployment happens in Phase 17, once the application is feature-complete — not before, since deploying an unfinished system to a public URL adds no value and this project has no need for continuous staged rollouts at its scale.

## Deploying (Phase 17)

`render.yaml` at the repo root is a Render Blueprint — infrastructure as code for the web service and its managed Postgres database. This is prepared and reviewable in the repo, but the account-level actions below are necessarily manual: they require a real Render account and real production secrets that should never pass through an agent or be committed anywhere.

1. **Push this repo to GitHub** if it isn't already (Render deploys from a Git repo, not a local directory).
2. In the Render dashboard: **New +** → **Blueprint**, connect the GitHub repo. Render reads `render.yaml` and proposes the web service + database.
3. Render prompts for the three secrets marked `sync: false` in the blueprint — fill these in **only in Render's dashboard**, never in a file:
   - `API_KEY` — generate a fresh, strong value (e.g. `openssl rand -hex 32`); do not reuse the local dev default.
   - `APP_SECRET_KEY` — same: generate fresh, don't reuse the local dev default.
   - `MISTRAL_API_KEY` — a real Mistral key. Using a dedicated key for production (separate from any local/dev key) is the safer choice, so one can be rotated without affecting the other.
4. Apply the Blueprint. Render builds the Docker image, provisions the database, and runs `dockerCommand` (`alembic upgrade head` then `uvicorn`, see `render.yaml`) — migrations run automatically on every deploy, not as a separate manual step.
5. Seed the known-vendor list once the service is live: from the Render dashboard's shell for the web service, run `python -m app.seed_vendors` (see `app/seed_vendors.py`) — this isn't run automatically, matching local dev's own setup instructions in the README.

## Known gaps in this deployment, stated plainly

- **No worker deployed.** `app/worker.py`'s crash-recovery logic (Phase 13) exists but nothing schedules it to run in production — a Render Background Worker or Cron Job would be the way to do that, and neither is on Render's free tier. This was a deliberate, cost-conscious scope decision for the initial deployment, not an oversight: Phase 17's own completion criterion (a document reaching a terminal state end to end) only exercises the synchronous upload path, which doesn't need the worker at all. Revisit if continuous crash recovery in production is ever actually needed.
- **Uploaded files don't persist across restarts or redeploys.** `LocalStorageProvider` (Phase 4) writes to the web service's local disk, which Render does not persist for a service without an attached paid Persistent Disk. A document's *record* (state, extracted fields, audit trail) survives fine in Postgres; the original file bytes behind a signed `/files/{storage_path}` URL do not. The S3-compatible `StorageProvider` this was always meant to graduate to (`docs/architecture.md`) isn't built yet — not pretended otherwise here.
- **Render's free Postgres plan is time-limited**, not a permanent free service — check current terms in Render's dashboard before relying on it past the initial demo period; this project doesn't commit to a specific expiration figure here since Render's own terms are authoritative and can change (same posture as `docs/adr/0005-deployment-platform.md`'s cold-start caveat).

## Smoke test

Phase 17's completion criterion: a real document, uploaded through the live deployed instance, reaches a terminal state end to end. This is the minimum bar for calling the deployment done — not a full Tier-4 test suite run against production, which stays a local/CI concern.

```bash
curl -X POST https://<your-render-service>.onrender.com/documents \
  -H "Authorization: Bearer <the real production API_KEY>" \
  -F "file=@spike/samples/inv_01_baseline_usd.pdf"
```

A free web service spins down after 15 minutes of inactivity (`docs/adr/0005-deployment-platform.md`) — the first request after a while can take 30–60 seconds to wake it; that's expected, not a failure. Confirm the response's `state` is `VALIDATED`, `NEEDS_REVIEW`, or `DUPLICATE` — never left `EXTRACTING`/`VALIDATING`, and never `FAILED` unless deliberately testing that path. Run this yourself against the real deployed URL with the real production key, rather than sharing that key — see `docs/security.md`.

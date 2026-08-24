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

## Smoke test

Phase 17's completion criterion: a real document, uploaded through the live deployed instance, reaches a terminal state end to end. This is the minimum bar for calling the deployment done — not a full Tier-4 test suite run against production, which stays a local/CI concern.

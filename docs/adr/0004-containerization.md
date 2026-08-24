# ADR 0004: Containerization — Docker

**Status:** Accepted
**Confidence:** High

## Decision

A single `Dockerfile` for the application plus a `docker-compose.yml` for local development (app + PostgreSQL). No orchestration layer (no Kubernetes).

## Alternatives considered

- **No containerization, native local Python env** — simpler on day one, but risks dev/prod environment drift and doesn't match how the app will actually be deployed on Render.
- **Kubernetes** — solves multi-node orchestration and scaling problems this single-service, single-tenant project does not have. Rejected outright as disproportionate.

## Why

Genuinely cheap (one file, no orchestration layer) and gives real dev/prod parity. Render deploys directly from a Dockerfile, so this isn't extra work duplicated for two different deployment shapes — it's the one artifact both local dev and production use. It's also a widely-expected production skill, which matters for the portfolio/learning objective, at a low complexity cost relative to that value.

## What would change this

Nothing currently anticipated within this project's scope — Docker without orchestration is expected to remain sufficient through Phase 19.

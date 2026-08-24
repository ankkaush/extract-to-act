# ADR 0005: Deployment platform — Render

**Status:** Accepted
**Confidence:** Medium

## Decision

Deploy on Render (web service + managed PostgreSQL), from the Docker image built per ADR 0004.

## Alternatives considered

- **Railway** — better day-to-day developer experience (one-click Postgres, connection strings auto-injected), but usage-metered pricing with no hard spending cap by default is a worse fit for a project explicitly optimizing for predictable, low cost.
- **Fly.io** — pure pay-as-you-go with no free tier for new users as of 2026, and its Postgres offering is a self-managed VM rather than a fully managed service, which shifts real operational work onto the project owner.
- **Self-hosting** — maximum control, but adds infrastructure-management overhead disconnected from this project's learning objective.

## Why

Render is the only one of the three PaaS options with a genuine no-credit-card free tier as of 2026, and its managed PostgreSQL includes point-in-time recovery, automated backups, and encryption at rest on paid tiers — production-grade infrastructure that would take real time to replicate manually. Continuity with prior projects also favors it.

## Known trade-off

Render's free web service spins down after 15 minutes of inactivity and takes 30–60 seconds to wake — acceptable for a portfolio project without live traffic, but worth knowing before a live demo to a client or interviewer. A paid Starter instance ($7/mo) removes the cold start if that becomes a recurring problem.

## What would change this

If live demos to clients/interviewers become frequent enough that cold-start latency is a recurring embarrassment, upgrade to the paid Starter tier — a $7/mo decision, not an architectural one. If Render's free-tier terms change materially, this ADR should be revisited.

# ADR 0008: API authentication — static bearer token for MVP

**Status:** Accepted
**Confidence:** Medium — explicitly a placeholder for single-tenant scope, not a final answer

## Decision

Mutating endpoints (starting with `POST /documents` in Phase 4) require a
static bearer token, checked via an `Authorization: Bearer <token>` header
against a single configured `API_KEY`. No user accounts, sessions, or
OAuth.

## Alternatives considered

- **OAuth / SSO** — solves multi-user, multi-identity authentication. This project has no such requirement yet, and building it now would be exactly the kind of enterprise-security-program over-engineering `docs/security.md` explicitly rules out for this scale.
- **Session-based login (username/password + cookie)** — implies a user table, password hashing, session storage — real complexity for a system with, at MVP, one operator.
- **No authentication at all** — rejected outright: this is a public repository and, per `docs/security.md`, mutating endpoints must never be open.

## Why a shared token is enough for now, and its known limit

A single shared secret is sufficient to satisfy "authenticated, not public" for ingestion (Phase 4) and the review/approval endpoints as they're built. It is explicitly **not** sufficient for one thing `docs/security.md` and `docs/workflow.md` both require: attributing a specific review correction or approval decision to a specific person. That distinction matters starting Phase 10 (human review) and especially Phase 11 (approval), where "every approval/rejection is attributed and logged, never anonymous" means a shared token alone won't do — a `reviewer`/`approver` identity string will need to come from somewhere real by then.

This ADR deliberately does not solve that yet. The plan: keep the shared-token gate for MVP, and revisit authentication specifically when Phase 10/11 needs real per-actor identity — at which point a lightweight mechanism (e.g. a small static user/API-key-per-person table) is likely enough, still short of full OAuth.

## Security notes

- The default `API_KEY` value (see `.env.example`) is an insecure placeholder for local development only, following the same pattern as `APP_SECRET_KEY` — any real deployment (Phase 17) must set a strong, unique value via Render's environment configuration, never a committed file.
- The key is never logged (see `docs/security.md`).

## What would change this

The moment attribution-per-actor is actually needed (Phase 10/11), or if this project ever needed more than one concurrent human operator with different permissions.

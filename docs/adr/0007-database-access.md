# ADR 0007: Database access — synchronous SQLAlchemy 2.0 + psycopg 3

**Status:** Accepted
**Confidence:** High

## Decision

Use synchronous SQLAlchemy 2.0 (declarative models, `Session`) with the `psycopg` (v3) driver, via Alembic for migrations — not an async ORM stack, despite FastAPI's async support.

## Alternatives considered

- **Async SQLAlchemy (`asyncpg` / async `Session`)** — matches FastAPI's async request handlers, but adds real complexity (async session lifecycle, async-aware Alembic config, no blocking calls anywhere in the call graph) for a benefit this project doesn't need yet.
- **An async-native ORM (e.g. `Tortoise ORM`)** — less mature migration tooling than Alembic, and would break continuity with the SQLAlchemy/Alembic pairing already chosen in ADR 0002.

## Why

The actual latency in this system's request paths is dominated by external provider calls (extraction, accounting) — not database round-trips. FastAPI's async event loop pays off most when many concurrent requests are waiting on I/O simultaneously at real scale; at this project's single-tenant, low-volume scope, a sync DB layer inside otherwise-async route handlers (via FastAPI's threadpool for sync dependencies) is simpler to write, simpler to test, and simpler for the scheduled worker (itself a plain sync process, not an async server) to share the same models and session logic with the API.

## What would change this

If the worker or API genuinely needed to hold many concurrent in-flight DB operations at once — real multi-tenant concurrency, not this project's expected scale — async SQLAlchemy would earn its added complexity. Not expected before Phase 19, if ever.

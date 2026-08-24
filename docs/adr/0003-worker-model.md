# ADR 0003: Background processing — scheduled polling worker, no queue

**Status:** Accepted
**Confidence:** High, explicitly conditional on scale

## Decision

Use a single scheduled worker process that polls PostgreSQL for documents needing their next processing step. No message broker, no distributed task queue.

## Alternatives considered, and why each is rejected right now

| Technology | Problem it solves | Why not here |
|---|---|---|
| Redis | Fast shared cache, session store, or broker for a task queue | No caching/session need yet; would only be justified alongside Celery, which is itself not justified |
| Celery | Distributed task execution across multiple worker processes/machines with a message broker | One process, low volume, I/O-bound calls — the scheduled worker already covers "run this later, retry on failure" without a broker |
| Kafka | High-throughput event streaming across many independent consumers | There is one consumer of "a document changed state" (the worker itself), not multiple independent services reacting to events |
| Temporal | Durable orchestration across many long-running, heterogeneous, interdependent async steps with automatic compensation | The state machine has roughly a dozen states and one worker; Temporal earns its complexity at dozens of interdependent workflows with complex rollback logic, which this project doesn't have |

## Why the simple option is sufficient

At single-tenant, low-volume, I/O-bound scale, a persisted state column plus a scheduled worker gives full visibility through plain SQL ("show me everything stuck in `NEEDS_REVIEW`" is one query) that a queue's own tooling would otherwise need to provide separately, at zero added infrastructure cost.

## What would change this

Real concurrent multi-worker contention (thousands of documents/day, several workers), or genuinely complex async orchestration across many parallel, long-running chains with scheduled reminders. Note: even concurrent-worker safety, if it becomes necessary, is available directly in PostgreSQL via `SELECT ... FOR UPDATE SKIP LOCKED`, without introducing new infrastructure — that would likely come before a full queue/broker is justified.

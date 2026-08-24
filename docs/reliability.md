# Reliability

## Business exception vs. technical failure

A **technical failure** means the system couldn't complete the work it was supposed to do (a network call broke, a service was down) — no business judgment has happened yet, and the document simply needs to be retried later. A **business exception** means the system did its job correctly and the *result itself* needs a human decision (numbers don't reconcile, the invoice looks duplicated, the vendor is unfamiliar) — the pipeline worked; the answer genuinely is "this needs a person," not "this is broken."

## Failure modes and responses

| Failure | Category | Response |
|---|---|---|
| Provider timeout | Technical, transient | Retry with bounded backoff — no human judgment involved |
| Provider rate limit | Technical, transient | Retry with backoff honoring the provider's retry-after |
| Provider outage (sustained) | Technical | After bounded retries exhaust, `FAILED` + alert — silent endless retrying would hide a real outage from whoever needs to act |
| Malformed / corrupted upload | Deterministic input problem | No retry — straight to `NEEDS_REVIEW` with a specific reason |
| Duplicate upload (same request) | Technical | Idempotency key returns the existing record, no reprocessing |
| Duplicate invoice (different request) | Business condition | Content-fuzzy-match → `DUPLICATE`, no reprocessing, no re-spend on extraction |
| Downstream accounting-write failure | Technical, high stakes | Retry with an idempotency check first (verify before ever writing twice); `FAILED` + alert if exhausted — a stuck document here is money not recorded |
| Worker crash / app restart | Technical | Scheduled worker resumes anything not in a terminal state on next run — see `docs/state-machine.md` |
| Notification failure | Technical, low stakes | Retry briefly, then log and continue — never block the pipeline on a notification |
| User resubmits / refreshes | Technical | Idempotency key returns the existing record instead of creating a duplicate |
| Database failure | Technical | Application-level operations fail fast and surface an error; recovery relies on Postgres's own durability guarantees, not application-level replication (out of scope at this scale) |

## Idempotency, by scenario

1. **Same request repeated** (client retries after a timeout) — a request-derived idempotency key means a repeat returns the existing record instead of creating a second `RECEIVED` row.
2. **Same invoice via two different requests** (two people upload it, or a supplier double-sends) — the request-level key won't catch this; content-level dedupe (fuzzy match on vendor + invoice number + amount + date, plus exact file hash) does, routing the second one to `DUPLICATE`.
3. **Downstream write succeeds but the app times out before knowing** — this is why `ACTIONED` exists as distinct from `COMPLETED` (`docs/state-machine.md`): before writing, the app records "attempted"; on resume, it checks whether the write already landed before ever writing again, rather than blindly retrying a write-only call.

All three mechanisms are cheap (one extra column, one fuzzy-match query, one key pattern) against the single costliest realistic failure — a duplicate payment — which is also the failure most likely to visibly embarrass a demo if it happened. This is treated as proportionate, not gold-plated: skipping any of the three creates an easily-triggered bug, not a hypothetical enterprise edge case.

## No queue, deliberately

See `docs/adr/0003-worker-model.md` for the full reasoning. Every failure above is handled by a persisted state column, bounded retries, and a scheduled worker — no Celery, Kafka, or Temporal.

## Where this is implemented and tested

Phase 13 implements retry/backoff and dead-letter handling; every row above gets a test that forces that specific condition, including a simulated crash (writing a stuck in-flight state directly to the database and asserting the worker recovers it) rather than actually killing a process.

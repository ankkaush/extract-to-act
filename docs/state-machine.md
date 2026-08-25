# State machine

Every document moves through a single state machine, persisted after every transition in `state_history` before the next step starts. This is what makes crash recovery possible: a scheduled worker finds anything not in a terminal state and resumes it from its last persisted state, rather than reprocessing from scratch (which would also waste a paid extraction call — see `docs/cost-strategy.md`).

## States

| State | Meaning | Why it exists |
|---|---|---|
| `RECEIVED` | Document stored, idempotency key assigned | Crash-safety anchor — nothing is lost even if every later step fails |
| `EXTRACTING` | Extraction call in flight | Persisted so a crash mid-call is distinguishable from "never started" |
| `EXTRACTED` | Extraction succeeded, normalized and stored | Durable regardless of what validation later finds |
| `VALIDATING` | Deterministic rules running | Same in-flight rationale as `EXTRACTING` |
| `NEEDS_REVIEW` | A business condition, not a failure | Confidence or rule threshold triggered — a human is needed |
| `VALIDATED` | Passed deterministically or approved by a reviewer | Ready for the approval/action decision |
| `ACTIONED` | Downstream write attempted and recorded | Distinct from `COMPLETED` so a timeout after a successful write is safely resumable — see `docs/reliability.md` |
| `COMPLETED` | Downstream write confirmed | Terminal success |
| `REJECTED` | A reviewer determined this isn't payable/valid | Terminal |
| `DUPLICATE` | Deterministically matched to an already-processed invoice | Terminal, no action taken, no re-spend on extraction |
| `FAILED` | Unrecoverable technical failure, dead-lettered | A system problem, not a business one — requires manual recovery, deliberately distinct from `NEEDS_REVIEW` |

## Transitions

```
RECEIVED → EXTRACTING → EXTRACTED → VALIDATING ─┬→ NEEDS_REVIEW → VALIDATED
                                                  └→ VALIDATED
RECEIVED → DUPLICATE              (terminal, exact file-hash match — see below)
VALIDATING → DUPLICATE            (terminal, content-level match — see below)
VALIDATED → ACTIONED → COMPLETED  (terminal, success)
NEEDS_REVIEW → REJECTED           (terminal, reviewer rejects)
any in-flight state → FAILED      (terminal, retries exhausted)
```

**`RECEIVED → DUPLICATE` was added in Phase 9**, revising the original single-source diagram. The original design only anticipated `VALIDATING → DUPLICATE`, but Phase 9's own completion criteria requires an exact re-upload (identical file bytes, matched by content hash) to reach `DUPLICATE` *without spending a paid extraction call on it* — which is only possible if the check runs before `EXTRACTING`, not after. `VALIDATING → DUPLICATE` still exists separately for the case extraction genuinely has to run for: the same invoice arriving as a *different* file (re-scanned, re-typed) but matching an existing invoice's (vendor, invoice number, total, invoice date) once extracted. See `docs/reliability.md`, idempotency scenario 2, and `app/duplicate_detection.py`.

A reviewer's correction moves a document from `NEEDS_REVIEW` to `VALIDATED`, rejoining the same forward path a touchless document takes — review is a detour, not a parallel pipeline.

## Crash recovery, plainly

If the application or worker process dies mid-transition, the document is left in whatever in-flight state (`EXTRACTING`, `VALIDATING`) was last persisted. On restart, the scheduled worker scans for anything not in a terminal state (`COMPLETED` / `REJECTED` / `DUPLICATE` / `FAILED`). An in-flight state older than a configured timeout is treated as an interrupted attempt and retried per the policy in `docs/reliability.md` — never silently reprocessed from `RECEIVED`, and never left stuck indefinitely.

## A noted, intentionally open trade-off

Persisting `EXTRACTING`/`VALIDATING` as distinct rows is defensible on crash-safety grounds (one extra column value, precise recovery). An acceptable simpler alternative — skip the in-flight states and use a timeout rule against `RECEIVED`/`EXTRACTED` instead — was considered and is not ruled out; it trades slightly fuzzier recovery for a smaller state model. This plan keeps the explicit in-flight states for MVP; Phase 3 should treat this as a cheap, low-risk decision to make once, not a debate to reopen per phase.

## `NEEDS_REVIEW` sub-cases

No separate top-level state exists for "document doesn't look like an invoice at all" (see `docs/architecture.md` on classification) — it lands in `NEEDS_REVIEW` with a reason code of `not_recognized`, alongside other review reasons (low confidence, arithmetic mismatch, unknown vendor). A reason code is sufficient; a new state is not needed.

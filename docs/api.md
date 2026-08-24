# API design

This describes the eventual API surface, derived from the workflow (`docs/workflow.md`) and state machine (`docs/state-machine.md`). Nothing here is implemented yet — routes, request/response shapes, and error formats will be finalized as each owning phase is built, and this document should be kept in sync at that point rather than treated as frozen now.

## Conventions (planned)

- JSON request/response bodies, standard HTTP status codes.
- All mutating endpoints require authentication (see `docs/security.md`); the specific auth mechanism is a Phase 2 decision, not yet made.
- Errors return a consistent shape: `{"error": "<code>", "message": "<human-readable>"}`.

## Endpoints, by owning phase

### Phase 4 — Ingestion
- `POST /documents` — upload a file (multipart), returns the created `document` record (or the existing one, if the request's idempotency key matches a prior submission).
- `GET /documents/{id}` — current state and metadata for a document.
- `GET /documents` — list, filterable by state.

### Phase 6 — Extraction
- `GET /documents/{id}/extraction` — normalized extracted fields, confidence, and provenance for a document (read-only; extraction itself is triggered internally by the worker, not via API call).

### Phase 10 — Human review
- `GET /review` — the review queue: documents in `NEEDS_REVIEW`, with reason codes.
- `GET /review/{id}` — a single document's original file reference plus extracted fields, for the side-by-side review UI.
- `POST /review/{id}/correct` — submit field corrections; writes a `review_events` audit entry and advances the state machine.
- `POST /review/{id}/reject` — reject the document; moves it to `REJECTED`.

### Phase 11 — Approval
- `GET /approvals` — documents awaiting approval.
- `POST /approvals/{id}/approve` — approve; requires an authenticated, authorized actor; writes an `approvals` row.
- `POST /approvals/{id}/reject` — reject.

### Phase 16 — Observability
- `GET /dashboard` — the metrics summary (straight-through rate, review rate, average processing time, etc. — see `docs/cost-strategy.md` for which are measured vs. estimated).

## Explicitly not planned

- No endpoint to trigger a payment or any downstream financial transfer — the system creates a record and marks it ready; it never executes a payment (see `docs/problem.md`).
- No bulk/batch upload endpoint for MVP — one document per request is sufficient to demonstrate the workflow and keeps validation/idempotency logic simpler.
- No public/unauthenticated read access to any endpoint, even in a demo deployment — see `docs/security.md`.

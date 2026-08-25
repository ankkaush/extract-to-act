# API design

This describes the eventual API surface, derived from the workflow (`docs/workflow.md`) and state machine (`docs/state-machine.md`). Nothing here is implemented yet — routes, request/response shapes, and error formats will be finalized as each owning phase is built, and this document should be kept in sync at that point rather than treated as frozen now.

## Conventions

- JSON request/response bodies, standard HTTP status codes.
- All endpoints require an `Authorization: Bearer <API_KEY>` header — see `docs/adr/0008-api-authentication.md`. A missing or wrong token returns `401`.
- Errors currently return FastAPI's default `{"detail": "<message>"}` shape. A consistent custom error envelope (`{"error": "<code>", "message": "..."}`) is deferred until more than one endpoint family exists to standardize across.

## Endpoints, by owning phase

### Phase 4 — Ingestion (implemented)
- `POST /documents` — upload a file (`multipart/form-data`, field name `file`). Optional `Idempotency-Key` header; a repeated request with the same key returns the existing document (`201`, not an error) instead of creating a duplicate. Rejects unrecognized file content with `415` (content-sniffed — PDF/PNG/JPEG/TIFF only, see `docs/security.md`) and oversized files with `413`.
- `GET /documents/{id}` — current state and metadata for a document. `404` if it doesn't exist.
- `GET /documents` — list, optionally filtered with `?state=`.

`DocumentOut` shape: `{id, state, original_filename, mime_type, content_hash, idempotency_key, created_at, updated_at}`.

### Phase 6 — Extraction (implemented)
- `GET /documents/{id}/extraction` — normalized extracted fields (with per-field confidence/page/bbox/source_text where the provider supplies them), line items, and the promoted header columns. `404` if the document doesn't exist, or if extraction hasn't produced a result (e.g. it failed — check `GET /documents/{id}`'s `state`).
- Extraction is **not** a separate call — `POST /documents` runs it synchronously as part of the upload request and only returns once it's done. There's no background worker yet (that's Phase 13); this is a deliberate, documented simplification, not an oversight — see `app/routers/documents.py`.

`ExtractionResultOut` shape: `{id, document_id, provider_name, provider_model_version, vendor_name, invoice_number, invoice_date, due_date, currency, subtotal, tax, total, fields, line_items, created_at}`.

### Phase 7 — Deterministic Validation (implemented)
No new endpoint — validation runs synchronously immediately after extraction succeeds, as part of the same `POST /documents` call: `EXTRACTED` → `VALIDATING` → `VALIDATED` (every rule passed) or `NEEDS_REVIEW` (at least one failed). A document's final `state` in the upload response already reflects the validation outcome, not just extraction. Every rule's individual pass/fail and reason is persisted (`validation_results`, not yet exposed via its own endpoint — that's part of Phase 10's review UI, which needs to show a reviewer exactly why a document landed in the queue).

**Full synchronous chain as of Phase 7:** a successful `POST /documents` response never actually shows `state: "EXTRACTED"` — extraction success always continues straight into validation within the same request. The only end states an upload response can show are `VALIDATED`, `NEEDS_REVIEW`, or `FAILED` (extraction itself failed, before validation ever ran).

### Phase 8 — Vendor Matching (implemented)
No new endpoint — vendor matching runs as one more rule inside the same validation step as Phase 7's checks (`docs/workflow.md` lists it as its own conceptual step, but the state machine has no dedicated "matching" state). A vendor name that doesn't fuzzy-match a known vendor closely enough is exactly as likely to send a document to `NEEDS_REVIEW` as a missing required field or a bad arithmetic check — same `validation_results` table, same `vendor:known` rule name. Known vendors are seeded via `python -m app.seed_vendors` (not automatic on startup — see `app/seed_vendors.py`).

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

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

### Phase 9 — Duplicate Detection (implemented)
No new endpoint — two independent checks, no worker or async step involved:
- **Exact file-hash match**, checked at `RECEIVED`, before extraction ever runs — a `POST /documents` with content identical to a prior upload (any state except `FAILED`) returns `state: "DUPLICATE"` immediately, never spending a paid extraction call. This is distinct from the `Idempotency-Key` behavior (Phase 4): that catches the same *request* retried, this catches the same *file* submitted through a genuinely different request.
- **Content-level match**, checked during `VALIDATING` (needs extracted fields) — the same invoice arriving as a different file (re-scanned, re-typed) is caught by an exact-after-normalization match on vendor + invoice number + total + invoice date together. A partial match (e.g. same vendor and date, different invoice number) is correctly treated as two different invoices, not flagged.

`docs/state-machine.md` documents a `RECEIVED → DUPLICATE` transition added in this phase, alongside the originally-planned `VALIDATING → DUPLICATE`.

### Phase 10 — Human review (implemented)
- `GET /review` — the review queue: documents in `NEEDS_REVIEW`, oldest first, each with the specific `ValidationResult` rows that failed (not just a summary reason string — a reviewer needs to see exactly which rule(s) triggered the queue entry).
- `GET /review/{id}` — a single document's fields, its failed rules, and a signed `file_url` for the original document. `404` if the document doesn't exist. Works for any document, not only ones currently `NEEDS_REVIEW`, since it's also useful for auditing a past decision.
- `POST /review/{id}/correct` — body: `{"reviewer": "<free-text identity>", "corrections": [{"field_name": "...", "corrected_value": "..."}]}`. Only the promoted extraction header fields (`vendor_name`, `invoice_number`, `invoice_date`, `due_date`, `currency`, `subtotal`, `tax`, `total`) are correctable. Each correction writes one `review_events` row (original value captured before the overwrite) and the corrected value is applied directly to the `extraction_results` row. Requires `state == NEEDS_REVIEW` (`409` otherwise, e.g. already corrected or rejected). An unknown `field_name`, or a value that doesn't parse into that field's type, is `422` — a correction is exactly the kind of financially-consequential write that should fail loudly, never silently coerce. On success the document moves straight to `VALIDATED`, per `docs/state-machine.md` — a correction is a reviewer's assertion that the value is now right, so it is **not** re-run through Phase 7/8's deterministic rules.
- `POST /review/{id}/reject` — body: `{"reviewer": "...", "reason": "..."}`. Requires `state == NEEDS_REVIEW` (`409` otherwise). Moves the document to `REJECTED`; the reviewer and reason are recorded in the `state_history` row's `reason` text (there is no separate `approvals`-style attribution table yet for review decisions — see `docs/adr/0008-api-authentication.md` on why `reviewer` is a free-text field, not an authenticated identity, at this stage).

`ReviewCorrectionIn`/`ReviewRejectionIn`/`ReviewDetailOut`/`ReviewQueueItemOut` shapes: see `app/schemas.py`.

### Phase 10 — Signed file access (implemented)
- `GET /files/{storage_path}?expires=<unix_ts>&signature=<hmac>` — serves the original file bytes with the document's real `mime_type`. Deliberately **not** behind the `Authorization: Bearer` check every other route requires — the signature and its expiry are themselves the authorization, so the URL returned as `file_url` above can be dropped straight into a reviewer's browser or an `<img>`/`<iframe>` src. `403` if the signature doesn't match or has expired; `404` if no document has that storage path. See `docs/security.md`, "Unauthorized document access," and `app/storage.py`.

### Phase 11 — Approval Workflow (implemented)
- `GET /approvals` — `VALIDATED` documents whose total is at or above `APPROVAL_THRESHOLD_AMOUNT` and that don't yet have an `approvals` row, oldest first, each with the reason approval is required. A document under the threshold never appears here — it needs no sign-off.
- `POST /approvals/{id}/approve` — body: `{"approver": "<free-text identity>"}`. Requires `state == VALIDATED`, the document to actually meet the threshold, and no existing `approvals` row (`409` otherwise on any of the three). Writes an `approvals` row (`amount`, `threshold_applied`, `approver`, `decision: APPROVED`). **Does not change `document.state`** — the document stays `VALIDATED`; the `approvals` row itself is the signal a later worker (Phase 12/13) checks before writing to accounting. See `docs/state-machine.md`.
- `POST /approvals/{id}/reject` — body: `{"approver": "...", "reason": "..."}`. Same preconditions as approve. Writes an `approvals` row (`decision: REJECTED`) and moves the document `VALIDATED → REJECTED` — a new transition documented in `docs/state-machine.md` alongside Phase 10's `NEEDS_REVIEW → REJECTED`. The approver and reason are recorded in the `state_history` row's `reason` text, same pattern as Phase 10's review rejection (see `docs/adr/0008-api-authentication.md` on why `approver` is a free-text field, not an authenticated identity, at this stage).

Not implemented: the smaller "missing a PO" approval floor `docs/workflow.md` mentions — no purchase-order field exists anywhere in the extraction schema, so there's nothing to check it against (see `app/approval.py`).

`ApprovalQueueItemOut`/`ApprovalDecisionIn`/`ApprovalRejectionIn`/`ApprovalActionOut` shapes: see `app/schemas.py`.

### Phase 12 — Downstream Accounting Action (implemented)
- `POST /documents/{id}/action` — the only endpoint this phase adds. Requires `state == VALIDATED` and, if the document is at or above the approval threshold, an existing `approvals` row (`409` "awaiting approval..." otherwise). Writes an `accounting_actions` row `ATTEMPTED` before the write (idempotency-first, per `docs/reliability.md` scenario 3), creates the actual payable record in the mock `ap_ledger_entries` table (`app/accounting.py`'s `MockAccountingProvider`), marks the `accounting_actions` row `CONFIRMED`, and moves the document `VALIDATED → ACTIONED → COMPLETED`. Best-effort logs a notification (`LogNotificationProvider`) — a notification failure never blocks or unwinds the write; `notification_sent: false` in the response is the only sign it happened. A repeated call after `COMPLETED` returns the existing result rather than writing a second ledger entry (`accounting_actions.document_id` is unique). If the accounting write itself fails, the document moves to `FAILED` and the endpoint returns `502`.

No worker exists yet to call this automatically — see `docs/adr/0003-worker-model.md`; Phase 13 adds the scheduled worker that would invoke the same underlying logic without a person calling the endpoint by hand. A document stuck `ACTIONED` from a crash between the `ATTEMPTED` and `CONFIRMED` writes is *not* auto-resumed by this endpoint (it just 409s as "not VALIDATED") — resuming that specific case is explicitly Phase 13's job.

`DocumentActionOut`/`AccountingActionOut` shapes: see `app/schemas.py`.

### Phase 16 — Observability
- `GET /dashboard` — the metrics summary (straight-through rate, review rate, average processing time, etc. — see `docs/cost-strategy.md` for which are measured vs. estimated).

## Explicitly not planned

- No endpoint to trigger a payment or any downstream financial transfer — the system creates a record and marks it ready; it never executes a payment (see `docs/problem.md`).
- No bulk/batch upload endpoint for MVP — one document per request is sufficient to demonstrate the workflow and keeps validation/idempotency logic simpler.
- No public/unauthenticated read access to any endpoint, even in a demo deployment — see `docs/security.md`.

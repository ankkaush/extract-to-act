# Data model

PostgreSQL is used because this system needs both strict relational integrity (state transitions, audit trail, financial totals — places where a wrong answer is a real risk) and flexible storage for raw provider output that differs by provider. `JSONB` gives the second without sacrificing the first. See `docs/adr/0002-database.md`.

This document describes entities and relationships at a high level. Exact columns, types, and indexes are finalized as SQLAlchemy models in Phase 3 — this is the blueprint that phase implements, not a substitute for it.

## Entities

| Entity | Purpose |
|---|---|
| `documents` | One row per uploaded file: storage reference, content hash, current state, idempotency key, worker retry count (Phase 13) |
| `extraction_results` | Per-document extraction output: normalized header fields (value/confidence/page/bbox), raw provider payload (`JSONB`), provider name + model version |
| `invoice_line_items` | Line-item rows tied to an extraction result: description, quantity, unit price, line total, confidence |
| `vendors` | Known-vendor table: name, normalized name, tax ID — used for deterministic fuzzy matching (Phase 8) |
| `validation_results` | Outcome of each deterministic rule run against a document: pass/fail, rule name, human-readable reason |
| `review_events` | Correction audit trail: original value, corrected value, reviewer, timestamp, per field |
| `approvals` | Approval/rejection decisions: amount, threshold applied, approver, timestamp |
| `state_history` | Append-only log of every state transition per document — backbone of both audit and crash recovery |
| `accounting_actions` | Idempotency ledger for downstream writes: attempted/confirmed status, external record reference |
| `ap_ledger_entries` | The mock AP ledger itself (Phase 12) — the payable record a confirmed write actually produced, distinct from the idempotency ledger above |

## Relationships

- One `document` has at most one `extraction_results` row (re-extraction, if ever needed, creates a new row rather than overwriting).
- One `extraction_results` row has many `invoice_line_items`.
- One `document` has many `validation_results`, `review_events`, and `state_history` rows (one per rule run / correction / transition).
- One `document` has at most one `approvals` row, at most one `accounting_actions` row, and at most one `ap_ledger_entries` row.
- `extraction_results.vendor_field` is matched against `vendors` at validation time (Phase 8); no foreign key is enforced at extraction time since a document may reference an unmatched/unknown vendor.

## Design notes

- `state_history` is append-only by design — never updated or deleted — because it doubles as both the audit trail and the crash-recovery mechanism (`docs/state-machine.md`).
- `accounting_actions` exists as a distinct table (not just a status column on `documents`) specifically to support the idempotency pattern in `docs/reliability.md`: recording "attempted" before a downstream write, and checking before ever retrying one.
- Indexes anticipated for Phase 3: `documents.content_hash` and `documents.idempotency_key` (duplicate/replay detection), `extraction_results` invoice-number and vendor fields (duplicate and vendor matching queries).
- Business/technical metrics (`docs/cost-strategy.md`, Phase 16) are computed from these tables via views or aggregation queries — no separate metrics-writing system, since there's no volume here that justifies a dedicated time-series store.

# PLAN.md — Extract to Act

Phase-level roadmap. One phase = one coherent engineering/learning concept. Phases are not reordered, merged, or split without a concrete implementation contradiction — see the note at the bottom.

**Legend:** ✅ done · 🔵 in progress · ⚪ not started

## Phase 1 — Documentation & Architecture Blueprint ✅

**Goal:** produce the full written blueprint (this file plus everything in `docs/`) before any application code exists.
**Depends on:** the discovery/architecture/review work that preceded this repository.
**Completion criteria:** every document below exists, is internally consistent, and is approved by the project owner. **Met — approved.**

## Phase 2 — Project Foundation & Tooling ✅

Empty FastAPI app, Docker + Compose, config/secrets loading, CI with lint + unit tests, pre-commit secret scanning. No business logic.
**Depends on:** Phase 1's ADRs for framework/DB/Docker.
**Built:** `app/main.py` (health check only, at the time), `app/config.py` (env-based settings), `Dockerfile` + `docker-compose.yml`, `pyproject.toml`, `.pre-commit-config.yaml` (ruff + gitleaks), `.github/workflows/ci.yml` (lint, Tier 1/2 tests, secret scan), `tests/test_health.py`.
**Completion criteria:** met.

## Phase 3 — Data Model & Persistence ✅

All core tables as SQLAlchemy models with Alembic migrations, full state-machine enum. No business logic reads/writes yet.
**Depends on:** Phase 2's working Postgres connection.
**Built:** `app/models.py` (9 tables, `DocumentState`/`ApprovalDecision`/`AccountingActionStatus` enums), `app/db.py` (engine/session, unused by any route yet), Alembic wired to `app.config`'s `DATABASE_URL` (no connection string in a committed file), initial migration `alembic/versions/e10b7a83d06f_initial_schema.py`, `docs/adr/0007-database-access.md` (sync SQLAlchemy decision), `tests/test_models.py` + `tests/conftest.py`.
**Verified, not assumed:** migration applies cleanly (`alembic upgrade head` creates all 9 tables); a full downgrade→upgrade round-trip succeeds (this surfaced and fixed a real bug — Postgres ENUM types aren't dropped by `drop_table`, so downgrade now drops them explicitly); FK/uniqueness constraints tested against a live Postgres (idempotency key uniqueness, `state_history` rejecting an orphaned `document_id`); `docker compose up` → migrate → `/health` all pass end to end from a clean volume.
**Completion criteria:** met.

## Phase 4 — Document Ingestion & Storage ✅

Authenticated upload endpoint: file validation, storage, `RECEIVED` state, request-level idempotency. No extraction provider involved.
**Depends on:** Phase 3's `documents` table.
**Built:** `app/storage.py` (`StorageProvider` interface + `LocalStorageProvider`; `sign_url` stubbed until Phase 10 needs it), `app/ingestion.py` (content-sniffed file-type check, size limit, SHA-256 hashing — no filename/Content-Type trust), `app/auth.py` (shared bearer token, `docs/adr/0008-api-authentication.md`), `app/routers/documents.py` (`POST/GET /documents`, `GET /documents/{id}`), `app/schemas.py`.
**Verified, not assumed:** 22 tests pass (unit: file-type sniffing rejects content that only *claims* to be a PDF by filename; integration: real Postgres + temp-dir storage via dependency overrides, with a SAVEPOINT-based test transaction so the router's own `session.commit()` never leaks into the database). Also verified against the real running container over plain HTTP: unauthenticated upload → `401`; valid upload → `201` with a `RECEIVED` row and a matching `state_history` entry; a second request with the same `Idempotency-Key` → same document `id`, not a duplicate; non-PDF content → `415`; the file actually lands in the container's local storage directory.
**Completion criteria:** met.

## Phase 5 — Extraction Provider Evaluation (Spike) ✅

Run 18 representative synthetic invoices through a real extraction provider, evaluated against authoritative ground truth, with business-critical fields (invoice number, invoice date, due date, currency, subtotal, tax, total) reported separately from the aggregate score. Produces a written, evidence-based provider decision.
**Depends on:** nothing from Phases 2–4 — ran in parallel with them.

**Built:** the full harness (`spike/schema.py`, `spike/providers/{azure,mistral,claude}_provider.py`, `spike/pricing.py`, `spike/run_spike.py`, `spike/evaluate.py`, `spike/README.md`), the approved 18-document synthetic dataset with ground truth generated first and authoritative by construction (`spike/invoice_specs.py`, `spike/render.py`, `spike/formatting.py`, `spike/degrade.py`, `spike/generate_samples.py`), and a full test suite (`spike/test_{formatting,providers,evaluate,dataset_integrity,run_spike,provider_readiness}.py` — 68 tests without `[spike]` installed, 75 with it). Two currency-rounding/layout bugs were caught by actually rendering and inspecting output, not just confirming generation succeeded. Two real Mistral SDK bugs (wrong import path, wrong JSON-schema field name) were caught by static package introspection before spending anything, and are now permanently guarded by `spike/test_provider_readiness.py`.

**Real run: Mistral OCR only, once, against all 18 documents.** Not a Mistral-vs-Claude comparison as originally planned — Azure was excluded from the start (project owner scope decision, optional not required), and Claude was excluded from the real run because the Anthropic credential in this environment was exposed during diagnosis and is treated as compromised; no call was made with it. Result: 18/18 processed (one transient `404` on `inv_04`, resolved with a single targeted retry of that one document, not a full rerun), **98% overall field accuracy, 98% business-critical-field accuracy**, $0.076 total cost. Three named critical-field errors (currency on the deliberately-ambiguous `inv_11`; a hallucinated due-date and a transposed invoice-date, both on `inv_13`) and one empirically-confirmed limitation (Mistral's structured-output call returns no per-field confidence at all) are recorded with full detail in `docs/extraction-strategy.md`, "Real results," and `spike/report.md`.

**Decision:** Mistral OCR is the Phase 6 `ExtractionProvider` — see `docs/adr/0006-extraction-provider.md` for the decision, its evidence, and its explicitly-stated confidence caveat (single-provider validation, not comparative). The confidence-score gap changes Phase 6/7's review-routing design: it must route via deterministic validation failures and targeted plausibility checks, not a per-field confidence threshold table, for this provider.

**Two credential-exposure incidents occurred during diagnosis before this final run** (an `env | grep` matching a variable name and printing its value; a raw SDK exception traceback echoing a credential embedded in a malformed header). Both keys were rotated by the project owner as a result. `docs/security.md` gained a "Secret-safe debugging practice" section recording exactly what went wrong and the rules it produced, so this isn't repeated in later phases.

**Completion criteria:** met.

## Phase 6 — Extraction Integration & Normalization ✅

Wire the chosen provider(s) behind an `ExtractionProvider` interface; map raw responses into the normalized field/confidence/provenance schema.
**Depends on:** Phase 4's ingestion pipeline; Phase 5's provider decision.
**Built:** `app/extraction.py` — the `ExtractionProvider` Protocol, `ExtractedField`/`ExtractedLineItem`/`ExtractionOutput` dataclasses, `MistralExtractionProvider` (the real integration, using the exact import path and `schema_definition` field name the Phase 5 spike verified — deliberately duplicated rather than imported from `spike/`, which stays a throwaway evaluation package), and `build_extraction_result()` (pure normalization into `ExtractionResult`/`InvoiceLineItem` rows). `app/routers/documents.py` now runs extraction synchronously as part of `POST /documents` (`RECEIVED` → `EXTRACTING` → `EXTRACTED`, or → `FAILED` on any exception, with a redacted reason recorded) — synchronous because no background worker exists yet (Phase 13), a deliberate scope decision, not an oversight. New `GET /documents/{id}/extraction` endpoint. `mistralai` moved from the spike-only dependency group to a real core dependency.
**Verified, not assumed:** 8 new/updated tests in `tests/test_documents_api.py` (upload → `EXTRACTED` with correct state-history sequence; extraction failure → `FAILED`; `GET .../extraction` returns normalized fields with provenance; `404` when extraction failed) plus 6 pure-logic tests in `tests/test_extraction.py` (number/date coercion, including the exact "unparseable date must not crash, must return `None`" case the real Phase 5 run surfaced) — all using a `FakeExtractionProvider` dependency override, never a real network call. A real bug was caught by actually running the suite, not assumed away: the default test fixture initially passed the fake provider *class* instead of a zero-arg factory to `dependency_overrides`, which made FastAPI try to treat the class's `output`/`error` constructor parameters as HTTP request parameters and fail with a Pydantic schema error on `Exception | None` — fixed before commit. Docker image rebuilt and confirmed to still build and serve `/health` correctly with the new dependency; the real upload endpoint was deliberately **not** exercised against the live Mistral key during verification, to avoid an unauthorized real API call outside Phase 5's already-completed spike.
**Completion criteria:** met — an uploaded document reaches `EXTRACTED` with normalized, provenance-tagged fields in the database, using only a fake provider in tests.

## Phase 7 — Deterministic Validation ✅

Required-field checks and arithmetic consistency, independent of confidence.
**Depends on:** Phase 6's normalized fields.
**Built:** `app/validation.py` — `check_required_fields()` (one rule per field: vendor_name, invoice_number, invoice_date, currency, subtotal, tax, total; `due_date` deliberately excluded — the real Phase 5 run confirmed a missing due date is a legitimate value, not an extraction failure) and `check_arithmetic_consistency()` (subtotal + tax = total within a $0.02 tolerance, with its own distinct reason when a component is missing entirely vs. when the numbers just don't add up). Wired into `app/routers/documents.py`: `EXTRACTED` → `VALIDATING` → `VALIDATED` (all rules passed) or `NEEDS_REVIEW` (any failed) — synchronous, same request, same reasoning as Phase 6 (no worker until Phase 13). Every rule's individual result is persisted to `validation_results`, not just a summary reason on `state_history`.
**Verified, not assumed:** 10 pure-logic tests in `tests/test_validation.py` — every rule has both a passing and a failing case with a specific reason string, including the exact adversarial cases PLAN.md named up front (a total off by one cent beyond tolerance, a missing invoice number), plus multi-failure and missing-component cases. 6 new/updated integration tests in `tests/test_documents_api.py` confirm the wiring end to end: a valid upload reaches `VALIDATED` with the correct 5-state history sequence; a missing required field or an arithmetic mismatch reaches `NEEDS_REVIEW` with the specific `validation_results` row to prove it; a missing `due_date` alone does *not* trigger review. 90 tests pass total (97 with `[spike]` installed). Docker image rebuilt and confirmed to build, migrate, and serve `/health` correctly.
**Completion criteria:** met — every rule has a passing and a failing test case with a correct, specific reason string.

## Phase 8 — Vendor Matching ✅

Deterministic fuzzy matching of extracted vendor names against a known-vendor table.
**Depends on:** Phase 6's normalized vendor field.
**Built:** `app/vendor_matching.py` — `normalize_vendor_name()` (lowercase, strip punctuation, matching the `Vendor.normalized_name` column's own convention), `find_best_match()` (pure function over plain `(id, name)` tuples, not ORM objects, so it's fully Tier-1 testable — uses `rapidfuzz`'s similarity scoring, threshold 85/100), and `check_vendor_known()` (wraps a match into the same `RuleResult` shape Phase 7's rules use). `app/seed_vendors.py` seeds 18 realistic vendor names mirroring the Phase 5 spike dataset (copied as plain strings, never imported from `spike/` — the app must never depend on the throwaway evaluation package), idempotent, run manually via `python -m app.seed_vendors` (not on every app startup, same reasoning as manual migrations). Wired into `app/routers/documents.py`'s existing `_run_validation_step` — vendor matching is folded into the same `VALIDATING` step as Phase 7's rules and feeds the same `VALIDATED`/`NEEDS_REVIEW` decision, since `docs/workflow.md` lists it as a conceptual step but the state machine has no dedicated "matching" state.
**Verified, not assumed:** 10 pure-logic tests in `tests/test_vendor_matching.py` (exact match, near-miss spelling still matches, genuinely unknown vendor correctly flagged, no-vendors-on-file, missing-name — per PLAN.md's stated completion criteria). 2 new integration tests confirm the wiring: an unrecognized vendor reaches `NEEDS_REVIEW` with a named `vendor:known` validation_results row; a cosmetic spelling variation ("Acme Corp." vs. "Acme Corp") still reaches `VALIDATED`. All existing Phase 6/7 happy-path tests updated to seed a matching vendor first, since a document's vendor now has to actually be recognized to sail through untouched — this is more realistic than before, not a workaround. 102 tests pass. Docker image rebuilt; the seed script was run twice against a real Postgres to confirm both that it works and that it's genuinely idempotent (18 inserted, then 0 inserted / 18 already present).
**Completion criteria:** met — a known vendor with a typo still matches; a genuinely new vendor is correctly flagged, not silently created.

## Phase 9 — Duplicate Detection ⚪

Content-hash and fuzzy matching to catch the same invoice arriving through a different request.
**Depends on:** Phase 7's validated fields; Phase 4's file hashing.

## Phase 10 — Human Review Workflow ⚪

Review queue, side-by-side document/field UI, correction capture as an audit event.
**Depends on:** Phases 7–9 (all review triggers must exist).

## Phase 11 — Approval Workflow ⚪

Threshold-based approval routing, separate from data-quality review.
**Depends on:** Phase 10's `VALIDATED` state.

## Phase 12 — Downstream Accounting Action ⚪

Mock AP ledger behind an `AccountingProvider` interface, idempotent writes, notification.
**Depends on:** Phase 11's approval decision.

## Phase 13 — Reliability & Recovery ⚪

Retry/backoff, dead-letter handling, crash/restart recovery for every failure mode in `docs/reliability.md`.
**Depends on:** all prior phases.

## Phase 14 — Security Hardening ⚪

Implements and verifies every control in `docs/security.md`.
**Depends on:** Phases 4, 6, 10, 11.

## Phase 15 — System-Level Testing ⚪

Opt-in end-to-end tests against a real provider; basic chaos/failure-injection testing.
**Depends on:** all feature phases (4–14).

## Phase 16 — Observability & Business Metrics ⚪

Dashboard of measured metrics, with any estimate explicitly labeled as an estimate.
**Depends on:** Phase 13's `state_history` being populated.

## Phase 17 — Deployment ⚪

Render deployment from the Docker image, production secrets, smoke test.
**Depends on:** Phase 2's Docker setup; feature-complete application.

## Phase 18 — Documentation & Demo Preparation ⚪

Finalize README, architecture diagram, demo script for a portfolio audience.
**Depends on:** Phase 17's live deployment.

## Phase 19 — Stretch Extensions ⚪

Real Xero/QuickBooks sandbox adapter, email ingestion, hybrid multi-provider extraction (only if Phase 5's data justifies it). Not committed to a date.
**Depends on:** a complete, working core system (Phases 1–18).

---

## On changing this structure

This 19-phase structure was deliberately designed around concept boundaries, not an arbitrary count, and has been approved. It should not be redesigned, merged, split, or reordered mid-project on aesthetic grounds. The one legitimate reason to revise it: a concrete implementation contradiction is discovered — e.g. two "separate" phases turn out to be impossible to build independently, or a phase turns out to secretly contain two unrelated concepts. If that happens, the specific contradiction should be stated plainly before any structural change is made.

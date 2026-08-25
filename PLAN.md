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

## Phase 6 — Extraction Integration & Normalization ⚪

Wire the chosen provider(s) behind an `ExtractionProvider` interface; map raw responses into the normalized field/confidence/provenance schema.
**Depends on:** Phase 4's ingestion pipeline; Phase 5's provider decision.

## Phase 7 — Deterministic Validation ⚪

Required-field checks and arithmetic consistency, independent of confidence.
**Depends on:** Phase 6's normalized fields.

## Phase 8 — Vendor Matching ⚪

Deterministic fuzzy matching of extracted vendor names against a known-vendor table.
**Depends on:** Phase 6's normalized vendor field.

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

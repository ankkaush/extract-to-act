# Extract to Act

An AI-assisted invoice-to-accounts-payable automation system: it takes an arbitrary invoice document, turns it into a structured record it can actually trust, and carries that record through a real business decision — validate, route to a human when warranted, approve, and post to a downstream ledger — with every step auditable and recoverable.

## Why this exists

Invoice processing is a mature automation domain — deterministic three-way matching already handles the majority of invoice volume in well-run AP departments without any AI involved. This project isn't trying to reinvent that. It's a deliberate demonstration of the part that's still genuinely hard: knowing when an AI extraction is trustworthy, what to do when it isn't, and never letting a probabilistic step make a deterministic financial decision on its own.

See [`docs/problem.md`](docs/problem.md) for the full business-problem writeup, including why this framing was chosen over alternatives like receipts, purchase orders, or claims.

## Status

**Project complete.** The core system is fully implemented, tested, documented, and deployment-ready. Production deployment is deliberately deferred (see below) — the application has not been deployed to Render, and this README makes no claim that it has.

| | |
|---|---|
| Ingestion → extraction → validation | ✅ Complete — content-sniffed upload, Mistral OCR, arithmetic + required-field checks, all synchronous in one request |
| Vendor matching & duplicate detection | ✅ Complete — deterministic fuzzy matching; exact-hash and content-level duplicate detection, before any wasted extraction spend |
| Human review & approval | ✅ Complete — review queue with per-rule failure reasons, correction audit trail, threshold-based approval routing |
| Downstream action & idempotency | ✅ Complete — mock AP ledger write, attempted-before-write idempotency, never double-posted |
| Reliability | ✅ Complete — bounded retry-with-backoff on every external call; a worker that resumes a document stuck mid-crash from exactly where it stopped |
| Security | ✅ Complete — every control in `docs/security.md` implemented and verified — see below |
| Real-provider proof | ✅ Complete — two opt-in tests against the live Mistral API, including a genuine authentication failure proving the dead-letter path holds for real |
| Observability | ✅ Complete — `GET /dashboard`, every rate genuinely measured from timestamps, exactly one number labeled and computed as an estimate |
| Documentation & demo prep | ✅ Complete — portfolio-oriented README, GitHub-renderable architecture diagram, guided demo script |
| Deployment infrastructure & docs | ✅ Complete — Render Blueprint and full deployment walkthrough, verified locally |
| Live production deployment | ⏸️ Deliberately deferred, not part of this completed scope — see below |

Nothing here looks at AI confidence to make a financial decision — see [`app/validation.py`](app/validation.py), [`app/vendor_matching.py`](app/vendor_matching.py), [`app/duplicate_detection.py`](app/duplicate_detection.py), and the rest of `app/`. Full phase-by-phase build log, what was verified and how, and every real bug found along the way: [`PLAN.md`](PLAN.md).

**On deployment:** deployment *infrastructure* is complete, not merely started — `render.yaml` and `docs/deployment.md` have everything needed to deploy: a reviewed Blueprint, the exact secrets to set and why, migration-on-deploy verified locally against the real built image (including Render's dynamic port binding), and honest documentation of what doesn't carry over yet (no continuously-running worker, uploaded files don't persist across restarts without a paid disk). What's deferred is only the act of actually deploying it: a prior, separate project ran into a real Render issue, so this one is intentionally holding off on redeploying until that's understood, rather than burn through free-tier deploy attempts testing it. **The application has not been deployed anywhere** — there is no live URL yet, and none is implied.

**Out of scope for this completed project:** Phase 19 is a stretch-extension backlog (a real Xero/QuickBooks sandbox adapter, email ingestion, hybrid multi-provider extraction) — optional future work, not unfinished core functionality. See `PLAN.md`'s Phase 19 entry.

## Try it

A ~10-minute walkthrough against the real system (local, real Mistral calls, no mocking): [`docs/demo-script.md`](docs/demo-script.md).

## How the system works, briefly

An invoice arrives, gets read and structured, and is checked deterministically — does the math add up, have we seen this invoice before, do we recognize this vendor. If everything checks out with high confidence, it moves forward untouched. If anything is uncertain, it's queued for a person to review, side by side with the original document. Once validated and (if needed) approved, it becomes a real record in a downstream accounting system, with a full audit trail behind it.

Full plain-English workflow: [`docs/workflow.md`](docs/workflow.md). System diagram: [`docs/architecture.md`](docs/architecture.md).

## Documentation map

| Document | Answers |
|---|---|
| [`docs/problem.md`](docs/problem.md) | What business problem is this, and why this use case |
| [`docs/workflow.md`](docs/workflow.md) | The end-to-end process in plain English |
| [`docs/architecture.md`](docs/architecture.md) | Components, boundaries, how they interact |
| [`docs/adr/`](docs/adr/) | Why each consequential technology/architecture decision was made |
| [`docs/data-model.md`](docs/data-model.md) | Entities, relationships, why each table exists |
| [`docs/state-machine.md`](docs/state-machine.md) | Every document state, transition, and crash-recovery behavior |
| [`docs/api.md`](docs/api.md) | The full API surface, by owning phase |
| [`docs/extraction-strategy.md`](docs/extraction-strategy.md) | How the extraction-provider decision was made and validated |
| [`docs/security.md`](docs/security.md) | Threats considered and the control for each |
| [`docs/reliability.md`](docs/reliability.md) | Failure modes and how each is handled |
| [`docs/testing-strategy.md`](docs/testing-strategy.md) | The four test tiers, and when a real paid API call is ever allowed |
| [`docs/cost-strategy.md`](docs/cost-strategy.md) | Where money can be spent and how it's kept near zero |
| [`docs/deployment.md`](docs/deployment.md) | How and where this runs, and its current (deferred) deployment status |
| [`docs/demo-script.md`](docs/demo-script.md) | A guided walkthrough of the running system |

## Tech stack

Python, FastAPI, PostgreSQL, SQLAlchemy + Alembic, Docker, a polling worker (no message queue), Render as the deployment target (Blueprint prepared, not yet live). Reasoning for each in [`docs/adr/`](docs/adr/). Extraction provider: Mistral OCR — see [`docs/adr/0006-extraction-provider.md`](docs/adr/0006-extraction-provider.md).

## Local setup

```bash
cp .env.example .env
docker compose up --build -d
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.seed_vendors
```

The app is then available at `http://localhost:8000`. Uploading a document (auth required — the unmodified `.env.example` uses the insecure dev-only default key, `dev-only-not-for-production`; see `docs/adr/0008-api-authentication.md`):

```bash
curl -X POST http://localhost:8000/documents \
  -H "Authorization: Bearer dev-only-not-for-production" \
  -F "file=@some-invoice.pdf"
```

Only PDF/PNG/JPEG/TIFF content is accepted (checked by file content, not extension), up to `MAX_UPLOAD_SIZE_BYTES`. **This call hits the real Mistral API** if `MISTRAL_API_KEY` is set in `.env` — extraction, deterministic validation, and vendor matching all run synchronously as part of the upload (see `docs/api.md`), so the response only comes back once the document is fully `VALIDATED` or `NEEDS_REVIEW` (or `FAILED`, if extraction itself failed). A vendor not in the seeded list (`python -m app.seed_vendors`) routes to `NEEDS_REVIEW`, same as a missing field. See `PLAN.md` for what's built so far.

## Data handling

Every document this project has ever processed — in the Phase 5 provider evaluation and in every test fixture — is synthetic or clearly fabricated, never a real vendor's real invoice (see `docs/security.md`). That matters for what follows.

This project's Mistral usage is on the free/experiment API tier (see `docs/testing-strategy.md`'s cost breakdown — the Phase 5 spike ran on free tiers by design). Per [Mistral's own documentation](https://help.mistral.ai/en/articles/156194-does-mistral-ai-exploit-users-data-to-train-its-models) and [terms](https://legal.mistral.ai/terms/data-processing-addendum), free/experiment-tier API usage **can be used for model training by default**, unlike paid API plans (which exclude training by default, with a 30-day abuse-monitoring retention window). Anyone extending this project to process real invoice data should switch to a paid Mistral plan (or opt out in the Admin Console's Privacy settings) first — this repository never has, because every document it touches is synthetic and there is nothing sensitive at stake in it being used for training.

### Running tests / lint without Docker

```bash
pip install -e ".[dev]"
pytest        # Tier 1 + Tier 2 only, no real API calls — see docs/testing-strategy.md
ruff check .
```

Tier 4 (`tests/test_e2e_real_provider.py`) hits the real Mistral API and is excluded by default. Run it deliberately, rarely, and only with a real `MISTRAL_API_KEY` set: `pytest -m real_api tests/test_e2e_real_provider.py`.

### Pre-commit hooks (lint + secret scanning)

```bash
pre-commit install
```

## Secrets

This is a public repository. No credentials of any kind are ever committed. See [`.env.example`](.env.example) for the full list of configuration variables the application will eventually need, and [`docs/security.md`](docs/security.md) for the full repository-safety approach.

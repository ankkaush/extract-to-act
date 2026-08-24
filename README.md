# Extract to Act

An AI-assisted invoice-to-accounts-payable automation system: it takes an arbitrary invoice document, turns it into a structured record it can actually trust, and carries that record through a real business decision — validate, route to a human when warranted, approve, and post to a downstream ledger — with every step auditable and recoverable.

## Why this exists

Invoice processing is a mature automation domain — deterministic three-way matching already handles the majority of invoice volume in well-run AP departments without any AI involved. This project isn't trying to reinvent that. It's a deliberate demonstration of the part that's still genuinely hard: knowing when an AI extraction is trustworthy, what to do when it isn't, and never letting a probabilistic step make a deterministic financial decision on its own.

See [`docs/problem.md`](docs/problem.md) for the full business-problem writeup, including why this framing was chosen over alternatives like receipts, purchase orders, or claims.

## Status

**Phase 3 of 19 — Data Model & Persistence — complete.** The full schema (9 tables) exists as SQLAlchemy models with an applied Alembic migration; no application code reads or writes them yet. See [`PLAN.md`](PLAN.md) for the full phase roadmap and current progress.

## How the system works, briefly

An invoice arrives, gets read and structured, and is checked deterministically — does the math add up, have we seen this invoice before, do we recognize this vendor. If everything checks out with high confidence, it moves forward untouched. If anything is uncertain, it's queued for a person to review, side by side with the original document. Once validated and (if needed) approved, it becomes a real record in a downstream accounting system, with a full audit trail behind it.

Full plain-English workflow: [`docs/workflow.md`](docs/workflow.md).

## Documentation map

| Document | Answers |
|---|---|
| [`docs/problem.md`](docs/problem.md) | What business problem is this, and why this use case |
| [`docs/workflow.md`](docs/workflow.md) | The end-to-end process in plain English |
| [`docs/architecture.md`](docs/architecture.md) | Components, boundaries, how they interact |
| [`docs/adr/`](docs/adr/) | Why each consequential technology/architecture decision was made |
| [`docs/data-model.md`](docs/data-model.md) | Entities, relationships, why each table exists |
| [`docs/state-machine.md`](docs/state-machine.md) | Every document state, transition, and crash-recovery behavior |
| [`docs/api.md`](docs/api.md) | The eventual API surface |
| [`docs/extraction-strategy.md`](docs/extraction-strategy.md) | How the extraction-provider decision will be made and validated |
| [`docs/security.md`](docs/security.md) | Threats considered and the control for each |
| [`docs/reliability.md`](docs/reliability.md) | Failure modes and how each is handled |
| [`docs/testing-strategy.md`](docs/testing-strategy.md) | The four test tiers, and when a real paid API call is ever allowed |
| [`docs/cost-strategy.md`](docs/cost-strategy.md) | Where money can be spent and how it's kept near zero |
| [`docs/deployment.md`](docs/deployment.md) | How and where this runs |

## Tech stack (planned)

Python, FastAPI, PostgreSQL, SQLAlchemy + Alembic, Docker, a scheduled polling worker (no message queue), deployed on Render. Reasoning for each in [`docs/adr/`](docs/adr/). The extraction provider is intentionally undecided — see [`docs/extraction-strategy.md`](docs/extraction-strategy.md).

## Local setup

```bash
cp .env.example .env
docker compose up --build -d
docker compose run --rm app alembic upgrade head
```

The app is then available at `http://localhost:8000/health`. The database schema now exists (9 tables — see `docs/data-model.md`), but no route reads or writes it yet — see `PLAN.md`.

### Running tests / lint without Docker

```bash
pip install -e ".[dev]"
pytest        # Tier 1 + Tier 2 only, no real API calls — see docs/testing-strategy.md
ruff check .
```

### Pre-commit hooks (lint + secret scanning)

```bash
pre-commit install
```

## Secrets

This is a public repository. No credentials of any kind are ever committed. See [`.env.example`](.env.example) for the full list of configuration variables the application will eventually need, and [`docs/security.md`](docs/security.md) for the full repository-safety approach.

# Testing strategy

The guiding constraint: be thoroughly tested without burning meaningful API credits. The mechanism that makes this possible is the adapter boundary in `docs/architecture.md` — the same interface that lets a provider be swapped lets it be faked.

## The four tiers

| Tier | What it covers | Providers involved | When it runs |
|---|---|---|---|
| 1 — Unit | Deterministic validation, state transitions, matching, dedupe logic | None | Every save, every push — free, near-instant |
| 2 — Fixture / mocked | Full pipeline shape using recorded real provider responses replayed from disk | None (replayed) | CI, every push — free |
| 3 — Small real-provider evaluation | The Phase 5 spike itself; occasional threshold re-calibration | Real, budgeted | Manual, rare, logged |
| 4 — End-to-end | Full pipeline against a live provider; basic chaos/failure injection | Real | Manual only, opt-in via `@pytest.mark.real_api`, excluded from CI by default, run before a milestone/demo |

## The fixture mechanism

Real provider responses are recorded once (a "cassette," in the same sense the `vcrpy` library uses the term — a saved real HTTP exchange replayed on later runs) and checked into the repo as sanitized JSON fixtures. This is what lets Tier 2 exercise the full pipeline realistically — including confidence handling and review-trigger logic — without a network call on every test run. Without this mechanism, tests would either use imagined mock data (risking a mismatch with what a provider actually returns) or a real API call every run (slow, costly, flaky).

## Rules for when a real API call is allowed

- Never in a default `pytest` run or in CI's default job.
- Only in the Phase 5 spike, in occasional threshold recalibration, or in explicitly-marked Tier 4 tests run manually.
- A test that would consume API credits without teaching something a fixture-based test can't is not written.

## Estimated real API usage across the whole project

| Category | Volume | Cost |
|---|---|---|
| Phase 5 spike (Azure + Mistral, free tiers) | ~15–20 documents each | $0 |
| Phase 5 spike (Claude) | ~15–20 documents | ~$0.10–0.20 |
| Occasional threshold recalibration | ~20–40 calls, mixed providers | Mostly free, a few cents where Claude is involved |
| Opt-in Tier 4 runs before milestones | ~6–8 runs × ~10–15 calls | ~$0.50–1.50 total |
| **Total, whole project** | **~150–250 real calls** | **Under $2–3** |

Full breakdown and reasoning in `docs/cost-strategy.md`.

## Adversarial fixtures, deliberately included

Tier 1/2 fixtures deliberately include: a total off by one cent, a missing required field, a near-duplicate vendor spelling, an exact-hash duplicate, two genuinely different invoices from the same vendor on the same day (must *not* be flagged as duplicate), and — for Phase 14 — a document containing adversarial text aimed at an extraction/normalization step (a basic prompt-injection test case).

## Where this is implemented

Test tiers are introduced starting Phase 2 (CI skeleton) and used by every subsequent phase per its own testing scope in `PLAN.md`. Phase 15 is the one phase whose entire purpose is Tier 4 testing and basic chaos/failure-injection at the system level, rather than any single feature.

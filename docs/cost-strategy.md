# Cost strategy

## Principle

The architecture barely changes to control cost — the provider-adapter boundary that enables swapping a provider also enables faking one. What actually changes is the shape of the test suite (`docs/testing-strategy.md`) and the sequencing of when a provider is first touched (`PLAN.md` Phase 4 deliberately involves no provider at all).

## Where money can actually be spent

| Category | Source | Controlled by |
|---|---|---|
| Extraction API calls | Azure / Mistral / Claude, per document | Fixture replay for all routine testing; real calls limited to Phase 5, occasional recalibration, and opt-in Tier 4 runs |
| LLM semantic-assist calls (if used) | Claude, per call | Haiku by default for low-stakes normalization; Sonnet only where genuine reasoning is needed |
| Hosting | Render web service + managed Postgres | Free tier by default; a $7/mo Starter instance only if cold-start latency becomes a real problem (`docs/adr/0005-deployment-platform.md`) |
| Object storage | S3-compatible (Cloudflare R2 / Backblaze B2) | Both have genuine free tiers at this project's expected volume |

## Extraction provider free tiers (the biggest lever)

| Provider | Free tier | Card required |
|---|---|---|
| Azure Document Intelligence | 500 pages/month, **ongoing** | No |
| Mistral OCR | "Experiment" tier, rate-limited, no fixed page cap | No |
| AWS Textract | 1,000 pages/month, first 3 months only | Yes |
| Google Document AI | $300 one-time credit | Yes |
| Claude | None | Yes |

Routing the Phase 5 spike primarily through Azure's and Mistral's free tiers means the most extraction-call-heavy activity in the whole project costs close to nothing. Full comparison in `docs/extraction-strategy.md`.

## Estimated total real API spend, whole project

**Roughly 150–250 real calls, under $2–3 total.** Full breakdown in `docs/testing-strategy.md`. The overwhelming majority of test runs during actual development touch zero real API calls, real or free-tier.

## What is measured vs. what is estimated (business metrics, Phase 16)

Straight-through-processing rate, review rate, average processing time, and correction rate are all directly observable from system timestamps and state history — genuinely measured, no assumption baked in. "Estimated time saved" (documents processed × assumed manual minutes) is explicitly an *estimate*, shown on the dashboard with its assumption stated and adjustable, never presented as a measured number. This distinction matters enough to state here, not just in Phase 16 — an honest cost/value story requires not overclaiming savings any more than it requires not overclaiming infrastructure cost.

# The business problem

## The pain, validated against real AP practice

AP staff at real companies lose disproportionate time to manual data entry, chasing missing information, and resolving invoice-to-PO/receipt mismatches — not to genuine judgment calls. Industry sources consistently point to manual data entry, missing or incorrect PO references, and price/quantity mismatches as the dominant causes of delay and error, with duplicate payment as the costliest failure mode.

## Why this problem is *not* as novel as it first looks

"Invoice arrives → gets extracted → validated → actioned" is not a new automation — mature AP vendors (Bill.com, Stampli, Tipalti, Rillion, DocuWare) already sell exactly this. Deterministic three-way matching already handles roughly 75–80% of invoice volume in well-run programs without any AI involved. A project that leads with "AI reads invoices" is competing with commodity software and will read as a demo, not engineering.

## The reframed problem this project actually solves

> Reliably turn an arbitrary invoice document into a trustworthy structured record, know when *not* to trust it, and route the untrustworthy cases to a human efficiently.

Everything downstream of a clean, trusted structured record (approval routing, ledger posting, notification) is comparatively conventional software — still built here, still real, but not where the interesting engineering is. The differentiated, portfolio-worthy story is the discipline at the boundary between deterministic automation and AI-assisted extraction, plus a human-review loop that treats AI output as evidence, not fact.

**Known risk of this framing:** focusing on extraction-and-trust could make the business-action half of the system feel like an afterthought. This is addressed directly by giving the downstream action (Phase 12) and the human-review UX (Phase 10) equal engineering weight to extraction, not treating them as the "easy phases."

## Why invoice/AP, and not another document workflow

| Alternative | Why it's weaker for this project |
|---|---|
| Expense receipts | Thinner schema, usually no approval-threshold or matching story — a smaller version of the same idea |
| Purchase orders | Outbound, not inbound — nothing to validate a PO *against* |
| Customer applications | Drags in KYC/credit-decisioning and compliance concerns outside this project's scope |
| Insurance claims | Adjudication logic is domain-regulated in ways hard to model credibly without insurance expertise |
| Contracts | Mostly narrative, not structured — a strong AI-only use case, but weak for demonstrating the deterministic/AI *split* that is this project's actual differentiator |

Invoices sit in the sweet spot: structured enough to validate deterministically, variable enough in layout that AI extraction earns its place, and financially consequential enough that human-in-the-loop review is self-evidently justified.

## What this project explicitly is not

- Not a replacement for a real ERP or accounting system (see `docs/architecture.md` for the mock-ledger decision).
- Not a payments system — no automated execution of a payment, ever.
- Not an enterprise multi-tenant SaaS platform — single-tenant, portfolio scale.
- Not a claim of production readiness beyond what is actually built and tested — see `docs/deployment.md` for the honest framing of "production-grade" used throughout this project.

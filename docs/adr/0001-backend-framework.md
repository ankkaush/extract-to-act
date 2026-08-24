# ADR 0001: Backend framework — FastAPI

**Status:** Accepted
**Confidence:** High

## Decision

Use FastAPI for the application (upload API, review UI endpoints, dashboard).

## Alternatives considered

- **Django** — more batteries-included (admin, ORM, auth), but heavier than this project needs and the admin panel isn't a good fit for a purpose-built review UI.
- **Flask** — comparable simplicity, but no native async support and weaker request/response typing than FastAPI's Pydantic integration.

## Why

- Continuity with prior projects (see project owner's stated preference).
- Native async support fits I/O-bound external provider calls (extraction, storage, accounting) without extra tooling.
- Pydantic models map cleanly onto extraction schemas (`docs/data-model.md`), giving request/response validation for free at the exact boundary (extraction output) where correctness matters most.

## What would change this

If the review UI turns out to need rich, stateful client-side interactivity beyond server-rendered templates/HTMX, a separate frontend framework might be added alongside FastAPI-as-API — but that's an addition, not a replacement, and only decided once Phase 10 is underway.

# ADR 0002: Database — PostgreSQL

**Status:** Accepted
**Confidence:** High

## Decision

Use PostgreSQL as the sole datastore, via SQLAlchemy models and Alembic migrations.

## Alternatives considered

- **SQLite** — fine for local scratch work, not for a system that needs concurrent worker access and production deployment; kept out entirely rather than used as a dev-only crutch, to avoid dev/prod schema drift.
- **MongoDB** — would fit the schema-variable raw-provider-response data well, but would sacrifice the relational integrity needed for state transitions, the audit trail, and financial totals, where a wrong answer is a real business risk, not a nice-to-have.

## Why

This system needs both: strict relational integrity (state transitions, audit trail, approvals — places where correctness matters) and flexible, schema-less storage for raw extraction-provider output that differs by provider and may change shape as the provider landscape evolves. PostgreSQL's `JSONB` column type gives the second without giving up the first — a pure document store or a non-JSON relational store would each partially sacrifice one side. Also continuity with prior projects.

## What would change this

If raw-provider-payload storage genuinely needed document-database query patterns (deep nested queries across arbitrary provider schemas) that JSONB couldn't reasonably support, that would be a signal to reconsider — not expected at this project's scale.

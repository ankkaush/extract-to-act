# Security

Proportional to a single-tenant, portfolio-scale, publicly-visible-repository project — not an enterprise security program. Designed from the start, not bolted on in Phase 14, though Phase 14 is where every control here is actually implemented and verified.

## Repository-level (public GitHub safety)

| Risk | Control |
|---|---|
| Secret committed to git | `.env` is git-ignored from commit one; `.env.example` lists every required variable name with a placeholder, never a real value; pre-commit secret scanning (`gitleaks` or `detect-secrets`) catches an accidentally-staged key before it's committed |
| Sensitive data in fixtures | All sample/fixture invoices are synthetic or clearly fabricated — never a real vendor's real document, even anonymized, since anonymizing financial documents is easy to get subtly wrong |
| Local artifacts leaking in | `.gitignore` excludes local DB dumps, any local document storage path, log files, IDE/OS files |
| CI secrets exposure | Real provider API keys (for the rare Tier-3/4 test run) live in GitHub Actions encrypted secrets, never inline in workflow YAML |

## Application-level

| Risk | Control |
|---|---|
| Malicious or oversized upload | Content-sniffed file-type allowlist (not extension-based); hard size ceiling enforced before storage or any paid provider call |
| Unauthorized document access | Signed, short-lived storage URLs; access scoped to the authenticated user even in a single-tenant MVP, so the pattern is correct if a second tenant is ever added |
| Prompt injection inside a document | Extracted values are always treated as untrusted data and re-checked deterministically regardless of what any AI step returns; extracted text never flows into a system prompt or executable context |
| Replay / duplicate submission | The idempotency design (`docs/reliability.md`) doubles as replay protection |
| Unauthorized approval action | Approval endpoints require an authenticated, role-checked actor; every approval/rejection is attributed and logged, never anonymous |
| Sensitive data in logs | Log document IDs and content hashes, never full document text, bank account numbers, or tax IDs |
| External-provider data handling | Each extraction provider's API-data-training policy is documented once (Phase 5) and disclosed plainly in the README, since this is a public repo touching real (if synthetic) financial documents |
| Bank/payment detail fraud | Bank/IBAN/payment-routing fields are never auto-populated into any downstream write path — captured for audit display only; a real bank-detail change is always a manual, out-of-band-verified event, never a workflow output |

## Deliberately not built

SSO/OAuth, a formal RBAC framework beyond two roles (admin, reviewer/approver), rate limiting beyond a basic per-IP throttle, a compliance program (SOC2, formal DLP), or field-level encryption/HSM. Each solves a problem this single-tenant portfolio deployment doesn't have.

## Where this is implemented and tested

Phase 4 (upload validation), Phase 6 (provider data handling), Phase 10/11 (auth on review/approval endpoints), and consolidated verification in Phase 14, where every row in the tables above gets a corresponding passing test.

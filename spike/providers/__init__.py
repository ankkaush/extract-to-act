"""Provider wrappers for the Phase 5 spike. Each module exposes a single
`extract(doc_path: Path, doc_id: str) -> NormalizedExtraction` function.

Status: written against each provider's documented API shape, but not
yet exercised against a live account — no credentials were available in
this environment when these were written. Treat the first real run as
also testing this code, not just the providers; see spike/README.md.
"""

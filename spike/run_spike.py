"""Runs every sample invoice in spike/samples/ through every provider that
has credentials configured, and writes each result to
spike/results/<provider>/<doc_id>.json.

Usage:
    python -m spike.run_spike [--budget-cap 2.00] [--providers azure,mistral,claude]

Deliberately conservative by default: skips a provider entirely if its
env vars aren't set (rather than failing the whole run), and refuses to
keep going once estimated real spend crosses --budget-cap — see
docs/cost-strategy.md. Azure and Mistral cost stay ~$0 on their free
tiers; the cap mainly protects against an unexpectedly large Claude bill
from a bug (e.g. an accidental loop) rather than the plan itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from spike.schema import NormalizedExtraction

SPIKE_DIR = Path(__file__).parent
SAMPLES_DIR = SPIKE_DIR / "samples"
RESULTS_DIR = SPIKE_DIR / "results"

_SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

_PROVIDERS = {
    "azure": ("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "AZURE_DOCUMENT_INTELLIGENCE_KEY"),
    "mistral": ("MISTRAL_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY",),
}


def _available_providers(requested: list[str]) -> list[str]:
    available = []
    for name in requested:
        required_vars = _PROVIDERS[name]
        missing = [v for v in required_vars if not os.environ.get(v)]
        if missing:
            print(f"[skip] {name}: missing {', '.join(missing)}")
            continue
        available.append(name)
    return available


def _run_one(provider_name: str, doc_path: Path, doc_id: str) -> NormalizedExtraction:
    if provider_name == "azure":
        from spike.providers import azure_provider as mod
    elif provider_name == "mistral":
        from spike.providers import mistral_provider as mod
    elif provider_name == "claude":
        from spike.providers import claude_provider as mod
    else:
        raise ValueError(provider_name)

    try:
        return mod.extract(doc_path, doc_id)
    except Exception as exc:  # noqa: BLE001 — a spike script; record and move on
        return NormalizedExtraction(
            provider_name=provider_name, model_version=None, doc_id=doc_id, error=str(exc)
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-cap", type=float, default=2.00)
    parser.add_argument("--providers", default="azure,mistral,claude")
    args = parser.parse_args()

    samples = sorted(p for p in SAMPLES_DIR.iterdir() if p.suffix.lower() in _SUPPORTED_EXTENSIONS)
    if not samples:
        print(f"No sample documents found in {SAMPLES_DIR}. See spike/README.md.")
        sys.exit(1)

    requested = [p.strip() for p in args.providers.split(",") if p.strip()]
    providers = _available_providers(requested)
    if not providers:
        print("No providers have credentials configured. See spike/README.md.")
        sys.exit(1)

    print(f"{len(samples)} sample document(s) x {len(providers)} provider(s) = "
          f"{len(samples) * len(providers)} calls planned.")

    total_estimated_cost = 0.0
    for doc_path in samples:
        doc_id = doc_path.stem
        for provider_name in providers:
            result = _run_one(provider_name, doc_path, doc_id)
            cost = result.estimated_cost_usd or 0.0
            total_estimated_cost += cost

            if total_estimated_cost > args.budget_cap:
                print(
                    f"\nBUDGET CAP HIT: estimated spend ${total_estimated_cost:.4f} exceeds "
                    f"--budget-cap ${args.budget_cap:.2f}. Stopping before this result is saved."
                )
                sys.exit(2)

            out_dir = RESULTS_DIR / provider_name
            out_dir.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(result.to_json(), indent=2, default=str)
            (out_dir / f"{doc_id}.json").write_text(payload)

            status = "ERROR" if result.error else "ok"
            print(
                f"  {provider_name:10s} {doc_id:20s} {status:6s} "
                f"latency={result.latency_seconds or 0:.2f}s cost=${cost:.4f}"
            )

    print(f"\nDone. Total estimated cost this run: ${total_estimated_cost:.4f}")
    print(f"Results written to {RESULTS_DIR}. Next: python -m spike.evaluate")


if __name__ == "__main__":
    main()

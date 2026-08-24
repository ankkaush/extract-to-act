"""Cost estimation for spike runs. Prices are as documented in
docs/extraction-strategy.md at the time this was written (2026-08) —
provider pricing changes; re-check before trusting this for anything
beyond a rough spike budget. See docs/cost-strategy.md.
"""

# Both have genuine free tiers (Azure: 500 pages/month ongoing, no card;
# Mistral: rate-limited "Experiment" tier, no card) — a spike of ~15-20
# documents should cost $0 on both. These per-page rates are what kicks
# in only if the free tier is exhausted.
AZURE_PREBUILT_INVOICE_USD_PER_PAGE = 0.01
MISTRAL_OCR_USD_PER_PAGE = 0.004  # $4 / 1,000 pages

# Claude has no free tier — every spike call against it costs real money,
# small as it is. Per-million-token rates, input/output.
CLAUDE_PRICING_USD_PER_MILLION_TOKENS = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}


def estimate_claude_cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = CLAUDE_PRICING_USD_PER_MILLION_TOKENS.get(
        model, CLAUDE_PRICING_USD_PER_MILLION_TOKENS["claude-sonnet-5"]
    )
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate

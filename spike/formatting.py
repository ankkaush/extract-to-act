"""Locale-style rendering of dates and amounts for the synthetic invoices.
These functions only control how a value is *displayed* on the rendered
document — the ground truth in invoice_specs.py is always the plain ISO
date / plain float, regardless of how it's shown. That's the whole point
of these test cases: the displayed format varies, the correct extracted
value doesn't.
"""

from __future__ import annotations

from datetime import date

_CURRENCY_SYMBOLS = {
    "USD": "$",
    "CAD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "INR": "₹",
}


def format_date(iso_date: str, style: str) -> str:
    d = date.fromisoformat(iso_date)
    if style == "us":
        return d.strftime("%m/%d/%Y")
    if style == "eu_dot":
        return d.strftime("%d.%m.%Y")
    if style == "dd_mm_yyyy_slash":
        return d.strftime("%d/%m/%Y")
    if style == "dd_mm_yyyy_dash":
        return d.strftime("%d-%m-%Y")
    if style == "iso":
        return d.isoformat()
    raise ValueError(f"unknown date style: {style}")


def _group_western(int_part: str) -> str:
    rev = int_part[::-1]
    groups = [rev[i : i + 3] for i in range(0, len(rev), 3)]
    return ",".join(groups)[::-1]


def _group_indian(int_part: str) -> str:
    # Last 3 digits, then groups of 2: 200000 -> 2,00,000
    if len(int_part) <= 3:
        return int_part
    last_three = int_part[-3:]
    rest = int_part[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join([*groups, last_three])


def format_amount(value: float, currency: str, *, ambiguous_symbol_only: bool = False) -> str:
    """Render `value` in `currency`'s conventional display format.

    `ambiguous_symbol_only=True` (inv_11) renders a bare currency symbol
    with no code — deliberately, to test currency inference from context
    rather than an explicit label.
    """
    decimals = 0 if currency == "JPY" else 2
    negative = value < 0
    magnitude = abs(value)
    # Format the whole number as one string first, then split — rounding
    # the integer and fractional parts independently (e.g. round(839.70)
    # then format ".70" separately) causes carry errors, like turning
    # 839.70 into "840.70". A single formatted string carries correctly.
    formatted = f"{magnitude:.{decimals}f}"
    if decimals:
        int_part, frac_part = formatted.split(".")
    else:
        int_part, frac_part = formatted, None

    if currency == "INR":
        grouped = _group_indian(int_part)
        number = f"{grouped}.{frac_part}" if frac_part else grouped
        text = f"{_CURRENCY_SYMBOLS['INR']}{number}"
    elif currency == "EUR":
        grouped = _group_western(int_part).replace(",", ".")
        text = f"{grouped},{frac_part} €" if frac_part else f"{grouped} €"
    else:
        grouped = _group_western(int_part)
        symbol = "$" if ambiguous_symbol_only else _CURRENCY_SYMBOLS.get(currency, currency + " ")
        text = f"{symbol}{grouped}.{frac_part}" if frac_part else f"{symbol}{grouped}"

    return f"-{text}" if negative else text

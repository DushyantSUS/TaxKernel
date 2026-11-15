"""Number formatting shared by narrator and guardrails.

Indian digit grouping is used everywhere (``12,34,567``, not ``1,234,567``).
The narrator and the numeric guard both call these helpers, so a rendered
amount can never differ from the audited value.
"""

from __future__ import annotations


def _group_indian(digits: str) -> str:
    """Group an integer digit string the Indian way (last 3, then pairs)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def format_inr(value: float) -> str:
    """``1234567`` -> ``₹12,34,567`` (paise only when non-zero)."""
    negative = value < 0
    magnitude = abs(float(value))
    whole, _, fraction = f"{magnitude:.2f}".partition(".")
    fraction = fraction.rstrip("0")
    rendered = "₹" + _group_indian(whole or "0")
    if fraction:
        rendered += "." + fraction
    return ("-" if negative else "") + rendered


def format_number(value: float) -> str:
    """Grouped number without the currency symbol."""
    return format_inr(value).lstrip("₹")


def format_percent(value: float) -> str:
    """``10.0`` -> ``10%``, ``7.25`` -> ``7.25%``."""
    if float(value).is_integer():
        return f"{int(value)}%"
    return f"{value:.2f}".rstrip("0").rstrip(".") + "%"

"""Rules-first intent classification (milestone M3).

No model, no embeddings, no network. A deterministic keyword/entity matcher
maps a question onto one of the supported intents, or refuses it as
out-of-scope. Determinism matters: the same query must always route to the
same engine so answers are replayable.

Anything not in the whitelist is refused rather than guessed — the refusal is
a first-class outcome (ARCHITECTURE §9, ``OUT_OF_SCOPE``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Final


class Intent(str, Enum):
    """Supported question shapes."""

    AIS_MISMATCH = "ais_mismatch"
    REGIME_COMPARE = "regime_compare"
    GST_THRESHOLD = "gst_threshold"
    ADVANCE_TAX = "advance_tax"
    TDS_RATE = "tds_rate"
    DEDUCTION_44ADA = "deduction_44ada"
    INVOICE_REVIEW = "invoice_review"
    CASH_FLOW = "cash_flow"
    SIMULATE = "simulate"
    OUT_OF_SCOPE = "out_of_scope"


#: Human-readable scope list, reused by refusal answers.
SUPPORTED_TOPICS: Final[tuple[str, ...]] = (
    "AIS / Form 26AS mismatches",
    "old vs new tax regime comparison",
    "GST registration threshold",
    "advance-tax instalments",
    "TDS sections and rates",
    "section 44ADA presumptive taxation",
    "why an invoice was flagged",
    "cash-flow and penalty forecasts",
    "what-if simulations",
)

# Ordered most-specific first: the first intent with the highest score wins.
_RULES: Final[tuple[tuple[Intent, tuple[str, ...]], ...]] = (
    (
        Intent.SIMULATE,
        ("what if", "simulate", "simulation", "if i earn", "if my income", "scenario"),
    ),
    (
        Intent.AIS_MISMATCH,
        ("ais", "26as", "annual information statement", "mismatch", "reconcil"),
    ),
    (
        Intent.REGIME_COMPARE,
        ("regime", "old tax", "new tax", "which tax system", "better for me"),
    ),
    (
        Intent.GST_THRESHOLD,
        ("gst", "gstr", "registration threshold", "20 lakh", "turnover limit"),
    ),
    (
        Intent.ADVANCE_TAX,
        ("advance tax", "instalment", "installment", "challan", "quarterly tax"),
    ),
    (
        Intent.TDS_RATE,
        ("tds", "withholding", "form 16a", "194", "393"),
    ),
    (
        Intent.DEDUCTION_44ADA,
        ("44ada", "44ad", "presumptive", "professional income"),
    ),
    (
        Intent.INVOICE_REVIEW,
        ("invoice", "flagged", "anomaly", "anomalous", "why was", "explain"),
    ),
    (
        Intent.CASH_FLOW,
        ("cash flow", "cashflow", "runway", "liquidity", "penalt", "forecast"),
    ),
)

_AMOUNT_RE: Final = re.compile(
    r"(?:rs\.?|inr|₹)?\s*\b(\d[\d,]*(?:\.\d+)?)\s*(lakh|lakhs|lac|lacs|crore|crores|k|thousand)?\b",
    re.IGNORECASE,
)
_INVOICE_RE: Final = re.compile(r"invoice\s*(?:id|no\.?|number|#)?\s*(\d+)", re.IGNORECASE)
_SECTION_RE: Final = re.compile(r"\b(\d{3}[a-z]?)\b", re.IGNORECASE)
_QUOTED_RE: Final = re.compile(r"[\"“']([^\"”']{2,60})[\"”']")
_FROM_RE: Final = re.compile(r"\bfrom\s+([A-Z][\w&.\- ]{1,40})")

_MULTIPLIERS: Final[dict[str, float]] = {
    "lakh": 100_000.0,
    "lakhs": 100_000.0,
    "lac": 100_000.0,
    "lacs": 100_000.0,
    "crore": 10_000_000.0,
    "crores": 10_000_000.0,
    "k": 1_000.0,
    "thousand": 1_000.0,
}


@dataclass(frozen=True, slots=True)
class IntentResult:
    """Outcome of classification."""

    intent: Intent
    confidence: float
    matched: tuple[str, ...] = ()
    slots: dict[str, object] = field(default_factory=dict)
    reason: str | None = None

    @property
    def is_supported(self) -> bool:
        return self.intent is not Intent.OUT_OF_SCOPE


def normalise(text: str) -> str:
    """Lowercase and collapse whitespace so matching is stable."""
    return " ".join(text.lower().replace("’", "'").split())


def classify(query: str) -> IntentResult:
    """Classify ``query`` into a supported intent or ``OUT_OF_SCOPE``."""
    text = normalise(query)
    if not text:
        return IntentResult(
            intent=Intent.OUT_OF_SCOPE,
            confidence=0.0,
            reason="empty query",
        )

    best_intent = Intent.OUT_OF_SCOPE
    best_matched: tuple[str, ...] = ()
    for intent, phrases in _RULES:
        matched = tuple(p for p in phrases if p in text)
        if len(matched) > len(best_matched):
            best_intent = intent
            best_matched = matched

    if not best_matched:
        return IntentResult(
            intent=Intent.OUT_OF_SCOPE,
            confidence=0.0,
            reason="no supported tax topic matched",
        )

    confidence = min(0.95, 0.60 + 0.10 * (len(best_matched) - 1))
    return IntentResult(
        intent=best_intent,
        confidence=round(confidence, 2),
        matched=best_matched,
        slots=extract_slots(query),
    )


def extract_slots(query: str) -> dict[str, object]:
    """Extract typed entities the orchestrator can pass to engines."""
    slots: dict[str, object] = {}

    invoice_match = _INVOICE_RE.search(query)
    if invoice_match:
        slots["invoice_id"] = int(invoice_match.group(1))

    quoted = _QUOTED_RE.search(query)
    if quoted:
        slots["vendor"] = quoted.group(1).strip()
    else:
        from_match = _FROM_RE.search(query)
        if from_match:
            slots["vendor"] = from_match.group(1).strip().rstrip(".,?!")

    amount = _parse_amount(query)
    if amount is not None:
        slots["amount"] = amount

    section = _SECTION_RE.search(query)
    if section:
        slots["section"] = section.group(1).upper()

    return slots


def _parse_amount(query: str) -> float | None:
    """First plausible monetary amount in the query (ignores years)."""
    for match in _AMOUNT_RE.finditer(query):
        raw = match.group(1)
        if raw is None:
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:  # pragma: no cover - regex guarantees digits
            continue
        suffix = (match.group(2) or "").lower()
        if suffix:
            value *= _MULTIPLIERS.get(suffix, 1.0)
        elif 1900 <= value <= 2100 and "." not in raw:
            continue  # a year, not an amount
        if value > 0:
            return value
    return None

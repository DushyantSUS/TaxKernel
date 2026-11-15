"""Deterministic Tier-1 template narrator and guardrail enforcement (milestone M4).

The narrator converts audited facts into human-readable text via Jinja2
templates. No LLM is required. A strict numeric guardrail verifies that no
number appears in the output unless it exists in :attr:`Facts.numbers`.

Any guardrail failure converts the answer into a structured refusal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import jinja2

from intel.envelope import (
    Band,
    Citation,
    Envelope,
    NumberFact,
    RefusalCode,
    refusal,
)
from intel.formatting import format_inr, format_number, format_percent
from intel.intent import Intent, SUPPORTED_TOPICS

if TYPE_CHECKING:
    from intel.confidence import ConfidenceResult
    from intel.orchestrator import Facts

TEMPLATES_DIR: Final[Path] = Path(__file__).resolve().parent / "templates"

_JINJA_ENV: Final[jinja2.Environment] = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

_TEMPLATE_MAP: Final[dict[Intent, str]] = {
    Intent.AIS_MISMATCH: "ais_mismatch.j2",
    Intent.REGIME_COMPARE: "regime_compare.j2",
    Intent.GST_THRESHOLD: "gst_threshold.j2",
    Intent.ADVANCE_TAX: "advance_tax.j2",
    Intent.TDS_RATE: "tds_rate.j2",
    Intent.DEDUCTION_44ADA: "deduction_44ada.j2",
    Intent.INVOICE_REVIEW: "invoice_review.j2",
    Intent.CASH_FLOW: "cash_flow.j2",
    Intent.SIMULATE: "simulate.j2",
}

_NUMERIC_TOKEN_RE: Final = re.compile(
    r"(?:rs\.?|inr|₹)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakh|lakhs|lac|lacs|crore|crores|k|thousand|%)?",
    re.IGNORECASE,
)

# Allowed legal or statutory constants that templates may reference without being facts
_STATUTORY_CONSTANTS: Final[set[float]] = {
    0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 8.0, 9.0, 10.0, 12.0, 15.0, 18.0, 20.0,
    22.0, 28.0, 44.0, 50.0, 75.0, 100.0, 194.0, 211.0, 234.0, 393.0, 2017.0, 2024.0, 2025.0,
}


def _get_number(facts: "Facts", label: str, default: float = 0.0) -> float:
    for n in facts.numbers:
        if n.label == label:
            return n.value
    return default


def _build_context(facts: "Facts") -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    for n in facts.numbers:
        ctx[n.label] = n.value
        ctx[f"{n.label}_inr"] = format_inr(n.value)
        ctx[f"{n.label}_grouped"] = format_number(n.value)

    # Intent-specific contextual variables
    if facts.intent is Intent.GST_THRESHOLD:
        ctx["turnover_inr"] = format_inr(_get_number(facts, "turnover"))
        ctx["limit_inr"] = format_inr(_get_number(facts, "gst_limit"))
        ctx["headroom_inr"] = format_inr(_get_number(facts, "headroom"))
        ctx["invoice_count"] = int(_get_number(facts, "invoice_count"))
        ctx["note"] = facts.notes[0] if facts.notes else ""

    elif facts.intent is Intent.REGIME_COMPARE:
        ctx["turnover_inr"] = format_inr(_get_number(facts, "turnover"))
        ctx["presumptive_inr"] = format_inr(_get_number(facts, "presumptive_income"))
        ctx["new_tax_inr"] = format_inr(_get_number(facts, "new_regime_tax"))
        ctx["old_tax_inr"] = format_inr(_get_number(facts, "old_regime_tax"))
        ctx["savings_inr"] = format_inr(_get_number(facts, "tax_savings"))
        ctx["preferred_regime"] = facts.notes[0] if facts.notes else "new"

    elif facts.intent is Intent.ADVANCE_TAX:
        ctx["turnover_inr"] = format_inr(_get_number(facts, "turnover"))
        ctx["estimated_tax_inr"] = format_inr(_get_number(facts, "estimated_tax"))
        ctx["cumulative_due_inr"] = format_inr(_get_number(facts, "cumulative_due"))
        ctx["percent"] = format_percent(_get_number(facts, "instalment_percent"))
        ctx["installment"] = facts.notes[0] if facts.notes else "Upcoming"
        ctx["due_date"] = facts.notes[1] if len(facts.notes) > 1 else ""

    elif facts.intent is Intent.TDS_RATE:
        ctx["tds_rate"] = format_percent(_get_number(facts, "tds_rate"))
        ctx["section_note"] = " ".join(facts.notes)

    elif facts.intent is Intent.DEDUCTION_44ADA:
        ctx["gross_inr"] = format_inr(_get_number(facts, "gross_receipts"))
        ctx["presumptive_inr"] = format_inr(_get_number(facts, "presumptive_income"))
        ctx["tax_inr"] = format_inr(_get_number(facts, "new_regime_tax"))
        ctx["status_note"] = facts.notes[0] if facts.notes else ""

    elif facts.intent is Intent.AIS_MISMATCH:
        ctx["turnover_inr"] = format_inr(_get_number(facts, "book_turnover"))
        ctx["ais_total_inr"] = format_inr(_get_number(facts, "ais_total"))
        ctx["variance_inr"] = format_inr(_get_number(facts, "variance"))
        ctx["unmatched_ais"] = int(_get_number(facts, "unmatched_in_ais"))
        ctx["unmatched_books"] = int(_get_number(facts, "unmatched_in_books"))
        ctx["confidence_pct"] = int(round(facts.signals.get("ais_match", 1.0) * 100))

    elif facts.intent is Intent.INVOICE_REVIEW:
        ctx["invoice_id"] = int(_get_number(facts, "invoice_id"))
        ctx["amount_inr"] = format_inr(_get_number(facts, "invoice_amount"))
        ctx["review_status"] = facts.notes[0] if facts.notes else ""
        ctx["evidence_ref"] = facts.evidence[0].ref_id if facts.evidence else "None"

    elif facts.intent is Intent.CASH_FLOW:
        ctx["turnover_inr"] = format_inr(_get_number(facts, "turnover"))
        ctx["lowest_balance_inr"] = format_inr(_get_number(facts, "lowest_projected_balance"))
        ctx["expected_penalty_inr"] = format_inr(_get_number(facts, "expected_penalty"))
        ctx["liquidity_risk"] = format_percent(_get_number(facts, "liquidity_risk_percent"))

    elif facts.intent is Intent.SIMULATE:
        ctx["gross_inr"] = format_inr(_get_number(facts, "simulated_turnover"))
        ctx["presumptive_inr"] = format_inr(_get_number(facts, "simulated_presumptive_income"))
        ctx["new_tax_inr"] = format_inr(_get_number(facts, "simulated_new_regime_tax"))
        ctx["old_tax_inr"] = format_inr(_get_number(facts, "simulated_old_regime_tax"))
        ctx["savings_inr"] = format_inr(_get_number(facts, "simulated_savings"))
        ctx["preferred_regime"] = facts.notes[1] if len(facts.notes) > 1 else "new"

    return ctx


def verify_numeric_integrity(
    rendered_text: str,
    facts: "Facts",
    citations: tuple[Citation, ...] = (),
) -> bool:
    """Ensure every number appearing in the output text is audited.

    Rejects hallucinated or mismatched figures.
    """
    valid_numbers: set[float] = {round(n.value, 2) for n in facts.numbers}
    valid_numbers.update(_STATUTORY_CONSTANTS)

    for c in citations:
        for s in re.findall(r"\d+", c.section):
            valid_numbers.add(float(s))
    for _, sec in facts.citation_keys:
        for s in re.findall(r"\d+", sec):
            valid_numbers.add(float(s))

    # Multipliers
    multipliers = {"lakh": 100000.0, "crore": 10000000.0, "k": 1000.0, "thousand": 1000.0}

    for m in _NUMERIC_TOKEN_RE.finditer(rendered_text):
        raw_val = m.group(1).replace(",", "")
        unit = (m.group(2) or "").lower()
        try:
            val = float(raw_val)
        except ValueError:
            continue

        if unit in multipliers:
            val *= multipliers[unit]

        rounded = round(val, 2)
        if rounded not in valid_numbers:
            # Also allow integer equivalence if rounded float matches
            if not any(abs(v - val) < 0.01 for v in valid_numbers):
                return False
    return True


def narrate(
    query: str,
    facts: "Facts",
    confidence_result: "ConfidenceResult",
    citations: tuple[Citation, ...] = (),
) -> Envelope:
    """Render and guard an auditable answer envelope."""
    # 1. Fact-level refusal check
    if facts.refusal is not None:
        template = _JINJA_ENV.get_template("refusal.j2")
        answer_text = template.render(
            reason=facts.refusal.value,
            detail=facts.refusal_detail or "",
            supported_topics=SUPPORTED_TOPICS,
        )
        return refusal(
            query=query,
            reason=facts.refusal,
            answer=answer_text,
            intent=facts.intent.value,
            confidence=0,
            citations=citations,
            rules_fired=facts.rules_fired,
            numbers=facts.numbers,
        )

    # 2. Confidence band guardrail: if band is REFUSED, decline
    if confidence_result.band is Band.REFUSED:
        return refusal(
            query=query,
            reason=RefusalCode.LOW_CONFIDENCE,
            answer=f"Declined to answer: confidence score {confidence_result.score} is below operational threshold.",
            intent=facts.intent.value,
            confidence=confidence_result.score,
            citations=citations,
            rules_fired=facts.rules_fired,
            numbers=facts.numbers,
        )

    # 3. Citation guardrail: if statutory intent requires citation but none provided
    if facts.citation_keys and not citations:
        return refusal(
            query=query,
            reason=RefusalCode.NO_CITATION,
            answer="Declined to answer: statutory citations could not be verified in local corpus.",
            intent=facts.intent.value,
            confidence=confidence_result.score,
            citations=(),
            rules_fired=facts.rules_fired,
            numbers=facts.numbers,
        )

    # 4. Render template
    template_name = _TEMPLATE_MAP.get(facts.intent)
    if not template_name:
        return refusal(
            query=query,
            reason=RefusalCode.OUT_OF_SCOPE,
            answer=f"No template available for intent {facts.intent.value}.",
            intent=facts.intent.value,
            confidence=0,
        )

    template = _JINJA_ENV.get_template(template_name)
    ctx = _build_context(facts)
    rendered = template.render(**ctx).strip()

    # 5. Numeric guardrail
    if not verify_numeric_integrity(rendered, facts, citations):
        return refusal(
            query=query,
            reason=RefusalCode.NUMERIC_MISMATCH,
            answer="Declined to answer: numeric integrity guardrail failed (output contained unverified numbers).",
            intent=facts.intent.value,
            confidence=0,
            citations=citations,
            rules_fired=facts.rules_fired,
            numbers=facts.numbers,
        )

    # 6. Word count limit (≤ 200 words)
    words = rendered.split()
    if len(words) > 200:
        rendered = " ".join(words[:200]) + "..."

    return Envelope(
        query=query,
        answer=rendered,
        citations=citations,
        rules_fired=facts.rules_fired,
        numbers=facts.numbers,
        confidence=confidence_result.score,
        band=confidence_result.band,
        human_review_required=(confidence_result.band is not Band.HIGH),
        intent=facts.intent.value,
        evidence_refs=facts.evidence,
    )

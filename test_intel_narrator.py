"""Tests for intel.narrator and guardrail enforcement (milestone M4)."""

from __future__ import annotations

import pytest

import database
from intel.confidence import ConfidenceResult, fuse
from intel.envelope import Band, Citation, NumberFact, RefusalCode
from intel.intent import Intent, classify
from intel.narrator import narrate, verify_numeric_integrity
from intel.orchestrator import Facts, gather


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    database.init_db()


def test_narrator_happy_path_regime_compare() -> None:
    res = classify("Compare old vs new regime")
    facts = gather(res)
    conf = fuse({"completeness": 1.0, "classifier": 1.0, "rag": 1.0, "ais_match": 1.0})
    citation = Citation(source="ITA 2025", section="44ADA")

    env = narrate("Compare old vs new regime", facts, conf, citations=(citation,))
    assert env.band is Band.HIGH
    assert env.refusal_reason is None
    assert "Tax calculation" in env.answer
    assert "Section 44ADA" in env.answer
    assert len(env.numbers) >= 3


def test_narrator_guardrail_missing_citation_refusal() -> None:
    res = classify("What is the GST threshold?")
    facts = gather(res)
    assert facts.citation_keys  # requires CGST Section 22
    conf = fuse({"completeness": 1.0, "forecast": 1.0})

    # Pass empty citations
    env = narrate("What is the GST threshold?", facts, conf, citations=())
    assert env.band is Band.REFUSED
    assert env.refusal_reason is RefusalCode.NO_CITATION
    assert "citations could not be verified" in env.answer


def test_narrator_guardrail_low_confidence_refusal() -> None:
    res = classify("What is the GST threshold?")
    facts = gather(res)
    citation = Citation(source="CGST Act 2017", section="22")
    # Low confidence result with score < 50
    low_conf = ConfidenceResult(score=30, band=Band.REFUSED, signals=(), coverage=0.3)

    env = narrate("What is the GST threshold?", facts, low_conf, citations=(citation,))
    assert env.band is Band.REFUSED
    assert env.refusal_reason is RefusalCode.LOW_CONFIDENCE
    assert "below operational threshold" in env.answer


def test_numeric_integrity_guard() -> None:
    facts = Facts(
        intent=Intent.GST_THRESHOLD,
        numbers=(
            NumberFact(label="turnover", value=1500000.0, source_engine="test"),
            NumberFact(label="gst_limit", value=2000000.0, source_engine="test"),
        ),
    )
    # Valid output with audited numbers
    valid_text = "Your turnover is ₹15,00,000 and GST limit is ₹20,00,000."
    assert verify_numeric_integrity(valid_text, facts) is True

    # Output with fabricated number (₹99,99,999)
    fabricated_text = "Your turnover is ₹15,00,000 and extra liability is ₹99,99,999."
    assert verify_numeric_integrity(fabricated_text, facts) is False


def test_narrator_refusal_passthrough() -> None:
    res = classify("Who is the president of Canada?")
    facts = gather(res)
    assert facts.refusal is RefusalCode.OUT_OF_SCOPE
    conf = fuse({})

    env = narrate("Who is the president of Canada?", facts, conf)
    assert env.band is Band.REFUSED
    assert env.refusal_reason is RefusalCode.OUT_OF_SCOPE
    assert "Supported topics include" in env.answer

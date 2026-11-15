"""Tests for intel.envelope (milestone M2 acceptance gate)."""

from __future__ import annotations

import json
import pytest

from intel.envelope import (
    Band,
    Citation,
    Envelope,
    EvidenceRef,
    NumberFact,
    RefusalCode,
    RuleFired,
    refusal,
)


def test_band_thresholds() -> None:
    assert Band.from_score(100) is Band.HIGH
    assert Band.from_score(80) is Band.HIGH
    assert Band.from_score(79) is Band.MEDIUM
    assert Band.from_score(50) is Band.MEDIUM
    assert Band.from_score(49) is Band.LOW
    assert Band.from_score(0) is Band.LOW

    assert Band.HIGH.allows_answer is True
    assert Band.MEDIUM.allows_answer is True
    assert Band.LOW.allows_answer is True
    assert Band.REFUSED.allows_answer is False


def test_citation_round_trip() -> None:
    c = Citation(source="ITA 2025", section="44ADA", title="Presumptive Taxation", url="https://incometax.gov.in")
    data = c.to_dict()
    assert data["source"] == "ITA 2025"
    assert data["section"] == "44ADA"
    assert data["title"] == "Presumptive Taxation"
    assert data["url"] == "https://incometax.gov.in"
    assert data["provisional"] is False

    reconstructed = Citation.from_dict(data)
    assert reconstructed == c


def test_envelope_success_serialization() -> None:
    env = Envelope(
        query="What is my advance tax liability?",
        intent="advance_tax",
        answer="Your upcoming installment is ₹15,000 due by 15-Dec.",
        confidence=85,
        band=Band.HIGH,
        human_review_required=False,
        citations=(Citation(source="ITA 2025", section="211"),),
        rules_fired=(RuleFired(engine="tax_rules", fn="get_upcoming_advance_tax"),),
        numbers=(
            NumberFact(label="estimated_tax", value=60000.0, source_engine="tax_rules.calculate_44ada_tax"),
            NumberFact(label="cumulative_due", value=45000.0, source_engine="tax_rules.get_upcoming_advance_tax"),
        ),
        evidence_refs=(EvidenceRef(kind="invoice", ref_id="1", hash="abcdef"),),
    )
    assert env.band is Band.HIGH
    assert env.refusal_reason is None
    assert env.is_refusal is False
    assert len(env.numbers) == 2

    payload = env.to_json()
    assert isinstance(payload, str)
    d = json.loads(payload)
    assert d["query"] == "What is my advance tax liability?"
    assert d["confidence"] == 85
    assert d["band"] == "high"
    assert len(d["citations"]) == 1
    assert d["citations"][0]["section"] == "211"

    # Invariant: can be parsed back
    from_d = Envelope.from_dict(d)
    assert from_d.query == env.query
    assert from_d.confidence == env.confidence
    assert from_d.band == env.band


def test_envelope_refusal_construction() -> None:
    env = refusal(
        query="Tell me about crypto trading tax in Malta",
        reason=RefusalCode.OUT_OF_SCOPE,
        answer="Malta tax laws are outside the TaxKernel domain.",
    )
    assert env.band is Band.REFUSED
    assert env.confidence == 0
    assert env.is_refusal is True
    assert env.refusal_reason is RefusalCode.OUT_OF_SCOPE
    assert "Malta" in env.answer

    d = json.loads(env.to_json())
    assert d["band"] == "refused"
    assert d["refusal_reason"] == "OUT_OF_SCOPE"

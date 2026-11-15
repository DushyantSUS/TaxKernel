"""Tests for intent classification and deterministic orchestration (milestone M3)."""

from __future__ import annotations

import pytest

import database
from intel.envelope import RefusalCode
from intel.formatting import format_inr, format_number, format_percent
from intel.intent import Intent, classify
from intel.orchestrator import Facts, gather


@pytest.fixture(autouse=True)
def _ensure_tables() -> None:
    database.init_db()


def test_formatting_indian_currency() -> None:
    assert format_inr(0) == "₹0"
    assert format_inr(500) == "₹500"
    assert format_inr(1500) == "₹1,500"
    assert format_inr(75000) == "₹75,000"
    assert format_inr(100000) == "₹1,00,000"
    assert format_inr(2000000) == "₹20,00,000"
    assert format_inr(15000000) == "₹1,50,00,000"
    assert format_inr(-45000) == "-₹45,000"

    assert format_number(1234567) == "12,34,567"
    assert format_percent(10.0) == "10%"
    assert format_percent(18.5) == "18.5%"


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        ("Do I have any AIS or 26AS mismatch with my ledger?", Intent.AIS_MISMATCH),
        ("Should I choose the old tax regime or new tax regime?", Intent.REGIME_COMPARE),
        ("Am I close to the 20 lakh GST registration threshold?", Intent.GST_THRESHOLD),
        ("When is my next advance tax installment due?", Intent.ADVANCE_TAX),
        ("What is the TDS rate under section 194J?", Intent.TDS_RATE),
        ("Can I claim 44ADA presumptive deduction on 50 lakhs?", Intent.DEDUCTION_44ADA),
        ("Why was invoice 4 flagged as an anomaly?", Intent.INVOICE_REVIEW),
        ("Show me my projected cash flow and penalty forecast", Intent.CASH_FLOW),
        ("What if I earn 60 lakhs this financial year?", Intent.SIMULATE),
        ("Who won the 2024 cricket world cup?", Intent.OUT_OF_SCOPE),
    ],
)
def test_intent_classification(query: str, expected_intent: Intent) -> None:
    res = classify(query)
    assert res.intent is expected_intent
    if expected_intent is not Intent.OUT_OF_SCOPE:
        assert res.is_supported is True
    else:
        assert res.is_supported is False


def test_orchestrator_gather_out_of_scope() -> None:
    res = classify("What is the capital of France?")
    facts = gather(res)
    assert facts.refusal is RefusalCode.OUT_OF_SCOPE
    assert "topic" in (facts.refusal_detail or "").lower() or "scope" in (facts.refusal_detail or "").lower()


def test_orchestrator_gather_gst_threshold() -> None:
    res = classify("What is my current GST turnover and limit?")
    facts = gather(res)
    assert facts.intent is Intent.GST_THRESHOLD
    assert facts.refusal is None
    labels = {n.label for n in facts.numbers}
    assert "turnover" in labels
    assert "gst_limit" in labels
    assert "headroom" in labels
    assert any(c[1] == "22" for c in facts.citation_keys)


def test_orchestrator_gather_regime_compare() -> None:
    res = classify("Compare old vs new regime for me")
    facts = gather(res)
    assert facts.intent is Intent.REGIME_COMPARE
    assert facts.refusal is None
    labels = {n.label for n in facts.numbers}
    assert "new_regime_tax" in labels
    assert "old_regime_tax" in labels
    assert "tax_savings" in labels


def test_orchestrator_gather_deduction_44ada() -> None:
    res = classify("Calculate 44ADA for 40 lakh gross receipts")
    facts = gather(res)
    assert facts.intent is Intent.DEDUCTION_44ADA
    assert facts.refusal is None
    gross = next(n.value for n in facts.numbers if n.label == "gross_receipts")
    assert gross == 4_000_000.0


def test_orchestrator_gather_simulation() -> None:
    res = classify("What if my income is 60 lakhs?")
    facts = gather(res)
    assert facts.intent is Intent.SIMULATE
    assert facts.refusal is None
    gross = next(n.value for n in facts.numbers if n.label == "simulated_turnover")
    assert gross == 6_000_000.0

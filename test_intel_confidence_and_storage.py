"""Tests for confidence fusion and answer persistence (milestone M6)."""

from __future__ import annotations

import pytest

import database
from intel.confidence import Band, WEIGHTS, clamp01, fuse
from intel.envelope import Citation, Envelope, NumberFact
from intel.storage import get_answer, list_answers, save_answer


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    database.init_db()
    # Ensure migration table exists in test DB if needed
    conn = database.get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intel_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            taxpayer_id INTEGER,
            invoice_id INTEGER,
            query TEXT NOT NULL,
            envelope_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def test_confidence_weights_sum_to_one() -> None:
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_confidence_clamp() -> None:
    assert clamp01(-5.0) == 0.0
    assert clamp01(10.0) == 1.0
    assert clamp01(0.75) == 0.75
    assert clamp01(float("nan")) == 0.0


def test_confidence_fusion() -> None:
    res = fuse({"ais_match": 1.0, "classifier": 1.0, "rag": 1.0, "completeness": 1.0, "forecast": 1.0})
    assert res.score == 100
    assert res.band is Band.HIGH
    assert res.coverage == 1.0

    partial = fuse({"completeness": 1.0})
    assert partial.score == 10
    assert partial.band is Band.LOW


def test_confidence_unknown_signal_raises() -> None:
    with pytest.raises(ValueError, match="unknown confidence signals"):
        fuse({"hallucinated_signal": 1.0})


def test_save_and_replay_answer() -> None:
    env = Envelope(
        query="What is my advance tax?",
        answer="Installment of ₹15,000 due 15-Dec.",
        confidence=85,
        band=Band.HIGH,
        human_review_required=False,
        citations=(Citation(source="ITA 2025", section="211"),),
        numbers=(NumberFact(label="due", value=15000.0, source_engine="tax_rules"),),
        intent="advance_tax",
    )
    answer_id = save_answer(env, user_id=1)
    assert answer_id > 0

    reconstructed = get_answer(answer_id)
    assert reconstructed is not None
    assert reconstructed.query == env.query
    assert reconstructed.answer == env.answer
    assert reconstructed.confidence == 85
    assert reconstructed.band is Band.HIGH
    assert len(reconstructed.citations) == 1
    assert reconstructed.citations[0].section == "211"

    recent = list_answers(user_id=1, limit=5)
    assert len(recent) >= 1
    assert any(r["id"] == answer_id for r in recent)

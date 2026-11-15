"""Tests for self-audit, drift detection, and retention policy (milestone M8)."""

from __future__ import annotations

import pytest

import database
from intel.envelope import Band, Envelope, NumberFact
from intel.selfaudit import audit_answer_drift, run_self_audit
from intel.storage import save_answer


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    database.init_db()
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


def test_drift_detection_no_drift() -> None:
    # 1. Ask a question and store its exact current answer
    from intel.service import ask

    env = ask("Compare old vs new regime", user_id=1)
    ans_id = save_answer(env, user_id=1)

    # 2. Audit drift
    drift = audit_answer_drift(ans_id, env.query, env.to_json())
    assert drift.drifted is False
    assert "Consistent" in drift.details


def test_drift_detection_detects_mismatch() -> None:
    # Stored answer with stale/drifted numbers
    stale_env = Envelope(
        query="Compare old vs new regime",
        answer="Old regime was better",
        confidence=80,
        band=Band.HIGH,
        human_review_required=False,
        numbers=(
            NumberFact(label="turnover", value=99999999.0, source_engine="mock"),
            NumberFact(label="new_regime_tax", value=5000000.0, source_engine="mock"),
        ),
        intent="regime_compare",
    )
    ans_id = save_answer(stale_env, user_id=1)

    drift = audit_answer_drift(ans_id, stale_env.query, stale_env.to_json())
    assert drift.drifted is True
    assert "turnover" in drift.details


def test_run_self_audit_dry_run() -> None:
    report = run_self_audit(dry_run=True)
    assert report.integrity_ok is True
    assert report.backup_path is None
    assert report.retention_8yr_compliant is True
    assert report.total_answers_audited >= 1


def test_run_self_audit_creates_backup(tmp_path: pytest.TempPathFactory) -> None:
    report = run_self_audit(dry_run=False)
    assert report.integrity_ok is True
    assert report.backup_path is not None
    assert report.retention_8yr_compliant is True

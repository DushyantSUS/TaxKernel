"""Persistence layer for intelligence answers (milestone M6).

Stores envelopes as append-only records in the ``intel_answers`` table for
audit trails, replayability, and drift detection.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from intel.envelope import Envelope


def _get_db() -> sqlite3.Connection:
    import database

    conn: sqlite3.Connection = database.get_db_connection()  # type: ignore[no-untyped-call]
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS intel_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            taxpayer_id INTEGER,
            invoice_id INTEGER,
            query TEXT NOT NULL,
            envelope_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def save_answer(
    envelope: Envelope,
    user_id: int = 1,
    taxpayer_id: int | None = None,
    invoice_id: int | None = None,
) -> int:
    """Store an envelope append-only into ``intel_answers``. Returns row ID."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO intel_answers (user_id, taxpayer_id, invoice_id, query, envelope_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, taxpayer_id, invoice_id, envelope.query, envelope.to_json()),
    )
    conn.commit()
    row_id = int(cursor.lastrowid or 0)
    conn.close()
    return row_id


def get_answer(answer_id: int) -> Envelope | None:
    """Load and reconstruct a stored envelope by its database ID."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT envelope_json FROM intel_answers WHERE id = ? LIMIT 1",
        (answer_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    raw_json = row["envelope_json"] if isinstance(row, sqlite3.Row) else row[0]
    return Envelope.from_json(str(raw_json))


def list_answers(user_id: int = 1, limit: int = 50) -> list[dict[str, Any]]:
    """List recent answers for a user."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, taxpayer_id, invoice_id, query, envelope_json, created_at
        FROM intel_answers
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "taxpayer_id": r["taxpayer_id"],
                "invoice_id": r["invoice_id"],
                "query": r["query"],
                "envelope": Envelope.from_json(str(r["envelope_json"])).to_dict(),
                "created_at": str(r["created_at"]),
            }
        )
    return out

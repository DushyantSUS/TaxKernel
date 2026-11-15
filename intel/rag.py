"""Local statutory RAG retrieval and citation resolution (milestone M5).

All citations are verified against a local SQLite FTS5 database built from the
statutory corpus. No outbound network requests are made.

If an orchestrator fact references a citation that cannot be resolved against
the corpus, the answer must be refused with RefusalCode.NO_CITATION.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from intel.corpus.build import DB_PATH, build_corpus_db
from intel.envelope import Citation

_DB_PATH: Final[Path] = DB_PATH


def _get_connection() -> sqlite3.Connection:
    if not _DB_PATH.exists():
        build_corpus_db(_DB_PATH)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_citation(source: str, section: str) -> Citation | None:
    """Resolve a specific statutory (source, section) pair from the corpus."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT source, section, title FROM corpus_fts WHERE source = ? AND section = ? LIMIT 1",
        (source, section),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return Citation(
        source=str(row["source"]),
        section=str(row["section"]),
        title=str(row["title"]) if row["title"] else None,
    )


def resolve_keys(keys: Sequence[tuple[str, str]]) -> tuple[Citation, ...] | None:
    """Resolve a sequence of citation keys.

    Returns a tuple of Citations if ALL keys resolve successfully; returns None
    if ANY key is missing (triggering a structured refusal).
    """
    resolved: list[Citation] = []
    for source, section in keys:
        c = resolve_citation(source, section)
        if c is None:
            return None
        resolved.append(c)
    return tuple(resolved)


def search(query: str, limit: int = 3) -> list[Citation]:
    """Search the corpus using SQLite FTS5 with BM25 ranking."""
    # Sanitize query for FTS5 (strip punctuation that could cause syntax errors)
    cleaned = " ".join(part for part in query.split() if part.isalnum())
    if not cleaned:
        return []

    conn = _get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT source, section, title, bm25(corpus_fts) AS rank
            FROM corpus_fts
            WHERE corpus_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (cleaned, limit),
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    results: list[Citation] = []
    for r in rows:
        results.append(
            Citation(
                source=str(r["source"]),
                section=str(r["section"]),
                title=str(r["title"]) if r["title"] else None,
            )
        )
    return results

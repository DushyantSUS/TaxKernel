"""Tests for local statutory RAG and citation resolution (milestone M5)."""

from __future__ import annotations

import pytest

from intel.rag import resolve_citation, resolve_keys, search


def test_resolve_citation_valid() -> None:
    c = resolve_citation("ITA 2025", "44ADA")
    assert c is not None
    assert c.source == "ITA 2025"
    assert c.section == "44ADA"
    assert "presumptive" in (c.title or "").lower()


def test_resolve_citation_unknown_returns_none() -> None:
    c = resolve_citation("ITA 2025", "999Z")
    assert c is None


def test_resolve_keys_all_valid() -> None:
    keys = (
        ("ITA 2025", "44ADA"),
        ("CGST Act 2017", "22"),
        ("ITA 2025", "211"),
    )
    resolved = resolve_keys(keys)
    assert resolved is not None
    assert len(resolved) == 3
    sections = [c.section for c in resolved]
    assert sections == ["44ADA", "22", "211"]


def test_resolve_keys_partial_failure_returns_none() -> None:
    keys = (
        ("ITA 2025", "44ADA"),
        ("ITA 2025", "DOES_NOT_EXIST"),
    )
    resolved = resolve_keys(keys)
    assert resolved is None  # Mandates a structured refusal


def test_search_bm25_ranking() -> None:
    results = search("presumptive profession gross receipts")
    assert len(results) > 0
    top = results[0]
    assert top.section == "44ADA"

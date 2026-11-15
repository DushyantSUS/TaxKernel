"""Tests for the presentation surface.

These are pytest-style (per D2) and exercise only the read-only demo module.
They must never open ``taxkernel_prod.db`` or make a network call.
"""

import json

import present_demo
import tax_rules


def test_snapshot_is_json_serializable():
    snapshot = present_demo.build_snapshot()
    encoded = json.dumps(snapshot)
    assert json.loads(encoded) == snapshot
    for key in ("meta", "receipts", "accrual", "gst", "ais", "classification", "itc",
                "regime", "advance", "switch", "gstr3b", "penalties", "liquidity"):
        assert key in snapshot


def test_receipts_and_accrual_match_the_engines():
    snapshot = present_demo.build_snapshot()
    invoices = present_demo.DEMO_INVOICES
    expected_total = sum(inv["amount"] for inv in invoices)
    expected = tax_rules.calculate_accrual_split(invoices, cash_balance=present_demo.CASH_BALANCE)

    assert snapshot["receipts"]["total"] == expected_total
    assert snapshot["accrual"]["green_zone_tax"] == round(expected["green_zone_tax"], 2)
    assert snapshot["accrual"]["red_zone_tax"] == round(expected["red_zone_tax"], 2)
    assert snapshot["accrual"]["needs_borrowing"] is expected["needs_borrowing"]


def test_gst_status_matches_forecast():
    snapshot = present_demo.build_snapshot()
    gst = snapshot["gst"]
    if gst["days_remaining"] <= 0 and not gst["predicted_date"].startswith("Never"):
        assert gst["status"] == "Crossed"
        assert gst["status_tone"] == "rose"
    assert 0.0 <= gst["r_squared"] <= 1.0


def test_regime_point_is_deterministic_and_monotonic():
    first = present_demo.regime_point(2_500_000)
    second = present_demo.regime_point(2_500_000)
    assert first == second
    assert first["new_tax_display"] == "1,04,000"

    higher = present_demo.regime_point(4_200_000)
    assert higher["new_tax"] >= first["new_tax"]
    assert higher["limit_exceeded"] is False

    over_ceiling = present_demo.regime_point(8_000_000)
    assert over_ceiling["limit_exceeded"] is True
    assert over_ceiling["savings"] >= 0


def test_indian_grouping():
    assert present_demo.inr(0) == "0"
    assert present_demo.inr(999) == "999"
    assert present_demo.inr(1_000) == "1,000"
    assert present_demo.inr(42_00_000) == "42,00,000"
    assert present_demo.inr(12_34_56_789) == "12,34,56,789"
    assert present_demo.inr(-2_500) == "-2,500"

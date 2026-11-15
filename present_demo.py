"""Presentation snapshot for the ``/present`` pitch page.

This module is deliberately read-only and offline:

* every figure is produced by the *existing* deterministic engines
  (``tax_rules``, ``ais_engine``, ``gst_engine``, ``classifier_engine``,
  ``forecast_engine``) against an in-memory sample ledger;
* ``taxkernel_prod.db`` is never opened or written;
* nothing here makes a network call.

The page it feeds is a demonstration surface. It does not replace the
``intel/`` intelligence layer described in ``IMPLEMENTATION_PLAN.md``; the
template narration shown on the page is illustrative and is labelled as such.
"""

from __future__ import annotations

import datetime
from typing import Any

import ais_engine
import classifier_engine
import gst_engine
import tax_rules
from forecast_engine import ForecastEngine

FY_LABEL = "FY 2026-27"

# ---------------------------------------------------------------------------
# Sample ledger (in memory only — never persisted)
# ---------------------------------------------------------------------------

DEMO_INVOICES: list[dict[str, Any]] = [
    {
        "id": 1,
        "vendor": "Northwind Software Consulting Pvt Ltd",
        "amount": 520_000.0,
        "date": "2026-04-12",
        "payment_state": "PAID",
    },
    {
        "id": 2,
        "vendor": "Vertex Data Science Labs",
        "amount": 460_000.0,
        "date": "2026-05-08",
        "payment_state": "PAID",
    },
    {
        "id": 3,
        "vendor": "Helios Software Systems",
        "amount": 720_000.0,
        "date": "2026-06-21",
        "payment_state": "PAID",
    },
    {
        "id": 4,
        "vendor": "Meridian Analytics LLP",
        "amount": 900_000.0,
        "date": "2026-07-30",
        "payment_state": "PENDING",
    },
    {
        "id": 5,
        "vendor": "Aurora Cloud Analytics Inc",
        "amount": 850_000.0,
        "date": "2026-09-05",
        "payment_state": "PENDING",
    },
    {
        "id": 6,
        "vendor": "Northwind Software Consulting Pvt Ltd",
        "amount": 750_000.0,
        "date": "2026-10-18",
        "payment_state": "PENDING",
    },
]

DEMO_AIS: list[dict[str, Any]] = [
    {"source_name": "NORTHWIND SOFTWARE CONSULTING PVT LTD", "amount": 520_000.0},
    {"source_name": "VERTEX DATA SCIENCE LABS", "amount": 460_000.0},
    {"source_name": "HELIOS SOFTWARE SYSTEMS", "amount": 720_000.0},
    {"source_name": "MERIDIAN ANALYTICS LLP", "amount": 900_000.0},
    {"source_name": "AURORA CLOUD ANALYTICS INC", "amount": 850_000.0},
    # Reported by the deductor at a lower value than the books.
    {"source_name": "NORTHWIND SOFTWARE CONSULTING PVT LTD", "amount": 610_000.0},
    # Reported in AIS but missing from the books.
    {"source_name": "QUANTUM LEAP MEDIA PRIVATE LIMITED", "amount": 380_000.0},
]

DEMO_PURCHASES: list[dict[str, Any]] = [
    {
        "vendor_gstin": "27AABCT1234A1Z5",
        "taxable_amount": 180_000.0,
        "cgst": 16_200.0,
        "sgst": 16_200.0,
        "igst": 0.0,
    },
    {
        "vendor_gstin": "29AACCV5678B1Z2",
        "taxable_amount": 120_000.0,
        "cgst": 10_800.0,
        "sgst": 10_800.0,
        "igst": 0.0,
    },
    # Supplier never filed GSTR-1 — this credit is at risk.
    {
        "vendor_gstin": "07AAACM9012C1Z8",
        "taxable_amount": 153_000.0,
        "cgst": 13_770.0,
        "sgst": 13_770.0,
        "igst": 0.0,
    },
    {
        "vendor_gstin": "33AAACQ3456D1Z1",
        "taxable_amount": 90_000.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "igst": 16_200.0,
    },
]

DEMO_GSTR2B: list[dict[str, Any]] = [
    {
        "id": "2B-001",
        "vendor_gstin": "27AABCT1234A1Z5",
        "taxable_amount": 180_000.0,
        "cgst": 16_200.0,
        "sgst": 16_200.0,
        "igst": 0.0,
    },
    {
        "id": "2B-002",
        "vendor_gstin": "29AACCV5678B1Z2",
        "taxable_amount": 120_000.0,
        "cgst": 10_800.0,
        "sgst": 10_800.0,
        "igst": 0.0,
    },
    {
        "id": "2B-004",
        "vendor_gstin": "33AAACQ3456D1Z1",
        "taxable_amount": 90_000.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "igst": 16_200.0,
    },
    {
        "id": "2B-009",
        "vendor_gstin": "19AAACX0000E1Z7",
        "taxable_amount": 60_000.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "igst": 10_800.0,
    },
]

CASH_BALANCE = 200_000.0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _group_indian(digits: str) -> str:
    """Group an integer string the Indian way: 12,34,56,789."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def inr(amount: float, decimals: int = 0) -> str:
    """Return an Indian-grouped amount without the rupee glyph."""
    value = float(amount)
    sign = "-" if value < 0 else ""
    quantised = round(abs(value), decimals)
    whole = int(quantised)
    text = _group_indian(str(whole))
    if decimals:
        fraction = f"{quantised - whole:.{decimals}f}".split(".")[1]
        text = f"{text}.{fraction}"
    return sign + text


def _pretty_date(iso_date: str) -> str:
    try:
        parsed = datetime.datetime.strptime(iso_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return iso_date
    return parsed.strftime("%d %b %Y")


def _gst_status(forecast: dict[str, Any]) -> dict[str, str]:
    predicted = str(forecast.get("predicted_date", ""))
    days = int(forecast.get("days_remaining", -1))
    if predicted.lower().startswith("never"):
        return {"tone": "emerald", "label": "Stable", "note": "Revenue trend does not cross the threshold."}
    if days <= 0:
        return {
            "tone": "rose",
            "label": "Crossed",
            "note": "Registration was due within 30 days of crossing.",
        }
    if days <= 90:
        return {"tone": "amber", "label": "Imminent", "note": "Registration window opens soon."}
    return {"tone": "emerald", "label": "On watch", "note": "Threshold is still ahead of the trend line."}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_snapshot() -> dict[str, Any]:
    """Compute every figure shown on the presentation page."""
    total = sum(inv["amount"] for inv in DEMO_INVOICES)
    paid = sum(inv["amount"] for inv in DEMO_INVOICES if inv["payment_state"] == "PAID")
    unpaid = total - paid

    accrual = tax_rules.calculate_accrual_split(DEMO_INVOICES, cash_balance=CASH_BALANCE)
    regime = tax_rules.calculate_44ada_tax(total)
    advance = tax_rules.get_upcoming_advance_tax(
        min(regime["new_regime_tax"], regime["old_regime_tax"])
    )

    forecaster = ForecastEngine()
    gst_forecast = forecaster.forecast_gst_crossing(DEMO_INVOICES)
    penalties = forecaster.forecast_penalties(DEMO_INVOICES)
    liquidity = forecaster.forecast_cash_flow(DEMO_INVOICES)

    reconciliation = ais_engine.reconcile(DEMO_INVOICES, DEMO_AIS)
    classification = classifier_engine.classify_activity(
        [inv["vendor"] for inv in DEMO_INVOICES]
    )
    switch = classifier_engine.simulate_retroactive_switch(total)
    itc = gst_engine.reconcile_itc(DEMO_PURCHASES, DEMO_GSTR2B)
    gstr3b = gst_engine.calculate_gstr3b(DEMO_INVOICES, DEMO_PURCHASES)

    gst_status = _gst_status(gst_forecast)
    tax_total = min(regime["new_regime_tax"], regime["old_regime_tax"])
    green_share = (accrual["green_zone_tax"] / tax_total * 100.0) if tax_total else 0.0

    snapshot: dict[str, Any] = {
        "meta": {
            "fy": FY_LABEL,
            "generated_at": datetime.datetime.now().strftime("%d %b %Y, %H:%M"),
            "invoice_count": len(DEMO_INVOICES),
            "ais_count": len(DEMO_AIS),
            "ledger": "Sample ledger, held in memory",
        },
        "receipts": {
            "total": round(total, 2),
            "total_display": inr(total),
            "paid": round(paid, 2),
            "paid_display": inr(paid),
            "unpaid": round(unpaid, 2),
            "unpaid_display": inr(unpaid),
            "paid_share_pct": round(paid / total * 100.0, 1) if total else 0.0,
        },
        "accrual": {
            "total_tax": round(tax_total, 2),
            "total_tax_display": inr(tax_total),
            "green_zone_tax": round(accrual["green_zone_tax"], 2),
            "green_zone_display": inr(accrual["green_zone_tax"]),
            "green_share_pct": round(green_share, 1),
            "red_zone_tax": round(accrual["red_zone_tax"], 2),
            "red_zone_display": inr(accrual["red_zone_tax"]),
            "red_share_pct": round(100.0 - green_share, 1),
            "borrowed_amount": round(accrual["borrowed_amount"], 2),
            "borrowed_display": inr(accrual["borrowed_amount"]),
            "interest_cost": round(accrual["interest_cost"], 2),
            "interest_display": inr(accrual["interest_cost"]),
            "needs_borrowing": bool(accrual["needs_borrowing"]),
            "unpaid_invoice_count": accrual["unpaid_invoice_count"],
            "paid_invoice_count": accrual["paid_invoice_count"],
        },
        "gst": {
            "predicted_date": str(gst_forecast["predicted_date"]),
            "predicted_display": _pretty_date(str(gst_forecast["predicted_date"])),
            "days_remaining": int(gst_forecast["days_remaining"]),
            "r_squared": round(float(gst_forecast["r_squared"]), 3),
            "is_structural_break": bool(gst_forecast["is_structural_break"]),
            "status": gst_status["label"],
            "status_tone": gst_status["tone"],
            "status_note": gst_status["note"],
            "threshold_display": inr(tax_rules.TOTAL_GST_LIMIT),
            "amber_display": inr(tax_rules.GST_AMBER_LIMIT),
        },
        "ais": {
            "confidence_pct": round(float(reconciliation["confidence_pct"]), 1),
            "scrutiny_risk_pct": round(float(reconciliation["scrutiny_risk_pct"]), 1),
            "variance": round(float(reconciliation["variance_inr"]), 2),
            "variance_display": inr(reconciliation["variance_inr"]),
            "total_ais_display": inr(reconciliation["total_ais"]),
            "total_books_display": inr(reconciliation["total_books"]),
            "matched_count": len(reconciliation["matched"]),
            "unmatched_ais_count": len(reconciliation["unmatched_in_ais"]),
            "unmatched_books_count": len(reconciliation["unmatched_in_books"]),
            "unmatched_ais_names": [
                entry["source_name"] for entry in reconciliation["unmatched_in_ais"]
            ],
            "unmatched_book_names": [
                inv["vendor"] for inv in reconciliation["unmatched_in_books"]
            ],
        },
        "classification": {
            "section": classification["classification"],
            "confidence_pct": round(float(classification["confidence_pct"]), 1),
            "professional_score": classification["professional_score"],
            "business_score": classification["business_score"],
            "matched_keywords": classification["matched_professional_keywords"],
            "risk_factors": classification["risk_factors"],
        },
        "itc": {
            "lost": round(float(itc["itc_lost_inr"]), 2),
            "lost_display": inr(itc["itc_lost_inr"]),
            "books_display": inr(itc["total_itc_books"]),
            "available_display": inr(itc["total_itc_2b"]),
            "unmatched_books_count": len(itc["unmatched_in_books"]),
            "unmatched_2b_count": len(itc["unmatched_in_2b"]),
        },
        "regime": {
            "new_tax": round(regime["new_regime_tax"], 2),
            "new_tax_display": inr(regime["new_regime_tax"]),
            "old_tax": round(regime["old_regime_tax"], 2),
            "old_tax_display": inr(regime["old_regime_tax"]),
            "preferred": regime["preferred_regime"],
            "savings": round(regime["tax_savings"], 2),
            "savings_display": inr(regime["tax_savings"]),
            "presumptive_income_display": inr(regime["presumptive_income"]),
            "limit_exceeded": bool(regime["limit_exceeded"]),
            "limit_display": inr(tax_rules.TOTAL_44ADA_LIMIT),
        },
        "advance": {
            "installment": advance["installment"],
            "due_date": advance["due_date"],
            "percent": advance["percent"],
            "cumulative_due": round(float(advance["cumulative_due"]), 2),
            "cumulative_due_display": inr(advance["cumulative_due"]),
        },
        "switch": {
            "tax_44ada": round(float(switch["tax_under_44ada"]), 2),
            "tax_44ada_display": inr(switch["tax_under_44ada"]),
            "tax_44ad": round(float(switch["tax_under_44ad"]), 2),
            "tax_44ad_display": inr(switch["tax_under_44ad"]),
            "cost": round(float(switch["misclassification_cost_inr"]), 2),
            "cost_display": inr(switch["misclassification_cost_inr"]),
            "worse_regime": switch["worse_regime"],
        },
        "gstr3b": {
            "output_tax": round(float(gstr3b["output_tax"]["total"]), 2),
            "output_tax_display": inr(gstr3b["output_tax"]["total"]),
            "itc": round(float(gstr3b["input_tax_credit"]["total"]), 2),
            "itc_display": inr(gstr3b["input_tax_credit"]["total"]),
            "net_payable": round(float(gstr3b["net_gst_payable_inr"]), 2),
            "net_payable_display": inr(gstr3b["net_gst_payable_inr"]),
        },
        "penalties": {
            "risk_pct": float(penalties["risk_pct"]),
            "expected_display": inr(penalties["expected_penalty_inr"]),
            "max_display": inr(penalties["max_penalty_inr"]),
        },
        "liquidity": {
            "dso": float(liquidity["dso"]),
            "dpo": float(liquidity["dpo"]),
            "ccc": float(liquidity["ccc"]),
            "risk_pct": float(liquidity["liquidity_risk_pct"]),
        },
    }
    return snapshot


def regime_point(receipts: float) -> dict[str, Any]:
    """What-if comparison for the presentation slider (tax engine only)."""
    receipts = max(0.0, float(receipts))
    info = tax_rules.calculate_44ada_tax(receipts)
    new_tax = float(info["new_regime_tax"])
    old_tax = float(info["old_regime_tax"])
    return {
        "receipts": round(receipts, 2),
        "receipts_display": inr(receipts),
        "presumptive_income_display": inr(info["presumptive_income"]),
        "new_tax": round(new_tax, 2),
        "new_tax_display": inr(new_tax),
        "old_tax": round(old_tax, 2),
        "old_tax_display": inr(old_tax),
        "preferred": info["preferred_regime"],
        "savings": round(float(info["tax_savings"]), 2),
        "savings_display": inr(info["tax_savings"]),
        "limit_exceeded": bool(info["limit_exceeded"]),
        "limit_display": inr(tax_rules.TOTAL_44ADA_LIMIT),
    }

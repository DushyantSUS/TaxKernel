"""Deterministic engine orchestration (milestone M3).

The orchestrator turns an :class:`intel.intent.IntentResult` into :class:`Facts`:
the numbers, provenance, and *proposed* citations that the narrator may use.
It never invents values — every number comes from a call into an existing
TaxKernel engine (``tax_rules``, ``ais_engine``, ``tds_engine``,
``forecast_engine``, ``classifier_engine``).

It also never asserts legal claims itself: it lists ``citation_keys`` which
:mod:`intel.rag` must resolve against the local corpus. An unresolved key
becomes a ``NO_CITATION`` refusal, so the narrator cannot cite statute that is
not installed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from intel.envelope import EvidenceRef, NumberFact, RefusalCode, RuleFired
from intel.intent import Intent, IntentResult


@dataclass(frozen=True, slots=True)
class Facts:
    """Raw, auditable output of the deterministic engines."""

    intent: Intent
    numbers: tuple[NumberFact, ...] = ()
    rules_fired: tuple[RuleFired, ...] = ()
    citation_keys: tuple[tuple[str, str], ...] = ()
    signals: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    refusal: RefusalCode | None = None
    refusal_detail: str | None = None


#: Citation keys the orchestrator may propose. Every key must exist in the
#: seeded corpus, otherwise answers depending on it are refused.
KEY_44ADA: Final[tuple[str, str]] = ("ITA 2025", "44ADA")
KEY_44AD: Final[tuple[str, str]] = ("ITA 2025", "44AD")
KEY_ADVANCE: Final[tuple[str, str]] = ("ITA 2025", "211")
KEY_TDS: Final[tuple[str, str]] = ("ITA 2025", "393")
KEY_GST: Final[tuple[str, str]] = ("CGST Act 2017", "22")
KEY_PENALTY: Final[tuple[str, str]] = ("ITA 2025", "234B")
KEY_AIS: Final[tuple[str, str]] = ("CBDT Circular", "AIS-2024")


def _digest(*parts: object) -> str:
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _inr(label: str, value: float, engine: str) -> NumberFact:
    return NumberFact(label=label, value=float(value), source_engine=engine)


def _count(label: str, value: float, engine: str) -> NumberFact:
    return NumberFact(label=label, value=float(value), source_engine=engine, unit="COUNT")


def gather(result: IntentResult) -> Facts:
    """Dispatch ``result.intent`` to its engine handler."""
    if not result.is_supported:
        return Facts(
            intent=result.intent,
            refusal=RefusalCode.OUT_OF_SCOPE,
            refusal_detail=result.reason or "no supported topic matched",
        )
    handler = _HANDLERS.get(result.intent)
    if handler is None:  # pragma: no cover - enum/handler drift guard
        return Facts(
            intent=result.intent,
            refusal=RefusalCode.OUT_OF_SCOPE,
            refusal_detail="intent not wired to an engine",
        )
    try:
        return handler(result.slots)
    except Exception as exc:  # engines must never 500 the request
        return Facts(
            intent=result.intent,
            refusal=RefusalCode.INSUFFICIENT_DATA,
            refusal_detail=f"engine error: {type(exc).__name__}: {exc}",
        )


# --------------------------------------------------------------------------- #
# Shared data access (imported lazily: intel must stay import-side-effect free)
# --------------------------------------------------------------------------- #

def _ledger() -> tuple[list[dict[str, Any]], float]:
    import database

    invoices: list[dict[str, Any]] = [dict(i) for i in database.get_invoices(include_inactive=False)]
    total = sum(float(i["amount"]) for i in invoices)
    return invoices, total


def _tax_summary(total: float) -> dict[str, Any]:
    import tax_rules

    return dict(tax_rules.calculate_44ada_tax(total))


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #

def _gst_threshold(slots: dict[str, object]) -> Facts:
    import forecast_engine
    import tax_rules

    invoices, total = _ledger()
    limit = float(tax_rules.TOTAL_GST_LIMIT)
    headroom = max(0.0, limit - total)
    engine = forecast_engine.ForecastEngine()  # type: ignore[no-untyped-call]
    forecast = dict(engine.forecast_gst_crossing(invoices))

    data_signal = 1.0 if len(invoices) >= 3 else (0.6 if invoices else 0.2)
    predicted_date = forecast.get("predicted_date")
    notes = (f"Forecast crossing date: {predicted_date}",) if predicted_date else ()
    return Facts(
        intent=Intent.GST_THRESHOLD,
        numbers=(
            _inr("turnover", total, "database.get_invoices"),
            _inr("gst_limit", limit, "tax_rules.TOTAL_GST_LIMIT"),
            _inr("headroom", headroom, "tax_rules.TOTAL_GST_LIMIT"),
            _count("invoice_count", float(len(invoices)), "database.get_invoices"),
        ),
        rules_fired=(
            RuleFired("tax_rules", "TOTAL_GST_LIMIT", args_digest=_digest(limit)),
            RuleFired(
                "forecast_engine",
                "forecast_gst_crossing",
                args_digest=_digest(len(invoices), round(total, 2)),
            ),
        ),
        citation_keys=(KEY_GST,),
        signals={"completeness": data_signal, "forecast": data_signal},
        notes=notes,
    )


def _regime_compare(slots: dict[str, object]) -> Facts:
    invoices, total = _ledger()
    summary = _tax_summary(total)
    new_tax = float(summary.get("new_regime_tax", 0.0) or 0.0)
    old_tax = float(summary.get("old_regime_tax", 0.0) or 0.0)
    savings = abs(new_tax - old_tax)

    data_signal = 1.0 if invoices else 0.35
    return Facts(
        intent=Intent.REGIME_COMPARE,
        numbers=(
            _inr("turnover", total, "database.get_invoices"),
            _inr("presumptive_income", float(summary.get("presumptive_income", 0.0) or 0.0), "tax_rules.calculate_44ada_tax"),
            _inr("new_regime_tax", new_tax, "tax_rules.calculate_44ada_tax"),
            _inr("old_regime_tax", old_tax, "tax_rules.calculate_44ada_tax"),
            _inr("tax_savings", savings, "tax_rules.calculate_44ada_tax"),
        ),
        rules_fired=(
            RuleFired("tax_rules", "calculate_44ada_tax", args_digest=_digest(round(total, 2))),
            RuleFired("tax_rules", "calculate_new_regime_tax"),
            RuleFired("tax_rules", "calculate_old_regime_tax"),
        ),
        citation_keys=(KEY_44ADA,),
        signals={"completeness": data_signal, "classifier": data_signal},
        notes=(str(summary.get("preferred_regime", "new")),),
    )


def _advance_tax(slots: dict[str, object]) -> Facts:
    import tax_rules

    _, total = _ledger()
    summary = _tax_summary(total)
    estimated = float(summary.get("new_regime_tax", 0.0) or 0.0)
    upcoming = dict(tax_rules.get_upcoming_advance_tax(estimated))

    return Facts(
        intent=Intent.ADVANCE_TAX,
        numbers=(
            _inr("estimated_tax", estimated, "tax_rules.calculate_44ada_tax"),
            _inr("cumulative_due", float(upcoming.get("cumulative_due", 0.0) or 0.0), "tax_rules.get_upcoming_advance_tax"),
            _inr("turnover", total, "database.get_invoices"),
            NumberFact(
                label="instalment_percent",
                value=float(upcoming.get("percent", 0.0) or 0.0),
                source_engine="tax_rules.get_upcoming_advance_tax",
                unit="PERCENT",
            ),
        ),
        rules_fired=(
            RuleFired("tax_rules", "get_upcoming_advance_tax", args_digest=_digest(round(estimated, 2))),
        ),
        citation_keys=(KEY_ADVANCE,),
        signals={"completeness": 1.0, "forecast": 0.7 if total else 0.3},
        notes=(str(upcoming.get("installment", "")), str(upcoming.get("due_date", ""))),
    )


def _tds_rate(slots: dict[str, object]) -> Facts:
    import tds_engine

    nature = "professional fees"
    section = slots.get("section")
    if isinstance(section, str):
        nature = f"section {section}"

    info = dict(tds_engine.verify_tds_rate(nature))
    rate = float(info.get("rate_pct", 0.0) or 0.0)

    return Facts(
        intent=Intent.TDS_RATE,
        numbers=(
            NumberFact(
                label="tds_rate",
                value=rate,
                source_engine="tds_engine.verify_tds_rate",
                unit="PERCENT",
            ),
        ),
        rules_fired=(RuleFired("tds_engine", "verify_tds_rate", args_digest=_digest(nature)),),
        citation_keys=(KEY_TDS,),
        signals={"completeness": 1.0},
        notes=(str(info.get("section", "")), str(info.get("notes", ""))),
    )


def _deduction_44ada(slots: dict[str, object]) -> Facts:
    invoices, total = _ledger()
    requested = slots.get("amount")
    if isinstance(requested, (float, int)) and requested > 0:
        gross = float(requested)
        source = "query"
    else:
        gross = total
        source = "ledger"

    summary = _tax_summary(gross)
    data_signal = 1.0 if invoices or source == "query" else 0.3
    return Facts(
        intent=Intent.DEDUCTION_44ADA,
        numbers=(
            _inr("gross_receipts", gross, "database.get_invoices" if source == "ledger" else "query"),
            _inr("presumptive_income", float(summary.get("presumptive_income", 0.0) or 0.0), "tax_rules.calculate_44ada_tax"),
            _inr("new_regime_tax", float(summary.get("new_regime_tax", 0.0) or 0.0), "tax_rules.calculate_44ada_tax"),
        ),
        rules_fired=(RuleFired("tax_rules", "calculate_44ada_tax", args_digest=_digest(round(gross, 2))),),
        citation_keys=(KEY_44ADA, KEY_44AD),
        signals={"completeness": data_signal, "classifier": data_signal},
        notes=("limit exceeded" if summary.get("limit_exceeded") else "within the 44ADA cash ceiling",),
    )


def _ais_mismatch(slots: dict[str, object]) -> Facts:
    import ais_engine
    import database

    invoices, total = _ledger()
    ais_entries = list(database.get_ais_entries())
    if not ais_entries:
        return Facts(
            intent=Intent.AIS_MISMATCH,
            refusal=RefusalCode.INSUFFICIENT_DATA,
            refusal_detail="no AIS entries are loaded for this ledger",
        )

    result = dict(ais_engine.reconcile(invoices, ais_entries))
    confidence_pct = float(result.get("confidence_pct", 0.0) or 0.0)
    variance = float(result.get("variance_inr", 0.0) or 0.0)
    unmatched_ais = len(result.get("unmatched_in_ais", []) or [])
    unmatched_books = len(result.get("unmatched_in_books", []) or [])

    return Facts(
        intent=Intent.AIS_MISMATCH,
        numbers=(
            _inr("book_turnover", total, "database.get_invoices"),
            _inr("ais_total", float(result.get("total_ais", 0.0) or 0.0), "ais_engine.reconcile"),
            _inr("variance", variance, "ais_engine.reconcile"),
            _count("unmatched_in_ais", float(unmatched_ais), "ais_engine.reconcile"),
            _count("unmatched_in_books", float(unmatched_books), "ais_engine.reconcile"),
        ),
        rules_fired=(
            RuleFired(
                "ais_engine",
                "reconcile",
                args_digest=_digest(len(invoices), len(ais_entries), round(variance, 2)),
            ),
        ),
        citation_keys=(KEY_AIS,),
        signals={"ais_match": confidence_pct / 100.0, "completeness": 1.0},
    )


def _invoice_review(slots: dict[str, object]) -> Facts:
    import database
    import tax_rules

    invoice_id = slots.get("invoice_id")
    invoices, _ = _ledger()
    all_invoices: list[dict[str, Any]] = [dict(i) for i in database.get_invoices(include_inactive=True)]

    match: dict[str, Any] | None = None
    if isinstance(invoice_id, int):
        match = next((i for i in all_invoices if int(i["id"]) == invoice_id), None)
    else:
        vendor = slots.get("vendor")
        if isinstance(vendor, str):
            needle = vendor.lower()
            match = next((i for i in all_invoices if str(i["vendor"]).lower() == needle), None)
        else:
            flagged = [i for i in invoices if int(i["is_anomaly"]) == 1]
            match = flagged[0] if flagged else None

    if match is None:
        return Facts(
            intent=Intent.INVOICE_REVIEW,
            refusal=RefusalCode.INSUFFICIENT_DATA,
            refusal_detail="no matching invoice in the local ledger",
        )

    amount = float(match["amount"])
    is_anomaly = bool(int(match["is_anomaly"]))
    peers = [i for i in invoices if i is not match] or invoices
    recomputed = bool(tax_rules.check_anomaly(str(match["vendor"]), amount, peers))

    evidence = (
        EvidenceRef(kind="invoice", ref_id=str(match["id"]), hash=str(match.get("merkle_leaf") or "") or None),
    )
    return Facts(
        intent=Intent.INVOICE_REVIEW,
        numbers=(
            _inr("invoice_amount", amount, "database.get_invoices"),
            _count("invoice_id", float(int(match["id"])), "database.get_invoices"),
        ),
        rules_fired=(
            RuleFired(
                "tax_rules",
                "check_anomaly",
                args_digest=_digest(str(match["vendor"]), round(amount, 2), len(peers)),
            ),
        ),
        citation_keys=(),
        signals={"completeness": 1.0, "ais_match": 0.8},
        notes=("rule flagged this invoice as an outlier" if (is_anomaly or recomputed) else "no anomaly rule fired",),
        evidence=evidence,
    )


def _cash_flow(slots: dict[str, object]) -> Facts:
    import forecast_engine

    invoices, total = _ledger()
    engine = forecast_engine.ForecastEngine()  # type: ignore[no-untyped-call]
    cash = dict(engine.forecast_cash_flow(invoices))
    penalties = dict(engine.forecast_penalties(invoices))

    paths = cash.get("paths") or []
    lowest = min((min(p) for p in paths if p), default=0.0)

    return Facts(
        intent=Intent.CASH_FLOW,
        numbers=(
            _inr("turnover", total, "database.get_invoices"),
            _inr("lowest_projected_balance", float(lowest), "forecast_engine.forecast_cash_flow"),
            _inr("expected_penalty", float(penalties.get("expected_penalty_inr", 0.0) or 0.0), "forecast_engine.forecast_penalties"),
            NumberFact(
                label="liquidity_risk_percent",
                value=float(cash.get("liquidity_risk_pct", 0.0) or 0.0),
                source_engine="forecast_engine.forecast_cash_flow",
                unit="PERCENT",
            ),
        ),
        rules_fired=(
            RuleFired("forecast_engine", "forecast_cash_flow", args_digest=_digest(len(invoices))),
            RuleFired("forecast_engine", "forecast_penalties", args_digest=_digest(len(invoices))),
        ),
        citation_keys=(KEY_PENALTY,),
        signals={"forecast": 1.0 if len(invoices) >= 3 else 0.5, "completeness": 1.0 if invoices else 0.3},
    )


def _simulate(slots: dict[str, object]) -> Facts:
    from intel import simulator

    amount = slots.get("amount")
    gross = float(amount) if isinstance(amount, (float, int)) else None
    return simulator.simulate(gross_receipts=gross)


Handler = Callable[[dict[str, object]], Facts]

_HANDLERS: Final[dict[Intent, Handler]] = {
    Intent.GST_THRESHOLD: _gst_threshold,
    Intent.REGIME_COMPARE: _regime_compare,
    Intent.ADVANCE_TAX: _advance_tax,
    Intent.TDS_RATE: _tds_rate,
    Intent.DEDUCTION_44ADA: _deduction_44ada,
    Intent.AIS_MISMATCH: _ais_mismatch,
    Intent.INVOICE_REVIEW: _invoice_review,
    Intent.CASH_FLOW: _cash_flow,
    Intent.SIMULATE: _simulate,
}

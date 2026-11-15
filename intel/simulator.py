"""What-if simulation sandbox (milestone M4, used by M3 orchestrator).

The simulator evaluates hypothetical revenue/receipt scenarios against the
deterministic tax rules without altering the ledger.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from intel.envelope import EvidenceRef, NumberFact, RuleFired
from intel.intent import Intent

if TYPE_CHECKING:
    from intel.orchestrator import Facts

KEY_44ADA: Final[tuple[str, str]] = ("ITA 2025", "44ADA")


def simulate(gross_receipts: float | None = None) -> Facts:
    from intel.orchestrator import Facts, _digest, _inr, _ledger, _tax_summary

    if gross_receipts is None:
        _, gross = _ledger()
        if gross <= 0.0:
            gross = 5_000_000.0  # ₹50L standard simulation baseline if ledger is empty
    else:
        gross = float(gross_receipts)

    summary = _tax_summary(gross)
    new_tax = float(summary.get("new_regime_tax", 0.0) or 0.0)
    old_tax = float(summary.get("old_regime_tax", 0.0) or 0.0)
    presumptive = float(summary.get("presumptive_income", 0.0) or 0.0)
    diff = abs(new_tax - old_tax)

    return Facts(
        intent=Intent.SIMULATE,
        numbers=(
            _inr("simulated_turnover", gross, "simulator.simulate"),
            _inr("simulated_presumptive_income", presumptive, "tax_rules.calculate_44ada_tax"),
            _inr("simulated_new_regime_tax", new_tax, "tax_rules.calculate_44ada_tax"),
            _inr("simulated_old_regime_tax", old_tax, "tax_rules.calculate_44ada_tax"),
            _inr("simulated_savings", diff, "tax_rules.calculate_44ada_tax"),
        ),
        rules_fired=(
            RuleFired("tax_rules", "calculate_44ada_tax", args_digest=_digest(round(gross, 2))),
            RuleFired("tax_rules", "calculate_new_regime_tax"),
            RuleFired("tax_rules", "calculate_old_regime_tax"),
        ),
        citation_keys=(KEY_44ADA,),
        signals={"completeness": 1.0, "forecast": 0.8},
        notes=(
            f"Simulated gross receipts of {gross:,.2f}",
            str(summary.get("preferred_regime", "new")),
        ),
    )

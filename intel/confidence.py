"""Calibrated confidence fusion (milestones M2 stub → M6 complete).

Confidence is a **weighted sum of independent signals**, never a model score
and never a language-model opinion. Missing signals contribute zero rather
than being renormalised away, so an answer built on partial evidence is
*visibly* less confident.

The weights are a public contract: tests assert them, and changing them is a
deliberate calibration decision recorded in ARCHITECTURE §8.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from intel.envelope import Band

#: Signal weights. Must sum to 1.0; asserted at import time.
WEIGHTS: Final[dict[str, float]] = {
    "ais_match": 0.30,      # quality of AIS ↔ books reconciliation
    "classifier": 0.25,     # classifier certainty for the activity
    "forecast": 0.15,       # forecast residual / data adequacy
    "rag": 0.20,            # citation retrieval quality
    "completeness": 0.10,   # required inputs present
}

if abs(sum(WEIGHTS.values()) - 1.0) > 1e-9:  # pragma: no cover - contract guard
    raise AssertionError("confidence weights must sum to 1.0")


@dataclass(frozen=True, slots=True)
class Signal:
    """One contributing signal, normalised to 0..1."""

    name: str
    score: float
    weight: float

    @property
    def contribution(self) -> float:
        return self.weight * self.score


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    """Fused score plus the evidence used to produce it."""

    score: int
    band: Band
    signals: tuple[Signal, ...]
    coverage: float

    @property
    def explanation(self) -> str:
        parts = [f"{s.name}={s.score:.2f}x{s.weight:.2f}" for s in self.signals]
        return f"score={self.score} band={self.band.value} coverage={self.coverage:.2f} [{', '.join(parts)}]"


def clamp01(value: float) -> float:
    """Clamp to the closed unit interval, rejecting NaN."""
    if value != value:  # NaN
        return 0.0
    return max(0.0, min(1.0, float(value)))


def fuse(
    scores: Mapping[str, float],
    *,
    weights: Mapping[str, float] = WEIGHTS,
) -> ConfidenceResult:
    """Fuse named signal scores into ``(score, band, signals)``.

    Parameters
    ----------
    scores:
        Mapping of signal name → score in 0..1. Unknown names raise
        :class:`ValueError` (a typo must not silently weaken confidence).
    weights:
        Override for tests/experiments; must cover every key used.
    """
    unknown = set(scores) - set(weights)
    if unknown:
        raise ValueError(f"unknown confidence signals: {sorted(unknown)}")

    signals: list[Signal] = []
    total = 0.0
    coverage = 0.0
    for name, weight in weights.items():
        if name in scores:
            score = clamp01(scores[name])
            coverage += weight
        else:
            score = 0.0
        signals.append(Signal(name=name, score=score, weight=weight))
        total += weight * score

    score_int = int(round(100 * total))
    return ConfidenceResult(
        score=score_int,
        band=Band.from_score(score_int),
        signals=tuple(signals),
        coverage=round(coverage, 4),
    )


def single(signal: str, score: float) -> ConfidenceResult:
    """Convenience wrapper used when only one signal is meaningful."""
    return fuse({signal: score})

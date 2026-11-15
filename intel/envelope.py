"""The answer contract (milestone M2).

Every intelligence-layer response — successful or refused — is an
:class:`Envelope`. The envelope is the *only* thing the API returns and the
only thing the UI renders, which makes guardrails enforceable in one place:

* every number the narrator may mention lives in :attr:`Envelope.numbers`;
* every legal claim must resolve to an entry in :attr:`Envelope.citations`;
* a refusal is a valid envelope with ``band=REFUSED`` and a reason.

Invariants are checked in ``__post_init__`` so an invalid envelope cannot be
constructed, serialized, or persisted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

#: Confidence thresholds. ``score >= 80`` is high, ``>= 50`` medium, else low.
HIGH_THRESHOLD: Final[int] = 80
MEDIUM_THRESHOLD: Final[int] = 50


class Band(str, Enum):
    """Calibrated confidence band attached to every answer."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    REFUSED = "refused"

    @classmethod
    def from_score(cls, score: int) -> "Band":
        if score >= HIGH_THRESHOLD:
            return cls.HIGH
        if score >= MEDIUM_THRESHOLD:
            return cls.MEDIUM
        return cls.LOW

    @property
    def allows_answer(self) -> bool:
        """True when the band permits narrating an answer."""
        return self is not Band.REFUSED


class RefusalCode(str, Enum):
    """Structured reasons for declining to answer (ARCHITECTURE §9)."""

    NO_CITATION = "NO_CITATION"
    NUMERIC_MISMATCH = "NUMERIC_MISMATCH"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class Citation:
    """A verifiable pointer into the local corpus."""

    source: str
    section: str
    title: str | None = None
    url: str | None = None
    provisional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "section": self.section,
            "title": self.title,
            "url": self.url,
            "provisional": self.provisional,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Citation":
        return cls(
            source=str(data["source"]),
            section=str(data["section"]),
            title=None if data.get("title") is None else str(data["title"]),
            url=None if data.get("url") is None else str(data["url"]),
            provisional=bool(data.get("provisional", False)),
        )


@dataclass(frozen=True, slots=True)
class RuleFired:
    """Provenance for one deterministic engine call."""

    engine: str
    fn: str
    version: str = "1.0"
    args_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "fn": self.fn,
            "version": self.version,
            "args_digest": self.args_digest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleFired":
        return cls(
            engine=str(data["engine"]),
            fn=str(data["fn"]),
            version=str(data.get("version", "1.0")),
            args_digest=str(data.get("args_digest", "")),
        )


@dataclass(frozen=True, slots=True)
class NumberFact:
    """A single number the narrator is allowed to mention."""

    label: str
    value: float
    source_engine: str
    unit: str = "INR"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "source_engine": self.source_engine,
            "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NumberFact":
        return cls(
            label=str(data["label"]),
            value=float(data["value"]),
            source_engine=str(data["source_engine"]),
            unit=str(data.get("unit", "INR")),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Pointer to tamper-evident evidence backing the answer."""

    kind: str
    ref_id: str
    hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref_id": self.ref_id, "hash": self.hash}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRef":
        return cls(
            kind=str(data["kind"]),
            ref_id=str(data["ref_id"]),
            hash=None if data.get("hash") is None else str(data["hash"]),
        )


@dataclass(frozen=True, slots=True)
class Envelope:
    """A complete, auditable answer."""

    query: str
    answer: str
    citations: tuple[Citation, ...] = ()
    rules_fired: tuple[RuleFired, ...] = ()
    numbers: tuple[NumberFact, ...] = ()
    confidence: int = 0
    band: Band = Band.LOW
    human_review_required: bool = True
    refusal_reason: RefusalCode | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    intent: str = ""
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 100:
            raise ValueError(f"confidence must be 0..100, got {self.confidence}")
        if self.band is Band.REFUSED and self.refusal_reason is None:
            raise ValueError("a refused envelope must carry a refusal_reason")
        if self.band is not Band.REFUSED and self.refusal_reason is not None:
            raise ValueError("only refused envelopes may carry a refusal_reason")
        if self.band is not Band.HIGH and not self.human_review_required:
            raise ValueError("non-high confidence must require human review")

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "rules_fired": [r.to_dict() for r in self.rules_fired],
            "numbers": [n.to_dict() for n in self.numbers],
            "confidence": self.confidence,
            "band": self.band.value,
            "human_review_required": self.human_review_required,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "evidence_refs": [e.to_dict() for e in self.evidence_refs],
            "intent": self.intent,
            "created_at": self.created_at,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        refusal = data.get("refusal_reason")
        return cls(
            query=str(data.get("query", "")),
            answer=str(data.get("answer", "")),
            citations=tuple(Citation.from_dict(c) for c in data.get("citations", [])),
            rules_fired=tuple(RuleFired.from_dict(r) for r in data.get("rules_fired", [])),
            numbers=tuple(NumberFact.from_dict(n) for n in data.get("numbers", [])),
            confidence=int(data.get("confidence", 0)),
            band=Band(str(data.get("band", "low"))),
            human_review_required=bool(data.get("human_review_required", True)),
            refusal_reason=None if refusal is None else RefusalCode(str(refusal)),
            evidence_refs=tuple(EvidenceRef.from_dict(e) for e in data.get("evidence_refs", [])),
            intent=str(data.get("intent", "")),
            created_at=str(data.get("created_at", _now())),
        )

    @classmethod
    def from_json(cls, payload: str) -> "Envelope":
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise ValueError("envelope JSON must be an object")
        return cls.from_dict(parsed)

    # -- guardrail helpers ------------------------------------------------

    def numeric_values(self) -> tuple[float, ...]:
        """Every number a narrator is allowed to state."""
        return tuple(n.value for n in self.numbers)

    @property
    def is_refusal(self) -> bool:
        return self.band is Band.REFUSED


def refusal(
    query: str,
    reason: RefusalCode,
    answer: str,
    *,
    intent: str = "",
    confidence: int = 0,
    citations: tuple[Citation, ...] = (),
    rules_fired: tuple[RuleFired, ...] = (),
    numbers: tuple[NumberFact, ...] = (),
) -> Envelope:
    """Build a well-formed refusal envelope."""
    return Envelope(
        query=query,
        answer=answer,
        citations=citations,
        rules_fired=rules_fired,
        numbers=numbers,
        confidence=max(0, min(100, confidence)),
        band=Band.REFUSED,
        human_review_required=True,
        refusal_reason=reason,
        intent=intent,
    )

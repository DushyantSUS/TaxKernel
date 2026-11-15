"""High-level intelligence service coordinator (milestone M7).

Orchestrates the query lifecycle:
  classify -> gather facts -> resolve citations -> fuse confidence -> narrate -> persist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intel.confidence import ConfidenceResult, fuse
from intel.envelope import Citation, Envelope, RefusalCode, refusal
from intel.intent import classify
from intel.narrator import narrate
from intel.orchestrator import Facts, gather
from intel.rag import resolve_keys, search
from intel.simulator import simulate as run_simulation
from intel.storage import get_answer, list_answers, save_answer


def ask(query: str, user_id: int = 1, taxpayer_id: int | None = None) -> Envelope:
    """Answer a user query with full auditable proof and persist the result."""
    intent_res = classify(query)
    facts = gather(intent_res)

    # 1. Resolve citations
    citations: tuple[Citation, ...] = ()
    if facts.citation_keys:
        resolved = resolve_keys(facts.citation_keys)
        if resolved is None:
            # Mandated statutory citation could not be verified in local corpus
            env = refusal(
                query=query,
                reason=RefusalCode.NO_CITATION,
                answer="Statutory citations required for this query could not be verified in the local corpus.",
                intent=facts.intent.value,
                confidence=0,
                rules_fired=facts.rules_fired,
                numbers=facts.numbers,
            )
            save_answer(env, user_id=user_id, taxpayer_id=taxpayer_id)
            return env
        citations = resolved
    else:
        # Semantic search for general context
        corpus_hits = search(query, limit=2)
        citations = tuple(corpus_hits)

    # 2. Fuse confidence
    signals = dict(facts.signals)
    if "rag" not in signals:
        signals["rag"] = 1.0 if citations else 0.4
    if "completeness" not in signals:
        signals["completeness"] = 1.0 if facts.numbers else 0.5

    try:
        conf_result = fuse(signals)
    except ValueError:
        # Default safe fusion if unmapped signals appear
        conf_result = fuse({"completeness": 0.5})

    # 3. Narrate with numeric guardrails
    envelope = narrate(query, facts, conf_result, citations=citations)

    # 4. Durable persistence
    save_answer(envelope, user_id=user_id, taxpayer_id=taxpayer_id)
    return envelope


def simulate(gross_receipts: float | None = None, user_id: int = 1) -> Envelope:
    """Run a hypothetical simulation scenario and persist the envelope."""
    facts = run_simulation(gross_receipts)
    query = f"Simulate tax liability for gross receipts {gross_receipts}" if gross_receipts else "Simulate tax scenario"

    citations: tuple[Citation, ...] = ()
    if facts.citation_keys:
        resolved = resolve_keys(facts.citation_keys)
        if resolved:
            citations = resolved

    conf_result = fuse({
        "completeness": 1.0,
        "forecast": 0.9,
        "classifier": 1.0,
        "rag": 1.0 if citations else 0.5,
        "ais_match": 1.0,
    })
    envelope = narrate(query, facts, conf_result, citations=citations)
    save_answer(envelope, user_id=user_id)
    return envelope

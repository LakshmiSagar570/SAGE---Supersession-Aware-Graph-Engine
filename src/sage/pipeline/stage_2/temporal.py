"""
Stage 2 — Temporal Reasoning.

Responsibility: enrich a list of Facts with temporal information.

    list[Fact]
        |
        v
   enrich_temporally()
        |
        v
    list[Fact]

Stage 2 does NOT extract new facts, merge facts, delete facts, resolve
contradictions, determine authority, change confidence, change status,
alter subject/predicate/object, alter source/evidence, persist anything,
or perform any Stage 3+ responsibility.

Critical mutation contract (behavioral, not enforced by stage_io.py):

    MAY change:      effective_from, effective_to, metadata
                      (metadata: temporal-related information only)

    MUST preserve exactly, unchanged:
                      fact_id, subject, predicate, object, source,
                      evidence, extracted_at, confidence, status

Cardinality is preserved: exactly one output Fact per input Fact. No
deduplication, deletion, creation, merging, or splitting — that
includes the two Maria Chen CEO facts, which Stage 2 must never
conclude are the same claim or that one supersedes the other. That
determination belongs to Stage 3 (contradiction detection) and beyond.

v0.1 is deliberately conservative: it reasons about temporal boundaries
only where the available facts actually provide evidence for them. It
never invents or guesses a date. Against an input of isolated,
mutually-unrelated facts (no shared subject/predicate pairing that
would justify a relational temporal inference), correctness looks like
leaving effective_from/effective_to exactly as Stage 1 produced them —
that is the "leave it unchanged rather than guess" rule in action, not
an unimplemented stage.

Facts are never mutated in place. Each output Fact is a new Pydantic
instance built via .model_copy(), which is what makes "the untouched
fields are structurally guaranteed unchanged" a property of the
approach rather than something individually re-typed per field.
"""

from __future__ import annotations

from contracts.fact_schema import Fact

# Locked list of temporal-metadata keys Stage 2 is allowed to write.
# Nothing else may be added to a Fact's metadata dict here — per spec,
# arbitrary Stage 2 bookkeeping does not belong in metadata, and
# unrelated metadata that Stage 1 (or a future upstream stage) may
# provide must never be touched.
_TEMPORAL_METADATA_KEYS = frozenset(
    {
        "temporal_reasoning_source",
        "temporal_inference_type",
        "temporal_relationship",
    }
)


def enrich_temporally(facts: list[Fact]) -> list[Fact]:
    """Enrich each Fact with temporal reasoning, preserving all
    non-temporal fields exactly and preserving cardinality.

    Empty input returns empty output.
    """
    return [_enrich_single_fact(fact, facts) for fact in facts]


def _enrich_single_fact(fact: Fact, all_facts: list[Fact]) -> Fact:
    """Produce an enriched copy of a single Fact.

    `all_facts` is passed through so that future, more capable temporal
    reasoning (relating one fact to others sharing its subject) has
    what it needs without changing this function's signature. v0.1
    does not yet perform cross-fact relational inference — see module
    docstring — so the only currently-implemented rule inspects the
    fact in isolation.
    """
    del all_facts  # Reserved for future cross-fact temporal reasoning.

    updates = _determine_temporal_updates(fact)
    if not updates:
        return fact.model_copy(deep=True)

    return fact.model_copy(deep=True, update=updates)


def _determine_temporal_updates(fact: Fact) -> dict[str, object]:
    """Decide what, if anything, Stage 2 should change on this Fact.

    v0.1 policy: a Fact's effective_from is either already grounded in
    an explicit date from Stage 1 extraction, or it fell back to
    extracted_at because no explicit date existed in the source text.
    Neither case gives Stage 2 new evidence to act on by itself — there
    is no legitimate inference to draw from a single isolated fact that
    Stage 1 hasn't already captured. So v0.1 returns no updates.

    This function is intentionally the single seam where future
    relational temporal logic would be added, so that behavior change
    stays localized to one place rather than scattered through
    enrich_temporally's iteration logic.
    """
    return {}
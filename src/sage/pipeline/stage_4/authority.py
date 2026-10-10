"""
Stage 4 — Authority Inference.

Responsibility: determine the relative authority of sources that
actually participate in contradictions detected by Stage 3.

    facts: list[Fact]
    contradictions: list[ContradictionSet]
            |
            v
    infer_authority()
            |
            v
    list[AuthorityAssessment]

Stage 4 does NOT detect contradictions (Stage 3's job), modify Facts,
modify ContradictionSets, resolve which fact is correct (Stage 5's
job), write to Neo4j (Stage 6's job), or infer temporal relationships.

--------------------------------------------------------------------
AUTHORITY POLICY

The actual ranking implemented here is documented as a standalone
design decision in docs/authority_policy.md — not invented in this
file. That document is authoritative; if this code and that document
ever diverge, the document is correct and this code has a bug.

Summary (see the doc for full rationale): v0.1 authority is
source-type-based only.

    DATABASE > DOCUMENT > API > WEB > OTHER

    DATABASE  1.00
    DOCUMENT  0.80
    API       0.60
    WEB       0.40
    OTHER     0.20

authority_score is a policy-weighted value, not a truth probability —
see docs/authority_policy.md, "What this score means".

The policy table lives in exactly one function, _POLICY_SCORES /
_source_type_score(), so a future, more sophisticated policy can
replace it without touching orchestration, deduplication, or
assessment-construction logic anywhere else in this module.
--------------------------------------------------------------------

Assessment identity is per-source, not per-fact or per-contradiction:
a source that participates in multiple contradictions still receives
exactly one AuthorityAssessment. Only sources that actually appear in
at least one ContradictionSet's conflicting facts are assessed —
Stage 4 does not manufacture assessments for uninvolved sources.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.fact_schema import (
    AuthorityAssessment,
    ContradictionSet,
    Fact,
    FactID,
    Source,
    SourceID,
    SourceType,
)

# The v0.1 authority policy table. See docs/authority_policy.md for the
# full design rationale — this is the implementation of that document,
# not an independent decision made here.
_POLICY_SCORES: dict[SourceType, float] = {
    SourceType.DATABASE: 1.00,
    SourceType.DOCUMENT: 0.80,
    SourceType.API: 0.60,
    SourceType.WEB: 0.40,
    SourceType.OTHER: 0.20,
}


def infer_authority(
    facts: list[Fact], contradictions: list[ContradictionSet]
) -> list[AuthorityAssessment]:
    """Produce one AuthorityAssessment per source actually participating
    in a contradiction.

    Facts and contradictions are only read, never mutated. If
    contradictions is empty, returns an empty list — Stage 4 does not
    manufacture assessments when there's nothing to assess authority
    for.
    """
    if not contradictions:
        return []

    assessed_at = datetime.now(UTC)
    facts_by_id = _index_facts_by_id(facts)
    participating_sources = _sources_in_contradictions(contradictions, facts_by_id)

    return [
        _build_assessment(source, assessed_at)
        for source in _deduplicated_sorted(participating_sources)
    ]


def _index_facts_by_id(facts: list[Fact]) -> dict[FactID, Fact]:
    """Build a lookup so contradiction fact_ids can be resolved back to
    their Source without repeated linear scans."""
    return {fact.fact_id: fact for fact in facts}


def _sources_in_contradictions(
    contradictions: list[ContradictionSet],
    facts_by_id: dict[FactID, Fact],
) -> list[Source]:
    """Collect every Source belonging to a fact that participates in at
    least one contradiction. May contain duplicates — deduplication
    happens separately in _deduplicated_sorted, keeping "which sources
    are involved" and "how we make that a unique, ordered set" as two
    distinct, individually-testable concerns.
    """
    sources: list[Source] = []
    for contradiction in contradictions:
        for fact_id in contradiction.conflicting_fact_ids:
            fact = facts_by_id.get(fact_id)
            if fact is not None:
                sources.append(fact.source)
    return sources


def _deduplicated_sorted(sources: list[Source]) -> list[Source]:
    """Reduce to one entry per unique source_id, in deterministic order.

    Source is a Pydantic model and may not be hashable depending on its
    fields, so deduplication goes through source_id (a str-based
    SourceID) as the key rather than attempting set(sources) directly —
    the same pattern used in pairing.py's fact-pair deduplication, for
    the same reason.
    """
    seen: dict[SourceID, Source] = {}
    for source in sources:
        if source.source_id not in seen:
            seen[source.source_id] = source
    return [seen[source_id] for source_id in sorted(seen, key=str)]


def _build_assessment(source: Source, assessed_at: datetime) -> AuthorityAssessment:
    """Construct one AuthorityAssessment for a source, per the v0.1
    policy in docs/authority_policy.md."""
    return AuthorityAssessment(
        source_id=source.source_id,
        authority_score=_source_type_score(source.source_type),
        rationale=_rationale_for(source.source_type),
        assessed_at=assessed_at,
    )


def _source_type_score(source_type: SourceType) -> float:
    """Look up this source type's score under the v0.1 policy.

    This is the one place the policy table is consulted. If SourceType
    ever gains a new member without a corresponding policy entry, this
    raises rather than silently defaulting to some score — a missing
    policy entry is a contract/policy-document mismatch that needs
    human attention, not something to paper over.
    """
    try:
        return _POLICY_SCORES[source_type]
    except KeyError as exc:
        raise ValueError(
            f"No v0.1 authority policy score defined for SourceType "
            f"{source_type!r}. Update docs/authority_policy.md and "
            f"_POLICY_SCORES together — do not add a score here without "
            f"updating the policy document, or the two will diverge."
        ) from exc


def _rationale_for(source_type: SourceType) -> str:
    """Rationale describes the BASIS of the assessment (which policy,
    which source type), never a resolution ("X is correct"). See
    authority.py module docstring and docs/authority_policy.md,
    "Governing rules" #4 — Stage 4 does not resolve contradictions, so
    its rationale must not imply that it did.
    """
    return (
        f"Authority assigned under the SAGE v0.1 source-type authority "
        f"policy (see docs/authority_policy.md): SourceType.{source_type.value} "
        f"carries a policy-weighted score of {_POLICY_SCORES[source_type]:.2f}. "
        f"This reflects the v0.1 default policy ranking, not a "
        f"determination of factual correctness."
    )
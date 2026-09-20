"""
Stage 6 — Cypher Query Construction.

Responsibility: build Cypher query strings and their parameters from
Stage6Input data. No Neo4j driver calls happen here — this module is
pure string/data construction, testable without any database
connection.

Every write query uses MERGE (never CREATE) keyed on the contract's
own stable IDs, so repeated execution against the same logical entity
converges rather than duplicates. Every query batches its inputs via
UNWIND rather than expecting one call per entity — the caller
(materialize.py) passes a full list of dicts in one parameter, not one
query per row.

Organization: one CREATE-CONSTRAINT query per identity-bearing node
type, one MERGE query per node type (batched), and one MERGE query per
relationship type (batched). Each MERGE_* function returns
(cypher_string, parameters_dict) — materialize.py is responsible for
actually executing these inside a transaction.
"""

from __future__ import annotations

from contracts.fact_schema import (
    AuthorityAssessment,
    ContradictionSet,
    Fact,
    Resolution,
    Source,
)

# ---------------------------------------------------------------------------
# Constraints
#
# One uniqueness constraint per identity-bearing node type. Written with
# IF NOT EXISTS so they're safe to run every startup, not just once.
# AuthorityAssessment has no independent contract-level ID of its own —
# its identity is its source_id (Stage 4's "one assessment per source"
# invariant, re-validated in validate.py) — so its constraint is keyed
# on source_id rather than inventing a synthetic assessment ID.
# ---------------------------------------------------------------------------

CREATE_CONSTRAINTS: list[str] = [
    (
        "CREATE CONSTRAINT source_id_unique IF NOT EXISTS "
        "FOR (n:Source) REQUIRE n.source_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT fact_id_unique IF NOT EXISTS "
        "FOR (n:Fact) REQUIRE n.fact_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT contradiction_id_unique IF NOT EXISTS "
        "FOR (n:ContradictionSet) REQUIRE n.contradiction_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT resolution_id_unique IF NOT EXISTS "
        "FOR (n:Resolution) REQUIRE n.resolution_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT authority_assessment_source_id_unique IF NOT EXISTS "
        "FOR (n:AuthorityAssessment) REQUIRE n.source_id IS UNIQUE"
    ),
]


def merge_sources(sources: list[Source]) -> tuple[str, dict[str, object]]:
    """Batch-MERGE Source nodes, keyed on source_id."""
    query = (
        "UNWIND $sources AS source "
        "MERGE (s:Source {source_id: source.source_id}) "
        "SET s.name = source.name, "
        "s.source_type = source.source_type, "
        "s.locator = source.locator"
    )
    params: dict[str, object] = {
        "sources": [
            {
                "source_id": str(source.source_id),
                "name": source.name,
                "source_type": source.source_type.value,
                "locator": source.locator,
            }
            for source in sources
        ]
    }
    return query, params


def merge_facts(facts: list[Fact]) -> tuple[str, dict[str, object]]:
    """Batch-MERGE Fact nodes, keyed on fact_id.

    Per spec, no supersedes/superseded_by property is stored on Fact —
    that relationship lives entirely on Resolution's SUPERSEDES edges.
    effective_to is passed through as None when open-ended; Neo4j
    stores that as a null property rather than a sentinel value.
    """
    query = (
        "UNWIND $facts AS fact "
        "MERGE (f:Fact {fact_id: fact.fact_id}) "
        "SET f.subject = fact.subject, "
        "f.predicate = fact.predicate, "
        "f.object = fact.object, "
        "f.evidence = fact.evidence, "
        "f.extracted_at = fact.extracted_at, "
        "f.effective_from = fact.effective_from, "
        "f.effective_to = fact.effective_to, "
        "f.status = fact.status"
    )
    params: dict[str, object] = {
        "facts": [
            {
                "fact_id": str(fact.fact_id),
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object,
                "evidence": fact.evidence,
                "extracted_at": fact.extracted_at.isoformat(),
                "effective_from": fact.effective_from.isoformat(),
                "effective_to": (
                    fact.effective_to.isoformat()
                    if fact.effective_to is not None
                    else None
                ),
                "status": fact.status.value,
            }
            for fact in facts
        ]
    }
    return query, params


def merge_contradictions(
    contradictions: list[ContradictionSet],
) -> tuple[str, dict[str, object]]:
    """Batch-MERGE ContradictionSet nodes, keyed on contradiction_id.
    conflicting_fact_ids is NOT stored as a node property — those
    facts are represented via CONFLICTS relationships instead, so the
    grouping is queryable via graph traversal rather than duplicated
    as a property array."""
    query = (
        "UNWIND $contradictions AS c "
        "MERGE (cs:ContradictionSet {contradiction_id: c.contradiction_id}) "
        "SET cs.conflict_type = c.conflict_type, "
        "cs.detected_at = c.detected_at"
    )
    params: dict[str, object] = {
        "contradictions": [
            {
                "contradiction_id": str(c.contradiction_id),
                "conflict_type": c.conflict_type.value,
                "detected_at": c.detected_at.isoformat(),
            }
            for c in contradictions
        ]
    }
    return query, params


def merge_authority_assessments(
    assessments: list[AuthorityAssessment],
) -> tuple[str, dict[str, object]]:
    """Batch-MERGE AuthorityAssessment nodes, keyed on source_id (per
    spec: identity derived from source_id, since there's no independent
    assessment ID in the contract)."""
    query = (
        "UNWIND $assessments AS a "
        "MERGE (aa:AuthorityAssessment {source_id: a.source_id}) "
        "SET aa.authority_score = a.authority_score, "
        "aa.rationale = a.rationale, "
        "aa.assessed_at = a.assessed_at"
    )
    params: dict[str, object] = {
        "assessments": [
            {
                "source_id": str(a.source_id),
                "authority_score": a.authority_score,
                "rationale": a.rationale,
                "assessed_at": a.assessed_at.isoformat(),
            }
            for a in assessments
        ]
    }
    return query, params


def merge_resolutions(resolutions: list[Resolution]) -> tuple[str, dict[str, object]]:
    """Batch-MERGE Resolution nodes, keyed on resolution_id.
    superseded_fact_ids is NOT stored as a node property — represented
    via SUPERSEDES relationships instead, same reasoning as
    ContradictionSet's conflicting_fact_ids."""
    query = (
        "UNWIND $resolutions AS r "
        "MERGE (res:Resolution {resolution_id: r.resolution_id}) "
        "SET res.outcome = r.outcome, "
        "res.rationale = r.rationale, "
        "res.resolved_at = r.resolved_at, "
        "res.winning_fact_id = r.winning_fact_id"
    )
    params: dict[str, object] = {
        "resolutions": [
            {
                "resolution_id": str(r.resolution_id),
                "outcome": r.outcome.value,
                "rationale": r.rationale,
                "resolved_at": r.resolved_at.isoformat(),
                "winning_fact_id": (
                    str(r.winning_fact_id) if r.winning_fact_id is not None else None
                ),
            }
            for r in resolutions
        ]
    }
    return query, params


def merge_fact_source_relationships(facts: list[Fact]) -> tuple[str, dict[str, object]]:
    """Batch-MERGE (:Fact)-[:FROM_SOURCE]->(:Source)."""
    query = (
        "UNWIND $pairs AS pair "
        "MATCH (f:Fact {fact_id: pair.fact_id}) "
        "MATCH (s:Source {source_id: pair.source_id}) "
        "MERGE (f)-[:FROM_SOURCE]->(s)"
    )
    params: dict[str, object] = {
        "pairs": [
            {"fact_id": str(fact.fact_id), "source_id": str(fact.source.source_id)}
            for fact in facts
        ]
    }
    return query, params


def merge_contradiction_conflicts_relationships(
    contradictions: list[ContradictionSet],
) -> tuple[str, dict[str, object]]:
    """Batch-MERGE (:ContradictionSet)-[:CONFLICTS]->(:Fact), one edge
    per fact in each ContradictionSet.conflicting_fact_ids."""
    query = (
        "UNWIND $pairs AS pair "
        "MATCH (cs:ContradictionSet {contradiction_id: pair.contradiction_id}) "
        "MATCH (f:Fact {fact_id: pair.fact_id}) "
        "MERGE (cs)-[:CONFLICTS]->(f)"
    )
    pairs = [
        {"contradiction_id": str(c.contradiction_id), "fact_id": str(fact_id)}
        for c in contradictions
        for fact_id in c.conflicting_fact_ids
    ]
    return query, {"pairs": pairs}


def merge_authority_assessed_by_relationships(
    facts: list[Fact], assessments: list[AuthorityAssessment]
) -> tuple[str, dict[str, object]]:
    """Batch-MERGE (:Fact)-[:ASSESSED_BY]->(:AuthorityAssessment), for
    every fact whose source has a corresponding assessment. Only facts
    with an actual assessed source get an edge — no edge is fabricated
    for facts whose source lacks an assessment."""
    assessed_source_ids = {str(a.source_id) for a in assessments}
    query = (
        "UNWIND $pairs AS pair "
        "MATCH (f:Fact {fact_id: pair.fact_id}) "
        "MATCH (aa:AuthorityAssessment {source_id: pair.source_id}) "
        "MERGE (f)-[:ASSESSED_BY]->(aa)"
    )
    pairs = [
        {"fact_id": str(fact.fact_id), "source_id": str(fact.source.source_id)}
        for fact in facts
        if str(fact.source.source_id) in assessed_source_ids
    ]
    return query, {"pairs": pairs}


def merge_resolution_resolves_relationships(
    resolutions: list[Resolution], contradiction_by_resolution_id: dict[str, str]
) -> tuple[str, dict[str, object]]:
    """Batch-MERGE (:Resolution)-[:RESOLVES]->(:ContradictionSet).

    The resolution_id -> contradiction_id mapping is supplied by the
    caller (materialize.py), which extracts it from each Resolution's
    explicit contradiction_id field. This function builds the corresponding
    Cypher statement for the batch of pairs.
    """
    query = (
        "UNWIND $pairs AS pair "
        "MATCH (res:Resolution {resolution_id: pair.resolution_id}) "
        "MATCH (cs:ContradictionSet {contradiction_id: pair.contradiction_id}) "
        "MERGE (res)-[:RESOLVES]->(cs)"
    )
    known_resolution_ids = {str(r.resolution_id) for r in resolutions}
    pairs = [
        {"resolution_id": rid, "contradiction_id": cid}
        for rid, cid in contradiction_by_resolution_id.items()
        if rid in known_resolution_ids
    ]
    return query, {"pairs": pairs}


def merge_resolution_winner_relationships(
    resolutions: list[Resolution],
) -> tuple[str, dict[str, object]]:
    """Batch-MERGE (:Resolution)-[:WINNER]->(:Fact).

    Only resolutions with a non-null winning_fact_id produce a pair —
    UNRESOLVED and ALL_REJECTED resolutions get no WINNER edge at all,
    not an edge to a null/placeholder node.
    """
    query = (
        "UNWIND $pairs AS pair "
        "MATCH (res:Resolution {resolution_id: pair.resolution_id}) "
        "MATCH (f:Fact {fact_id: pair.fact_id}) "
        "MERGE (res)-[:WINNER]->(f)"
    )
    pairs = [
        {"resolution_id": str(r.resolution_id), "fact_id": str(r.winning_fact_id)}
        for r in resolutions
        if r.winning_fact_id is not None
    ]
    return query, {"pairs": pairs}


def merge_resolution_supersedes_relationships(
    resolutions: list[Resolution],
) -> tuple[str, dict[str, object]]:
    """Batch-MERGE (:Resolution)-[:SUPERSEDES]->(:Fact), one edge per
    entry in each Resolution.superseded_fact_ids. Only pairs explicitly
    present in the Resolution are created — never inferred from
    timestamps or any other signal Stage 5 didn't already establish."""
    query = (
        "UNWIND $pairs AS pair "
        "MATCH (res:Resolution {resolution_id: pair.resolution_id}) "
        "MATCH (f:Fact {fact_id: pair.fact_id}) "
        "MERGE (res)-[:SUPERSEDES]->(f)"
    )
    pairs = [
        {"resolution_id": str(r.resolution_id), "fact_id": str(fact_id)}
        for r in resolutions
        for fact_id in r.superseded_fact_ids
    ]
    return query, {"pairs": pairs}
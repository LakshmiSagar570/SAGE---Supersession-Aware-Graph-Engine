"""
Stage 6 — Materialization.

Responsibility: orchestrate validation, deterministic ordering, and
transactional persistence of a Stage6Input into Neo4j.

    Stage6Input
          |
          v
    validate_stage6_input()   (fail closed on any invariant violation)
          |
          v
    normalize / sort by stable IDs   (determinism regardless of input order)
          |
          v
    single Neo4j transaction:
        MERGE Source nodes
        MERGE Fact nodes
        MERGE ContradictionSet nodes
        MERGE AuthorityAssessment nodes
        MERGE Resolution nodes
        MERGE FROM_SOURCE relationships
        MERGE CONFLICTS relationships
        MERGE ASSESSED_BY relationships
        MERGE RESOLVES relationships
        MERGE WINNER relationships
        MERGE SUPERSEDES relationships
    commit
          |
          v
    Stage6Output (write counts + status="COMMITTED")

This module contains NO reasoning logic: it does not choose winners,
infer authority, detect contradictions, modify Fact semantics,
reinterpret Resolution, or invent any relationship not already
justified by the Stage 5 output. It only transforms already-decided
state into persistence operations.

--------------------------------------------------------------------
TESTABILITY WITHOUT A LIVE DATABASE

materialize() takes a client conforming to the TransactionalClient
protocol below, not a concrete Neo4jClient. Unit tests
(test_stage6_materialization.py) pass a fake/mock implementing that
protocol, so the full validate -> sort -> build-queries -> execute ->
build-output flow is exercised and asserted without any real Neo4j
connection. Only tests/integration/test_stage6_neo4j.py (a separate,
UNVERIFIED-in-this-environment file) exercises the real
neo4j_client.py against an actual database.
--------------------------------------------------------------------

RESOLUTION -> CONTRADICTION MAPPING: the Resolution contract includes
an explicit contradiction_id field linking each Resolution directly to
its originating ContradictionSet. This module uses that explicit
reference to build [:RESOLVES] relationships deterministically, without
relying on positional correspondence or list ordering.
--------------------------------------------------------------------
"""

from __future__ import annotations

from typing import Protocol

from contracts.fact_schema import (
    AuthorityAssessment,
    ContradictionSet,
    Fact,
    Resolution,
    Source,
)
from contracts.stage_io import Stage6Input, Stage6Output

from . import queries
from .validate import validate_stage6_input


class TransactionalClient(Protocol):
    """What materialize() needs from a Neo4j client: run a batch of
    write queries with parameters, inside a transaction that commits
    only if every call in the batch succeeds. A test fake and the real
    neo4j_client.Neo4jClient both satisfy this protocol.
    """

    def run_in_transaction(
        self, statements: list[tuple[str, dict[str, object]]]
    ) -> None:
        """Execute every (query, params) pair in `statements`, in order,
        inside a single transaction. Commits only if all succeed; must
        roll back and raise (not swallow) if any statement fails,
        leaving no partial state."""
        ...


def materialize(stage_input: Stage6Input, client: TransactionalClient) -> Stage6Output:
    """Validate, normalize, and atomically persist a Stage6Input.

    Raises Stage6ValidationError (from validate_stage6_input) before
    any transaction begins if the input is invalid — no database write
    is attempted for invalid input. Raises whatever `client` raises on
    transaction failure; this function does not swallow persistence
    errors.
    """
    validate_stage6_input(stage_input)

    sorted_facts = sorted(stage_input.facts, key=lambda f: str(f.fact_id))
    sorted_sources = _deduplicated_sorted_sources(sorted_facts)
    sorted_contradictions = sorted(
        stage_input.contradictions, key=lambda c: str(c.contradiction_id)
    )
    sorted_assessments = sorted(
        stage_input.authority_assessments, key=lambda a: str(a.source_id)
    )
    sorted_resolutions = sorted(
        stage_input.resolutions, key=lambda r: str(r.resolution_id)
    )
    contradiction_by_resolution_id = {
        str(r.resolution_id): str(r.contradiction_id)
        for r in sorted_resolutions
    }

    statements = _build_statements(
        sorted_sources,
        sorted_facts,
        sorted_contradictions,
        sorted_assessments,
        sorted_resolutions,
        contradiction_by_resolution_id,
    )
    client.run_in_transaction(statements)

    return Stage6Output(
        facts_written=len(sorted_facts),
        sources_written=len(sorted_sources),
        contradictions_written=len(sorted_contradictions),
        authority_assessments_written=len(sorted_assessments),
        resolutions_written=len(sorted_resolutions),
        status="COMMITTED",
    )


def _build_statements(
    sources: list[Source],
    facts: list[Fact],
    contradictions: list[ContradictionSet],
    assessments: list[AuthorityAssessment],
    resolutions: list[Resolution],
    contradiction_by_resolution_id: dict[str, str],
) -> list[tuple[str, dict[str, object]]]:
    """Build the full ordered list of (query, params) statements for one
    transaction: all node MERGEs first, then all relationship MERGEs —
    relationships can only MATCH nodes that already exist, so node
    writes must precede relationship writes within the same
    transaction."""
    return [
        queries.merge_sources(sources),
        queries.merge_facts(facts),
        queries.merge_contradictions(contradictions),
        queries.merge_authority_assessments(assessments),
        queries.merge_resolutions(resolutions),
        queries.merge_fact_source_relationships(facts),
        queries.merge_contradiction_conflicts_relationships(contradictions),
        queries.merge_authority_assessed_by_relationships(facts, assessments),
        queries.merge_resolution_resolves_relationships(
            resolutions, contradiction_by_resolution_id
        ),
        queries.merge_resolution_winner_relationships(resolutions),
        queries.merge_resolution_supersedes_relationships(resolutions),
    ]


def _deduplicated_sorted_sources(sorted_facts: list[Fact]) -> list[Source]:
    """Extract each fact's Source, deduplicated by source_id, in
    deterministic sorted order. validate_stage6_input has already
    confirmed that any two facts sharing a source_id describe the same
    Source, so the first occurrence encountered is safe to keep."""
    seen: dict[str, Source] = {}
    for fact in sorted_facts:
        key = str(fact.source.source_id)
        if key not in seen:
            seen[key] = fact.source
    return [seen[key] for key in sorted(seen)]



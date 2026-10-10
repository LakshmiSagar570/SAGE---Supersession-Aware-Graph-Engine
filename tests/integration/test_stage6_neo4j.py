"""Integration tests for Stage 6 against a REAL Neo4j instance.

*** THESE TESTS HAVE NEVER BEEN RUN IN THIS ENVIRONMENT ***

The sandbox this file was written in has no network access to any
database -- its bash tool is restricted to a fixed package-registry
allowlist. This file has been written carefully and should be
structurally correct pytest, but it has never been collected, never
been executed, and its assertions have never been checked against a
real Neo4j response. Do not report these as passing until they have
actually been run against a live database (e.g. via docker-compose.yml
in this repo) and you have seen real pass/fail output.

Requires:
    - A running Neo4j instance (see docker-compose.yml)
    - NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE set
      (see .env.example)
    - `pip install neo4j` (or project dependencies installed)

Run with: pytest tests/integration/test_stage6_neo4j.py -v
(separately from the unit suite, since it requires live infrastructure
the unit suite deliberately does not depend on)
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from contracts.fact_schema import (
    ConflictType,
    ContradictionID,
    ContradictionSet,
    Fact,
    FactID,
    FactStatus,
    Resolution,
    ResolutionID,
    ResolutionOutcome,
    Source,
    SourceID,
    SourceType,
)
from contracts.stage_io import Stage6Input
from sage.pipeline.stage_6.materialize import materialize
from sage.pipeline.stage_6.neo4j_client import Neo4jClient
from sage.pipeline.stage_6.queries import CREATE_CONSTRAINTS


def _make_source(source_id: str, source_type: SourceType = SourceType.DOCUMENT) -> Source:
    return Source(
        source_id=SourceID(source_id),
        name=source_id,
        source_type=source_type,
        locator=source_id,
    )


def _make_fact(*, subject: str, predicate: str, obj: str, source: Source) -> Fact:
    now = datetime.now(UTC)
    return Fact(
        fact_id=FactID(str(uuid4())),
        subject=subject,
        predicate=predicate,
        object=obj,
        source=source,
        evidence=f"{subject} {predicate} {obj}.",
        extracted_at=now,
        effective_from=now,
        effective_to=None,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )


def _read_count(neo4j_client: Neo4jClient, query: str) -> int:
    rows = neo4j_client.run_read_query(query)
    assert len(rows) == 1
    val = rows[0]["count"]
    assert isinstance(val, int)
    return val


@pytest.fixture(scope="module")
def neo4j_client() -> Generator[Neo4jClient, None, None]:
    """A real Neo4jClient, connected to whatever NEO4J_URI etc. point
    to. If these env vars aren't set, this fixture -- and every test
    using it -- should be skipped rather than fail with a confusing
    connection error."""
    if not os.environ.get("NEO4J_PASSWORD"):
        pytest.skip(
            "NEO4J_PASSWORD not set; skipping integration tests. See "
            ".env.example and docker-compose.yml to set up a real Neo4j "
            "instance before running this suite."
        )
    client = Neo4jClient()
    client.verify_connectivity()
    client.create_constraints(CREATE_CONSTRAINTS)
    yield client
    client.close()


@pytest.fixture(autouse=True)
def _clean_database(neo4j_client: Neo4jClient) -> None:
    """Wipe all SAGE-related nodes before each test, so tests don't
    interfere with each other. A real integration suite would likely
    use a dedicated test database rather than wiping a shared one --
    flagged here as a real design gap in this UNVERIFIED file, not
    something resolved."""
    neo4j_client.run_in_transaction(
        [
            (
                (
                    "MATCH (n) WHERE n:Source OR n:Fact OR n:ContradictionSet "
                    "OR n:AuthorityAssessment OR n:Resolution DETACH DELETE n"
                ),
                {},
            )
        ]
    )


class TestBasicMaterialization:
    """Test 1 -- basic materialization: Stage5Input -> Stage 6 -> graph
    contains expected nodes."""

    def test_facts_and_sources_materialize(self, neo4j_client: Neo4jClient) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        stage_input = Stage6Input(
            facts=[fact], contradictions=[], authority_assessments=[], resolutions=[]
        )

        output = materialize(stage_input, neo4j_client)

        assert output.facts_written == 1
        assert output.sources_written == 1
        assert output.status == "COMMITTED"

    def test_optional_evidence_and_locator_persist_as_null(
        self, neo4j_client: Neo4jClient
    ) -> None:
        source = Source(
            source_id=SourceID("optional-source"),
            name="optional-source",
            source_type=SourceType.DOCUMENT,
        )
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        fact.evidence = None
        materialize(
            Stage6Input(
                facts=[fact], contradictions=[], authority_assessments=[], resolutions=[]
            ),
            neo4j_client,
        )

        rows = neo4j_client.run_read_query(
            "MATCH (f:Fact {fact_id: $fact_id}) "
            "MATCH (s:Source {source_id: $source_id}) "
            "RETURN f.evidence AS evidence, s.locator AS locator",
            {"fact_id": str(fact.fact_id), "source_id": str(source.source_id)},
        )
        assert rows == [{"evidence": None, "locator": None}]


class TestProvenance:
    """Test 2 -- provenance: Fact -> FROM_SOURCE -> Source."""

    def test_from_source_relationship_exists(self, neo4j_client: Neo4jClient) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        stage_input = Stage6Input(
            facts=[fact], contradictions=[], authority_assessments=[], resolutions=[]
        )
        materialize(stage_input, neo4j_client)
        rows = neo4j_client.run_read_query(
            "MATCH (f:Fact)-[:FROM_SOURCE]->(s:Source) "
            "RETURN count(*) AS count"
        )
        assert rows == [{"count": 1}]


class TestContradiction:
    """Test 3 -- contradiction: ContradictionSet -> CONFLICTS -> Facts."""

    def test_conflicts_relationships_created(self, neo4j_client: Neo4jClient) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = ContradictionSet(
            contradiction_id=ContradictionID(str(uuid4())),
            conflicting_fact_ids=[fact_a.fact_id, fact_b.fact_id],
            conflict_type=ConflictType.TEMPORAL_OVERLAP,
            detected_at=datetime.now(UTC),
        )
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=[],
            resolutions=[],
        )

        output = materialize(stage_input, neo4j_client)
        assert output.contradictions_written == 1
        assert _read_count(
            neo4j_client,
            "MATCH (:ContradictionSet)-[:CONFLICTS]->(:Fact) RETURN count(*) AS count",
        ) == 2


class TestResolution:
    """Test 4 -- resolution: RESOLVES, WINNER, SUPERSEDES relationships."""

    def test_winner_selected_creates_all_three_relationship_types(
        self, neo4j_client: Neo4jClient
    ) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = ContradictionSet(
            contradiction_id=ContradictionID(str(uuid4())),
            conflicting_fact_ids=[fact_a.fact_id, fact_b.fact_id],
            conflict_type=ConflictType.TEMPORAL_OVERLAP,
            detected_at=datetime.now(UTC),
        )
        resolution = Resolution(
            resolution_id=ResolutionID(str(uuid4())),
            contradiction_id=contradiction.contradiction_id,
            outcome=ResolutionOutcome.WINNER_SELECTED,
            winning_fact_id=fact_a.fact_id,
            superseded_fact_ids=[fact_b.fact_id],
            rationale="test",
            resolved_at=datetime.now(UTC),
        )
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=[],
            resolutions=[resolution],
        )

        output = materialize(stage_input, neo4j_client)
        assert output.resolutions_written == 1
        assert _read_count(
            neo4j_client,
            "MATCH (:Resolution)-[:RESOLVES]->(:ContradictionSet) RETURN count(*) AS count",
        ) == 1
        assert _read_count(
            neo4j_client,
            "MATCH (:Resolution)-[:WINNER]->(:Fact) RETURN count(*) AS count",
        ) == 1
        assert _read_count(
            neo4j_client,
            "MATCH (:Resolution)-[:SUPERSEDES]->(:Fact) RETURN count(*) AS count",
        ) == 1


class TestUnresolved:
    """Test 5 -- unresolved: RESOLVES exists, but WINNER = 0, SUPERSEDES = 0."""

    def test_unresolved_has_no_winner_or_supersedes(
        self, neo4j_client: Neo4jClient
    ) -> None:
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("doc-2", SourceType.DOCUMENT)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = ContradictionSet(
            contradiction_id=ContradictionID(str(uuid4())),
            conflicting_fact_ids=[fact_a.fact_id, fact_b.fact_id],
            conflict_type=ConflictType.TEMPORAL_OVERLAP,
            detected_at=datetime.now(UTC),
        )
        resolution = Resolution(
            resolution_id=ResolutionID(str(uuid4())),
            contradiction_id=contradiction.contradiction_id,
            outcome=ResolutionOutcome.UNRESOLVED,
            winning_fact_id=None,
            superseded_fact_ids=[],
            rationale="test",
            resolved_at=datetime.now(UTC),
        )
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=[],
            resolutions=[resolution],
        )

        output = materialize(stage_input, neo4j_client)
        assert output.resolutions_written == 1
        assert _read_count(
            neo4j_client,
            "MATCH (:Resolution)-[:RESOLVES]->(:ContradictionSet) RETURN count(*) AS count",
        ) == 1
        assert _read_count(
            neo4j_client,
            "MATCH (:Resolution)-[:WINNER]->(:Fact) RETURN count(*) AS count",
        ) == 0
        assert _read_count(
            neo4j_client,
            "MATCH (:Resolution)-[:SUPERSEDES]->(:Fact) RETURN count(*) AS count",
        ) == 0


class TestIdempotency:
    """Test 6 -- idempotency: same input run twice, unchanged node/edge counts."""

    def test_running_twice_produces_same_counts(self, neo4j_client: Neo4jClient) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        stage_input = Stage6Input(
            facts=[fact], contradictions=[], authority_assessments=[], resolutions=[]
        )

        first_output = materialize(stage_input, neo4j_client)
        first_node_count = _read_count(
            neo4j_client,
            "MATCH (n) WHERE n:Source OR n:Fact OR n:ContradictionSet "
            "OR n:AuthorityAssessment OR n:Resolution RETURN count(n) AS count",
        )
        first_relationship_count = _read_count(
            neo4j_client, "MATCH ()-[r]->() RETURN count(r) AS count"
        )
        second_output = materialize(stage_input, neo4j_client)
        second_node_count = _read_count(
            neo4j_client,
            "MATCH (n) WHERE n:Source OR n:Fact OR n:ContradictionSet "
            "OR n:AuthorityAssessment OR n:Resolution RETURN count(n) AS count",
        )
        second_relationship_count = _read_count(
            neo4j_client, "MATCH ()-[r]->() RETURN count(r) AS count"
        )

        assert first_output.facts_written == second_output.facts_written
        assert first_output.sources_written == second_output.sources_written
        assert first_node_count == second_node_count == 2
        assert first_relationship_count == second_relationship_count == 1


class TestRollback:
    """Test 7 -- rollback: forced transaction failure leaves no partial state."""

    def test_forced_failure_leaves_no_partial_state(
        self, neo4j_client: Neo4jClient
    ) -> None:
        """Atomicity test: execute a batch of statements where an intermediate
        statement triggers a runtime execution failure (unique constraint
        violation on Source.source_id).

        Verify that Neo4jTransactionError is raised, and verify via read query
        that neither the statements prior to the failure nor any after it
        persisted to the graph.
        """
        from sage.pipeline.stage_6.neo4j_client import Neo4jTransactionError

        source_1_id = f"rollback-src-1-{uuid4()}"
        source_2_id = f"rollback-src-2-{uuid4()}"

        statements: list[tuple[str, dict[str, object]]] = [
            # 1. Valid statement before failure point: creates source_1
            (
                "CREATE (s:Source {source_id: $sid, name: 'Rollback 1', source_type: 'DOCUMENT'})",
                {"sid": source_1_id},
            ),
            # 2. Statement that parses fine, but violates uniqueness constraint at execution time
            (
                "CREATE (s:Source {source_id: $sid, name: 'Colliding Node', source_type: 'DOCUMENT'})",
                {"sid": source_1_id},
            ),
            # 3. Valid statement after failure point: creates source_2
            (
                "CREATE (s:Source {source_id: $sid, name: 'Rollback 2', source_type: 'DOCUMENT'})",
                {"sid": source_2_id},
            ),
        ]

        with pytest.raises(Neo4jTransactionError):
            neo4j_client.run_in_transaction(statements)

        # Confirm via read query that zero of the nodes persisted
        rows = neo4j_client.run_read_query(
            "MATCH (s:Source) WHERE s.source_id IN [$s1, $s2] RETURN count(s) AS count",
            {"s1": source_1_id, "s2": source_2_id},
        )
        assert len(rows) == 1
        assert rows[0]["count"] == 0


class TestMissingReference:
    """Test 8 -- missing reference: invalid Stage 6 input fails before persistence."""

    def test_invalid_input_never_reaches_database(self, neo4j_client: Neo4jClient) -> None:
        from sage.pipeline.stage_6.validate import Stage6ValidationError

        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        phantom_fact_id = FactID(str(uuid4()))
        bad_resolution = Resolution(
            resolution_id=ResolutionID(str(uuid4())),
            contradiction_id=ContradictionID(str(uuid4())),
            outcome=ResolutionOutcome.WINNER_SELECTED,
            winning_fact_id=phantom_fact_id,
            superseded_fact_ids=[],
            rationale="references unknown fact",
            resolved_at=datetime.now(UTC),
        )
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[],
            resolutions=[bad_resolution],
        )

        with pytest.raises(Stage6ValidationError):
            materialize(stage_input, neo4j_client)
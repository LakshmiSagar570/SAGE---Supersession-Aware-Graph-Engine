"""Tests for Stage 6 materialization (materialize.py) and query
construction (queries.py) -- entirely mock-based, no real Neo4j
connection anywhere in this file. See tests/integration/test_stage6_neo4j.py
for the (currently unverified) real-database test suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from contracts.fact_schema import (
    AuthorityAssessment,
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
from sage.pipeline.stage_6 import queries
from sage.pipeline.stage_6.materialize import materialize
from sage.pipeline.stage_6.stage import run_stage6
from sage.pipeline.stage_6.validate import Stage6ValidationError


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


def _make_contradiction(*fact_ids: FactID) -> ContradictionSet:
    return ContradictionSet(
        contradiction_id=ContradictionID(str(uuid4())),
        conflicting_fact_ids=list(fact_ids),
        conflict_type=ConflictType.TEMPORAL_OVERLAP,
        detected_at=datetime.now(UTC),
    )


def _make_assessment(source: Source, score: float) -> AuthorityAssessment:
    return AuthorityAssessment(
        source_id=source.source_id,
        authority_score=score,
        rationale="test",
        assessed_at=datetime.now(UTC),
    )


def _make_winner_resolution(
    winner: Fact, *losers: Fact, contradiction_id: ContradictionID | None = None
) -> Resolution:
    return Resolution(
        resolution_id=ResolutionID(str(uuid4())),
        contradiction_id=contradiction_id or ContradictionID(str(uuid4())),
        outcome=ResolutionOutcome.WINNER_SELECTED,
        winning_fact_id=winner.fact_id,
        superseded_fact_ids=[f.fact_id for f in losers],
        rationale="test winner resolution",
        resolved_at=datetime.now(UTC),
    )


def _make_unresolved_resolution(
    contradiction_id: ContradictionID | None = None,
) -> Resolution:
    return Resolution(
        resolution_id=ResolutionID(str(uuid4())),
        contradiction_id=contradiction_id or ContradictionID(str(uuid4())),
        outcome=ResolutionOutcome.UNRESOLVED,
        winning_fact_id=None,
        superseded_fact_ids=[],
        rationale="test unresolved resolution",
        resolved_at=datetime.now(UTC),
    )


class FakeTransactionalClient:
    """Mock satisfying materialize.py's TransactionalClient protocol.
    Records every statement it was asked to run, and can be configured
    to raise partway through to test failure propagation."""

    def __init__(self, fail_on_statement_index: int | None = None) -> None:
        self.recorded_statements: list[tuple[str, dict[str, object]]] = []
        self.committed = False
        self._fail_on_statement_index = fail_on_statement_index

    def run_in_transaction(
        self, statements: list[tuple[str, dict[str, object]]]
    ) -> None:
        for i, statement in enumerate(statements):
            if self._fail_on_statement_index is not None and i == self._fail_on_statement_index:
                raise RuntimeError(f"Simulated failure at statement index {i}")
            self.recorded_statements.append(statement)
        self.committed = True


class TestQueryConstruction:
    """Verify generated Cypher: MERGE usage, UNWIND batching, no CREATE
    where idempotency requires MERGE."""

    def test_merge_sources_uses_merge_not_create(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        query, _params = queries.merge_sources([source])
        assert "MERGE" in query
        assert "CREATE" not in query

    def test_merge_sources_uses_unwind_for_batching(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        query, params = queries.merge_sources([source_a, source_b])
        assert "UNWIND" in query
        assert len(params["sources"]) == 2  # type: ignore[arg-type]

    def test_merge_facts_uses_merge_not_create(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        query, _params = queries.merge_facts([fact])
        assert "MERGE" in query
        assert "CREATE" not in query

    def test_merge_facts_parameters_preserve_fact_id(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        _, params = queries.merge_facts([fact])
        fact_params = params["facts"][0]  # type: ignore[index]
        assert fact_params["fact_id"] == str(fact.fact_id)

    def test_merge_facts_no_supersedes_property(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        query, _params = queries.merge_facts([fact])
        assert "supersedes" not in query.lower()
        assert "superseded_by" not in query.lower()

    def test_merge_contradictions_no_conflicting_fact_ids_property(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        query, params = queries.merge_contradictions([contradiction])
        assert "conflicting_fact_ids" not in query
        assert "conflicting_fact_ids" not in params["contradictions"][0]  # type: ignore[index]

    def test_merge_resolutions_no_superseded_fact_ids_property(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        resolution = _make_winner_resolution(fact_a, fact_b)
        query, params = queries.merge_resolutions([resolution])
        assert "superseded_fact_ids" not in query
        assert "superseded_fact_ids" not in params["resolutions"][0]  # type: ignore[index]

    def test_relationship_queries_use_merge(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        query, _params = queries.merge_fact_source_relationships([fact])
        assert "MERGE" in query
        assert "CREATE" not in query

    def test_winner_relationship_only_for_winner_selected(self) -> None:
        unresolved = _make_unresolved_resolution()
        _, params = queries.merge_resolution_winner_relationships([unresolved])
        assert params["pairs"] == []

    def test_winner_relationship_present_for_winner_selected(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        resolution = _make_winner_resolution(fact_a, fact_b)
        _, params = queries.merge_resolution_winner_relationships([resolution])
        assert len(params["pairs"]) == 1  # type: ignore[arg-type]
        assert params["pairs"][0]["fact_id"] == str(fact_a.fact_id)  # type: ignore[index]

    def test_supersedes_relationships_only_explicit_pairs(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        source_c = _make_source("api-1", SourceType.API)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        fact_c = _make_fact(subject="X", predicate="is Y", obj="C", source=source_c)
        resolution = _make_winner_resolution(fact_a, fact_b, fact_c)
        _, params = queries.merge_resolution_supersedes_relationships([resolution])
        superseded_ids = {p["fact_id"] for p in params["pairs"]}  # type: ignore[attr-defined]
        assert superseded_ids == {str(fact_b.fact_id), str(fact_c.fact_id)}

    def test_constraints_use_if_not_exists(self) -> None:
        for statement in queries.CREATE_CONSTRAINTS:
            assert "IF NOT EXISTS" in statement

    def test_constraints_cover_all_identity_bearing_nodes(self) -> None:
        constraint_text = " ".join(queries.CREATE_CONSTRAINTS)
        for node_label in ("Source", "Fact", "ContradictionSet", "Resolution"):
            assert f"FOR (n:{node_label})" in constraint_text


class TestMaterialize:
    def test_validation_runs_before_any_transaction(self) -> None:
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
        client = FakeTransactionalClient()

        with pytest.raises(Stage6ValidationError):
            materialize(stage_input, client)

        assert client.recorded_statements == []
        assert client.committed is False

    def test_valid_input_produces_correct_write_counts(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        resolution = _make_winner_resolution(fact_a, fact_b, contradiction_id=contradiction.contradiction_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
        ]
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=assessments,
            resolutions=[resolution],
        )
        client = FakeTransactionalClient()

        output = materialize(stage_input, client)

        assert output.facts_written == 2
        assert output.sources_written == 2
        assert output.contradictions_written == 1
        assert output.authority_assessments_written == 2
        assert output.resolutions_written == 1
        assert output.status == "COMMITTED"
        assert client.committed is True

    def test_deterministic_output_regardless_of_input_order(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        resolution = _make_winner_resolution(fact_a, fact_b, contradiction_id=contradiction.contradiction_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
        ]

        forward_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=assessments,
            resolutions=[resolution],
        )
        reversed_input = Stage6Input(
            facts=[fact_b, fact_a],
            contradictions=[contradiction],
            authority_assessments=list(reversed(assessments)),
            resolutions=[resolution],
        )

        client_forward = FakeTransactionalClient()
        client_reversed = FakeTransactionalClient()
        output_forward = materialize(forward_input, client_forward)
        output_reversed = materialize(reversed_input, client_reversed)

        assert output_forward.facts_written == output_reversed.facts_written
        assert output_forward.sources_written == output_reversed.sources_written
        forward_fact_params = client_forward.recorded_statements[1][1]["facts"]  
        reversed_fact_params = client_reversed.recorded_statements[1][1]["facts"]  
        assert forward_fact_params == reversed_fact_params  

    def test_unresolved_resolution_produces_no_winner_but_counts(self) -> None:
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("doc-2", SourceType.DOCUMENT)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        resolution = _make_unresolved_resolution(contradiction_id=contradiction.contradiction_id)
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=[],
            resolutions=[resolution],
        )
        client = FakeTransactionalClient()

        output = materialize(stage_input, client)

        assert output.resolutions_written == 1
        winner_statement = next(
            (q, p) for q, p in client.recorded_statements if "[:WINNER]" in q
        )
        assert winner_statement[1]["pairs"] == []

    def test_transaction_failure_propagates_and_no_output_produced(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[],
            resolutions=[],
        )
        failing_client = FakeTransactionalClient(fail_on_statement_index=1)

        with pytest.raises(RuntimeError, match="Simulated failure"):
            materialize(stage_input, failing_client)

        assert failing_client.committed is False

    def test_no_relationships_created_for_uninvolved_facts(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[],
            resolutions=[],
        )
        client = FakeTransactionalClient()

        materialize(stage_input, client)

        statements_by_relationship = {
            q: p for q, p in client.recorded_statements if "MATCH" in q
        }
        for query, params in statements_by_relationship.items():
            if "[:FROM_SOURCE]" in query:
                assert len(params["pairs"]) == 1  # type: ignore[arg-type]
            else:
                assert params.get("pairs", []) == []

    def test_empty_input_produces_zero_counts(self) -> None:
        stage_input = Stage6Input(
            facts=[], contradictions=[], authority_assessments=[], resolutions=[]
        )
        client = FakeTransactionalClient()

        output = materialize(stage_input, client)

        assert output.facts_written == 0
        assert output.sources_written == 0
        assert output.contradictions_written == 0
        assert output.authority_assessments_written == 0
        assert output.resolutions_written == 0
        assert output.status == "COMMITTED"


class TestRunStage6:
    def test_run_stage6_delegates_to_materialize(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        stage_input = Stage6Input(
            facts=[fact], contradictions=[], authority_assessments=[], resolutions=[]
        )
        client = FakeTransactionalClient()

        output = run_stage6(stage_input, client)

        assert output.facts_written == 1
        assert output.status == "COMMITTED"
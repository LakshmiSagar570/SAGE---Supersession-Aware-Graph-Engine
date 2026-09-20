"""Tests for Stage 6 structural validation (validate.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

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
from sage.pipeline.stage_6.validate import Stage6ValidationError, validate_stage6_input


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


class TestValidateStage6Input:
    def test_a_valid_stage5_state_passes(self) -> None:
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

        validate_stage6_input(stage_input)

    def test_b_unknown_winning_fact_id_fails(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        phantom_fact_id = FactID(str(uuid4()))
        c_id = ContradictionID(str(uuid4()))
        bad_resolution = Resolution(
            resolution_id=ResolutionID(str(uuid4())),
            contradiction_id=c_id,
            outcome=ResolutionOutcome.WINNER_SELECTED,
            winning_fact_id=phantom_fact_id,
            superseded_fact_ids=[],
            rationale="references a fact that doesn't exist",
            resolved_at=datetime.now(UTC),
        )
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[],
            resolutions=[bad_resolution],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(phantom_fact_id) in str(exc)
            assert "winning_fact_id" in str(exc)

    def test_c_unknown_superseded_fact_id_fails(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        phantom_fact_id = FactID(str(uuid4()))
        c_id = ContradictionID(str(uuid4()))
        bad_resolution = Resolution(
            resolution_id=ResolutionID(str(uuid4())),
            contradiction_id=c_id,
            outcome=ResolutionOutcome.WINNER_SELECTED,
            winning_fact_id=fact.fact_id,
            superseded_fact_ids=[phantom_fact_id],
            rationale="references a superseded fact that doesn't exist",
            resolved_at=datetime.now(UTC),
        )
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[],
            resolutions=[bad_resolution],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(phantom_fact_id) in str(exc)
            assert "superseded" in str(exc).lower()

    def test_d_unknown_contradiction_fact_id_fails(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        phantom_fact_id = FactID(str(uuid4()))
        bad_contradiction = _make_contradiction(fact.fact_id, phantom_fact_id)
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[bad_contradiction],
            authority_assessments=[],
            resolutions=[],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(phantom_fact_id) in str(exc)

    def test_e_duplicate_fact_id_fails(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact_1 = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        fact_2 = fact_1.model_copy(update={"object": "B"})
        stage_input = Stage6Input(
            facts=[fact_1, fact_2],
            contradictions=[],
            authority_assessments=[],
            resolutions=[],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(fact_1.fact_id) in str(exc)
            assert "fact_id" in str(exc).lower()

    def test_f_duplicate_contradiction_id_fails(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction_1 = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        contradiction_2 = contradiction_1.model_copy()
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction_1, contradiction_2],
            authority_assessments=[],
            resolutions=[],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(contradiction_1.contradiction_id) in str(exc)

    def test_g_duplicate_resolution_id_fails(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        resolution_1 = _make_unresolved_resolution()
        resolution_2 = resolution_1.model_copy()
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[],
            resolutions=[resolution_1, resolution_2],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(resolution_1.resolution_id) in str(exc)

    def test_h_valid_unresolved_resolution_passes(self) -> None:
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

        validate_stage6_input(stage_input)

    def test_i_multiple_resolutions_all_validated(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        source_c = _make_source("api-1", SourceType.API)
        source_d = _make_source("other-1", SourceType.OTHER)

        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        fact_c = _make_fact(subject="P", predicate="is Q", obj="C", source=source_c)
        fact_d = _make_fact(subject="P", predicate="is Q", obj="D", source=source_d)

        contradiction_1 = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        contradiction_2 = _make_contradiction(fact_c.fact_id, fact_d.fact_id)
        resolution_1 = _make_winner_resolution(fact_a, fact_b, contradiction_id=contradiction_1.contradiction_id)
        resolution_2 = _make_unresolved_resolution(contradiction_id=contradiction_2.contradiction_id)

        stage_input = Stage6Input(
            facts=[fact_a, fact_b, fact_c, fact_d],
            contradictions=[contradiction_1, contradiction_2],
            authority_assessments=[
                _make_assessment(source_a, 1.0),
                _make_assessment(source_b, 0.4),
            ],
            resolutions=[resolution_1, resolution_2],
        )

        validate_stage6_input(stage_input)

    def test_j_input_objects_unchanged(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        resolution = _make_winner_resolution(fact_a, fact_b, contradiction_id=contradiction.contradiction_id)
        assessment = _make_assessment(source_a, 1.0)

        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=[assessment],
            resolutions=[resolution],
        )
        snapshot = stage_input.model_copy(deep=True)

        validate_stage6_input(stage_input)

        assert stage_input == snapshot

    def test_k_deterministic_validation(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        phantom_fact_id = FactID(str(uuid4()))
        bad_contradiction = _make_contradiction(fact.fact_id, phantom_fact_id)
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[bad_contradiction],
            authority_assessments=[],
            resolutions=[],
        )

        messages = []
        for _ in range(10):
            try:
                validate_stage6_input(stage_input)
            except Stage6ValidationError as exc:
                messages.append(str(exc))

        assert len(messages) == 10
        assert len(set(messages)) == 1

    def test_l_empty_collections_valid(self) -> None:
        stage_input = Stage6Input(
            facts=[],
            contradictions=[],
            authority_assessments=[],
            resolutions=[],
        )
        validate_stage6_input(stage_input)

    def test_inconsistent_source_id_fails(self) -> None:
        source_a = _make_source("shared-id", SourceType.DATABASE)
        source_b = _make_source("shared-id", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[],
            authority_assessments=[],
            resolutions=[],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert "shared-id" in str(exc)

    def test_duplicate_authority_assessment_source_fails(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        assessment_1 = _make_assessment(source, 1.0)
        assessment_2 = _make_assessment(source, 0.8)
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[assessment_1, assessment_2],
            resolutions=[],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(source.source_id) in str(exc)

    def test_authority_assessment_unknown_source_fails(self) -> None:
        source = _make_source("db-1", SourceType.DATABASE)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        orphan_source = _make_source("orphan-1", SourceType.WEB)
        orphan_assessment = _make_assessment(orphan_source, 0.5)
        stage_input = Stage6Input(
            facts=[fact],
            contradictions=[],
            authority_assessments=[orphan_assessment],
            resolutions=[],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert "orphan-1" in str(exc)
    def test_unknown_resolution_contradiction_id_fails(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        orphan_contradiction_id = ContradictionID(str(uuid4()))
        bad_resolution = _make_winner_resolution(
            fact_a, fact_b, contradiction_id=orphan_contradiction_id
        )
        stage_input = Stage6Input(
            facts=[fact_a, fact_b],
            contradictions=[contradiction],
            authority_assessments=[],
            resolutions=[bad_resolution],
        )

        try:
            validate_stage6_input(stage_input)
            raise AssertionError("expected Stage6ValidationError")
        except Stage6ValidationError as exc:
            assert str(orphan_contradiction_id) in str(exc)
            assert "contradiction_id" in str(exc)

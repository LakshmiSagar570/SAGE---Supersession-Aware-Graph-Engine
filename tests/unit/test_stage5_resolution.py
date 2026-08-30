"""Tests for Stage 5 (Resolution)."""

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
    ResolutionOutcome,
    Source,
    SourceID,
    SourceType,
)
from contracts.stage_io import Stage5Input
from sage.pipeline.stage_5.resolve import resolve_contradictions
from sage.pipeline.stage_5.stage import run_stage5


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
        rationale=f"test assessment for {source.source_id}",
        assessed_at=datetime.now(UTC),
    )


class TestResolveContradictions:
    def test_a_higher_authority_wins(self) -> None:
        """DATABASE 1.0 vs WEB 0.4 -> WINNER_SELECTED."""
        source_db = _make_source("db-1", SourceType.DATABASE)
        source_web = _make_source("web-1", SourceType.WEB)
        fact_db = _make_fact(
            subject="X", predicate="is Y", obj="A", source=source_db
        )
        fact_web = _make_fact(
            subject="X", predicate="is Y", obj="B", source=source_web
        )
        contradiction = _make_contradiction(fact_db.fact_id, fact_web.fact_id)
        assessments = [
            _make_assessment(source_db, 1.0),
            _make_assessment(source_web, 0.4),
        ]

        resolutions = resolve_contradictions(
            [fact_db, fact_web], [contradiction], assessments
        )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.outcome == ResolutionOutcome.WINNER_SELECTED
        assert resolution.winning_fact_id == fact_db.fact_id
        assert resolution.superseded_fact_ids == [fact_web.fact_id]

    def test_b_equal_authority_unresolved(self) -> None:
        """DOCUMENT 0.8 vs DOCUMENT 0.8 -> UNRESOLVED."""
        source_1 = _make_source("doc-1", SourceType.DOCUMENT)
        source_2 = _make_source("doc-2", SourceType.DOCUMENT)
        fact_1 = _make_fact(subject="X", predicate="is Y", obj="A", source=source_1)
        fact_2 = _make_fact(subject="X", predicate="is Y", obj="B", source=source_2)
        contradiction = _make_contradiction(fact_1.fact_id, fact_2.fact_id)
        assessments = [
            _make_assessment(source_1, 0.8),
            _make_assessment(source_2, 0.8),
        ]

        resolutions = resolve_contradictions(
            [fact_1, fact_2], [contradiction], assessments
        )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.outcome == ResolutionOutcome.UNRESOLVED
        assert resolution.winning_fact_id is None
        assert resolution.superseded_fact_ids == []

    def test_c_missing_assessment_unresolved(self) -> None:
        """Fact A has an assessment, Fact B does not -> UNRESOLVED, no
        fabricated score for B."""
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [_make_assessment(source_a, 1.0)]

        resolutions = resolve_contradictions(
            [fact_a, fact_b], [contradiction], assessments
        )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.outcome == ResolutionOutcome.UNRESOLVED
        assert resolution.winning_fact_id is None

    def test_d_multiple_facts_clear_winner(self) -> None:
        """A=1.0, B=0.8, C=0.4 -> A wins, B and C superseded."""
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("doc-1", SourceType.DOCUMENT)
        source_c = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        fact_c = _make_fact(subject="X", predicate="is Y", obj="C", source=source_c)
        contradiction = _make_contradiction(
            fact_a.fact_id, fact_b.fact_id, fact_c.fact_id
        )
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.8),
            _make_assessment(source_c, 0.4),
        ]

        resolutions = resolve_contradictions(
            [fact_a, fact_b, fact_c], [contradiction], assessments
        )

        resolution = resolutions[0]
        assert resolution.outcome == ResolutionOutcome.WINNER_SELECTED
        assert resolution.winning_fact_id == fact_a.fact_id
        assert set(resolution.superseded_fact_ids) == {fact_b.fact_id, fact_c.fact_id}

    def test_e_multiple_fact_tie_unresolved(self) -> None:
        """A=1.0, B=1.0, C=0.4 -> UNRESOLVED (A and B tie for max)."""
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("db-2", SourceType.DATABASE)
        source_c = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        fact_c = _make_fact(subject="X", predicate="is Y", obj="C", source=source_c)
        contradiction = _make_contradiction(
            fact_a.fact_id, fact_b.fact_id, fact_c.fact_id
        )
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 1.0),
            _make_assessment(source_c, 0.4),
        ]

        resolutions = resolve_contradictions(
            [fact_a, fact_b, fact_c], [contradiction], assessments
        )

        resolution = resolutions[0]
        assert resolution.outcome == ResolutionOutcome.UNRESOLVED
        assert resolution.winning_fact_id is None
        assert resolution.superseded_fact_ids == []

    def test_f_no_contradictions_no_resolutions(self) -> None:
        source = _make_source("doc-1", SourceType.DOCUMENT)
        fact = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        resolutions = resolve_contradictions([fact], [], [])
        assert resolutions == []

    def test_g_non_conflicting_fact_never_becomes_winner(self) -> None:
        """A fact outside any ContradictionSet must never appear as a
        winning_fact_id or superseded_fact_id anywhere in the output."""
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        source_outside = _make_source("doc-1", SourceType.DOCUMENT)

        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        outside_fact = _make_fact(
            subject="Unrelated", predicate="is Z", obj="C", source=source_outside
        )
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
            _make_assessment(source_outside, 1.0),
        ]

        resolutions = resolve_contradictions(
            [fact_a, fact_b, outside_fact], [contradiction], assessments
        )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.winning_fact_id != outside_fact.fact_id
        assert outside_fact.fact_id not in resolution.superseded_fact_ids

    def test_h_facts_unchanged(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
        ]
        snapshot_a = fact_a.model_copy(deep=True)
        snapshot_b = fact_b.model_copy(deep=True)

        resolve_contradictions([fact_a, fact_b], [contradiction], assessments)

        assert fact_a == snapshot_a
        assert fact_b == snapshot_b
        assert fact_a.status is FactStatus.DISCOVERED
        assert fact_b.status is FactStatus.DISCOVERED

    def test_i_contradictions_unchanged(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
        ]
        snapshot = contradiction.model_copy(deep=True)

        resolve_contradictions([fact_a, fact_b], [contradiction], assessments)

        assert contradiction == snapshot

    def test_j_authority_assessments_unchanged(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessment_a = _make_assessment(source_a, 1.0)
        assessment_b = _make_assessment(source_b, 0.4)
        assessments = [assessment_a, assessment_b]
        snapshot_a = assessment_a.model_copy(deep=True)
        snapshot_b = assessment_b.model_copy(deep=True)

        resolve_contradictions([fact_a, fact_b], [contradiction], assessments)

        assert assessment_a == snapshot_a
        assert assessment_b == snapshot_b

    def test_k_no_arbitrary_tiebreaking_across_repeated_runs(self) -> None:
        """The same tied case must never select different winners across
        repeated calls, or select any winner at all."""
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("doc-2", SourceType.DOCUMENT)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [
            _make_assessment(source_a, 0.8),
            _make_assessment(source_b, 0.8),
        ]
        facts = [fact_a, fact_b]

        for _ in range(20):
            resolutions = resolve_contradictions(facts, [contradiction], assessments)
            assert resolutions[0].outcome == ResolutionOutcome.UNRESOLVED
            assert resolutions[0].winning_fact_id is None

        reversed_resolutions = resolve_contradictions(
            list(reversed(facts)), [contradiction], list(reversed(assessments))
        )
        assert reversed_resolutions[0].outcome == ResolutionOutcome.UNRESOLVED

    def test_l_resolution_ids_are_unique(self) -> None:
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
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
            _make_assessment(source_c, 0.6),
            _make_assessment(source_d, 0.2),
        ]

        resolutions = resolve_contradictions(
            [fact_a, fact_b, fact_c, fact_d],
            [contradiction_1, contradiction_2],
            assessments,
        )

        resolution_ids = [r.resolution_id for r in resolutions]
        assert len(resolution_ids) == len(set(resolution_ids))

    def test_m_rationale_present_and_meaningful(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
        ]

        resolutions = resolve_contradictions(
            [fact_a, fact_b], [contradiction], assessments
        )

        rationale = resolutions[0].rationale
        assert rationale
        assert len(rationale) > 20

    def test_n_timestamp_is_timezone_aware_utc(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
        ]

        resolutions = resolve_contradictions(
            [fact_a, fact_b], [contradiction], assessments
        )

        resolved_at = resolutions[0].resolved_at
        assert resolved_at.tzinfo is not None
        assert resolved_at.tzinfo == UTC

    def test_never_produces_all_rejected(self) -> None:
        """v0.1's purely comparative policy has no mechanism to reach
        ALL_REJECTED — confirm it never appears across a range of
        scenarios (winner, tie, missing assessment)."""
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)

        winner_case = resolve_contradictions(
            [fact_a, fact_b],
            [contradiction],
            [_make_assessment(source_a, 1.0), _make_assessment(source_b, 0.4)],
        )
        tie_case = resolve_contradictions(
            [fact_a, fact_b],
            [contradiction],
            [_make_assessment(source_a, 0.8), _make_assessment(source_b, 0.8)],
        )
        missing_case = resolve_contradictions(
            [fact_a, fact_b], [contradiction], [_make_assessment(source_a, 1.0)]
        )

        for resolutions in (winner_case, tie_case, missing_case):
            assert all(
                r.outcome != ResolutionOutcome.ALL_REJECTED for r in resolutions
            )

    def test_empty_input(self) -> None:
        assert resolve_contradictions([], [], []) == []


class TestRunStage5:
    def test_produces_valid_stage5_output(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        assessments = [
            _make_assessment(source_a, 1.0),
            _make_assessment(source_b, 0.4),
        ]

        output = run_stage5(
            Stage5Input(
                facts=[fact_a, fact_b],
                contradictions=[contradiction],
                authority_assessments=assessments,
            )
        )

        assert output.facts == [fact_a, fact_b]
        assert output.contradictions == [contradiction]
        assert output.authority_assessments == assessments
        assert len(output.resolutions) == 1
        assert isinstance(output.resolutions[0], Resolution)

    def test_empty_input(self) -> None:
        output = run_stage5(
            Stage5Input(facts=[], contradictions=[], authority_assessments=[])
        )
        assert output.facts == []
        assert output.contradictions == []
        assert output.authority_assessments == []
        assert output.resolutions == []
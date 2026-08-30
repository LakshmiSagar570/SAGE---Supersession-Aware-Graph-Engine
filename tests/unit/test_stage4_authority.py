"""Tests for Stage 4 (Authority Inference)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from contracts.fact_schema import (
    ConflictType,
    ContradictionID,
    ContradictionSet,
    Fact,
    FactID,
    FactStatus,
    Source,
    SourceID,
    SourceType,
)
from contracts.stage_io import Stage4Input
from sage.pipeline.stage_4.authority import infer_authority
from sage.pipeline.stage_4.stage import run_stage4


def _make_source(source_id: str, source_type: SourceType) -> Source:
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


class TestInferAuthority:
    def test_1_no_contradictions_no_assessments(self) -> None:
        source = _make_source("doc-1", SourceType.DOCUMENT)
        fact = _make_fact(
            subject="CompanyCorp", predicate="is headquartered in", obj="Austin",
            source=source,
        )
        assessments = infer_authority([fact], [])
        assert assessments == []

    def test_2_one_contradiction_produces_assessments_for_both_sources(self) -> None:
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(
            subject="CompanyCorp", predicate="is headquartered in", obj="Austin",
            source=source_a,
        )
        fact_b = _make_fact(
            subject="CompanyCorp", predicate="is headquartered in", obj="Boston",
            source=source_b,
        )
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)

        assessments = infer_authority([fact_a, fact_b], [contradiction])

        source_ids = {a.source_id for a in assessments}
        assert source_ids == {source_a.source_id, source_b.source_id}
        assert len(assessments) == 2

    def test_3_same_source_multiple_contradictions_one_assessment(self) -> None:
        """A source participating in multiple contradictions must get
        exactly one assessment, not duplicates."""
        shared_source = _make_source("db-1", SourceType.DATABASE)
        other_source_1 = _make_source("web-1", SourceType.WEB)
        other_source_2 = _make_source("api-1", SourceType.API)

        fact_1 = _make_fact(
            subject="CompanyCorp", predicate="is headquartered in", obj="Austin",
            source=shared_source,
        )
        fact_2 = _make_fact(
            subject="CompanyCorp", predicate="is headquartered in", obj="Boston",
            source=other_source_1,
        )
        fact_3 = _make_fact(
            subject="CompanyCorp", predicate="is the CEO of", obj="Someone",
            source=shared_source,
        )
        fact_4 = _make_fact(
            subject="CompanyCorp", predicate="is the CEO of", obj="Someone Else",
            source=other_source_2,
        )
        contradiction_1 = _make_contradiction(fact_1.fact_id, fact_2.fact_id)
        contradiction_2 = _make_contradiction(fact_3.fact_id, fact_4.fact_id)

        assessments = infer_authority(
            [fact_1, fact_2, fact_3, fact_4], [contradiction_1, contradiction_2]
        )

        shared_source_assessments = [
            a for a in assessments if a.source_id == shared_source.source_id
        ]
        assert len(shared_source_assessments) == 1
        assert len(assessments) == 3  # shared, other_1, other_2

    def test_4_correct_source_ids(self) -> None:
        """Every assessment must correspond to a source actually
        involved in a contradiction — no assessments for uninvolved
        sources."""
        involved_source = _make_source("doc-1", SourceType.DOCUMENT)
        uninvolved_source = _make_source("web-1", SourceType.WEB)

        involved_fact_a = _make_fact(
            subject="CompanyCorp", predicate="is headquartered in", obj="Austin",
            source=involved_source,
        )
        involved_fact_b = _make_fact(
            subject="CompanyCorp", predicate="is headquartered in", obj="Boston",
            source=involved_source,
        )
        uninvolved_fact = _make_fact(
            subject="CompanyCorp", predicate="was founded on", obj="2018-03-12",
            source=uninvolved_source,
        )
        contradiction = _make_contradiction(
            involved_fact_a.fact_id, involved_fact_b.fact_id
        )

        assessments = infer_authority(
            [involved_fact_a, involved_fact_b, uninvolved_fact], [contradiction]
        )

        source_ids = {a.source_id for a in assessments}
        assert uninvolved_source.source_id not in source_ids

    def test_5_score_bounds(self) -> None:
        source_a = _make_source("db-1", SourceType.DATABASE)
        source_b = _make_source("other-1", SourceType.OTHER)
        fact_a = _make_fact(
            subject="X", predicate="is Y", obj="A", source=source_a,
        )
        fact_b = _make_fact(
            subject="X", predicate="is Y", obj="B", source=source_b,
        )
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)

        assessments = infer_authority([fact_a, fact_b], [contradiction])

        for assessment in assessments:
            assert 0.0 <= assessment.authority_score <= 1.0

    def test_6_deterministic_score_per_source_type(self) -> None:
        """Same SourceType must always yield the same authority_score,
        across repeated runs. Timestamps are not compared."""
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        facts = [fact_a, fact_b]
        contradictions = [contradiction]

        first_run = infer_authority(facts, contradictions)
        second_run = infer_authority(facts, contradictions)

        first_scores = {a.source_id: a.authority_score for a in first_run}
        second_scores = {a.source_id: a.authority_score for a in second_run}
        assert first_scores == second_scores

    def test_7_facts_unchanged(self) -> None:
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)

        snapshot_a = fact_a.model_copy(deep=True)
        snapshot_b = fact_b.model_copy(deep=True)

        infer_authority([fact_a, fact_b], [contradiction])

        assert fact_a == snapshot_a
        assert fact_b == snapshot_b

    def test_8_contradictions_unchanged(self) -> None:
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)
        snapshot = contradiction.model_copy(deep=True)

        infer_authority([fact_a, fact_b], [contradiction])

        assert contradiction == snapshot

    def test_9_no_resolution_behavior(self) -> None:
        """Stage 4 must not delete facts, merge facts, change status,
        modify temporal fields, remove a contradiction, or produce
        anything resembling a Resolution."""
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)

        output = run_stage4(
            Stage4Input(facts=[fact_a, fact_b], contradictions=[contradiction])
        )

        assert len(output.facts) == 2
        assert all(f.status is FactStatus.DISCOVERED for f in output.facts)
        assert len(output.contradictions) == 1
        assert not hasattr(output, "resolution")
        assert not hasattr(output, "winning_fact_id")

    def test_10_rationale_present_and_policy_based(self) -> None:
        source = _make_source("doc-1", SourceType.DOCUMENT)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source)
        other_source = _make_source("web-1", SourceType.WEB)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=other_source)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)

        assessments = infer_authority([fact_a, fact_b], [contradiction])

        # Verdict phrases a resolution-style rationale would use, but an
        # authority-basis rationale must not. Checking for these directly
        # (rather than a bare "correct" substring) avoids false-flagging
        # the required disclaimer language itself, e.g. "not a
        # determination of factual correctness" — which correctly
        # contains "correct" while being the opposite of a verdict.
        verdict_phrases = (
            "is correct",
            "is incorrect",
            "is wrong",
            "is true",
            "is false",
            "wins",
            "loses",
        )
        for assessment in assessments:
            assert assessment.rationale is not None
            assert len(assessment.rationale) > 0
            rationale_lower = assessment.rationale.lower()
            for phrase in verdict_phrases:
                assert phrase not in rationale_lower, (
                    f"Rationale contains verdict phrase {phrase!r}, which "
                    f"belongs to Stage 5 resolution, not Stage 4 authority "
                    f"assessment: {assessment.rationale!r}"
                )
            # Must still explicitly reference the policy basis.
            assert "policy" in rationale_lower

    def test_empty_facts_and_contradictions(self) -> None:
        assert infer_authority([], []) == []

    def test_policy_scores_match_documented_policy(self) -> None:
        """Cross-check the implemented scores against the exact table
        in docs/authority_policy.md, so a drift between the doc and
        the code is caught by tests rather than discovered later."""
        expected = {
            SourceType.DATABASE: 1.00,
            SourceType.DOCUMENT: 0.80,
            SourceType.API: 0.60,
            SourceType.WEB: 0.40,
            SourceType.OTHER: 0.20,
        }
        facts = []
        for i, source_type in enumerate(expected):
            source = _make_source(f"src-{i}", source_type)
            facts.append(
                _make_fact(subject="X", predicate="is Y", obj=str(i), source=source)
            )
        # Pair every fact with the next one so each source participates
        # in at least one contradiction.
        contradictions = [
            _make_contradiction(facts[i].fact_id, facts[i + 1].fact_id)
            for i in range(len(facts) - 1)
        ]

        assessments = infer_authority(facts, contradictions)
        scores_by_source_type = {
            fact.source.source_type: next(
                a.authority_score
                for a in assessments
                if a.source_id == fact.source.source_id
            )
            for fact in facts
        }

        assert scores_by_source_type == expected


class TestRunStage4:
    def test_produces_valid_stage4_output(self) -> None:
        source_a = _make_source("doc-1", SourceType.DOCUMENT)
        source_b = _make_source("web-1", SourceType.WEB)
        fact_a = _make_fact(subject="X", predicate="is Y", obj="A", source=source_a)
        fact_b = _make_fact(subject="X", predicate="is Y", obj="B", source=source_b)
        contradiction = _make_contradiction(fact_a.fact_id, fact_b.fact_id)

        output = run_stage4(
            Stage4Input(facts=[fact_a, fact_b], contradictions=[contradiction])
        )

        assert output.facts == [fact_a, fact_b]
        assert output.contradictions == [contradiction]
        assert len(output.authority_assessments) == 2

    def test_empty_input(self) -> None:
        output = run_stage4(Stage4Input(facts=[], contradictions=[]))
        assert output.facts == []
        assert output.contradictions == []
        assert output.authority_assessments == []
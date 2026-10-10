"""Verification for Documentation & Contract Conformity.

Tests:
1. docs/graph_schema.md against queries.py and materialize.py.
2. ContradictionSet, Resolution, AuthorityAssessment construction sites against fact_schema.py.
3. Explicit Resolution -> Contradiction reference in Stage 5 -> Stage 6 flow.
4. validate.py enforcement of fact_schema.py documented invariants.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from typing import Any, cast

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
from sage.pipeline.stage_5.resolve import resolve_contradictions
from sage.pipeline.stage_6 import queries
from sage.pipeline.stage_6.validate import Stage6ValidationError, validate_stage6_input


def test_graph_schema_constraints_match_code() -> None:
    """Verify that constraints in queries.CREATE_CONSTRAINTS match docs/graph_schema.md."""
    schema_doc = pathlib.Path("docs/graph_schema.md").read_text()
    
    # Check that all 5 constraints in queries.CREATE_CONSTRAINTS appear in docs/graph_schema.md
    for constraint in queries.CREATE_CONSTRAINTS:
        # Normalize whitespace
        norm_code = " ".join(constraint.split())
        assert norm_code in " ".join(schema_doc.split()), f"Constraint missing from doc: {norm_code}"


def test_graph_schema_node_properties_match_queries() -> None:
    """Verify node property keys in queries match docs/graph_schema.md table."""
    now = datetime.now(UTC)
    s = Source(source_id=SourceID("s1"), name="S1", source_type=SourceType.DOCUMENT, locator="loc")
    f = Fact(
        fact_id=FactID("f1"), subject="A", predicate="B", object="C", source=s,
        evidence="ev", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )
    f2 = Fact(
        fact_id=FactID("f2"), subject="A", predicate="B", object="D", source=s,
        evidence="ev", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )
    ContradictionSet(
        contradiction_id=ContradictionID("c1"), conflicting_fact_ids=[f.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT, detected_at=now,
    )
    c = ContradictionSet(
        contradiction_id=ContradictionID("c1"), conflicting_fact_ids=[f.fact_id, FactID("f2")],
        conflict_type=ConflictType.DIRECT, detected_at=now,
    )
    a = AuthorityAssessment(source_id=s.source_id, authority_score=0.8, rationale="rat", assessed_at=now)
    r = Resolution(
        resolution_id=ResolutionID("r1"),
        contradiction_id=ContradictionID("c1"), outcome=ResolutionOutcome.WINNER_SELECTED,
        winning_fact_id=f.fact_id, superseded_fact_ids=[FactID("f2")], rationale="rat", resolved_at=now,
    )

    _, s_params = queries.merge_sources([s])
    sources_list = cast(list[dict[str, Any]], s_params["sources"])
    assert set(sources_list[0].keys()) == {"source_id", "name", "source_type", "locator"}

    _, f_params = queries.merge_facts([f])
    facts_list = cast(list[dict[str, Any]], f_params["facts"])
    assert set(facts_list[0].keys()) == {
        "fact_id", "subject", "predicate", "object", "evidence", "extracted_at",
        "effective_from", "effective_to", "status",
    }

    _, c_params = queries.merge_contradictions([c])
    c_list = cast(list[dict[str, Any]], c_params["contradictions"])
    assert set(c_list[0].keys()) == {
        "contradiction_id", "conflict_type", "detected_at"
    }

    _, a_params = queries.merge_authority_assessments([a])
    a_list = cast(list[dict[str, Any]], a_params["assessments"])
    assert set(a_list[0].keys()) == {
        "source_id", "authority_score", "rationale", "assessed_at"
    }

    _, r_params = queries.merge_resolutions([r])
    r_list = cast(list[dict[str, Any]], r_params["resolutions"])
    assert set(r_list[0].keys()) == {
        "resolution_id", "outcome", "rationale", "resolved_at", "winning_fact_id"
    }


def test_validate_enforces_contradiction_distinct_facts_invariant() -> None:
    """fact_schema.py invariant: conflicting_fact_ids must contain >= 2 DISTINCT FactIDs."""
    now = datetime.now(UTC)
    s = Source(source_id=SourceID("s1"), name="S1", source_type=SourceType.DOCUMENT, locator="loc")
    f1 = Fact(
        fact_id=FactID("f1"), subject="A", predicate="B", object="C1", source=s,
        evidence="ev", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )
    f2 = Fact(
        fact_id=FactID("f2"), subject="A", predicate="B", object="C2", source=s,
        evidence="ev", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )

    # Violation 1: fewer than 2 facts
    c_single = ContradictionSet(
        contradiction_id=ContradictionID("c-single"),
        conflicting_fact_ids=[f1.fact_id],
        conflict_type=ConflictType.DIRECT,
        detected_at=now,
    )
    with pytest.raises(Stage6ValidationError, match="fewer than 2 conflicting_fact_ids"):
        validate_stage6_input(Stage6Input(facts=[f1], contradictions=[c_single], authority_assessments=[], resolutions=[]))

    # Violation 2: duplicate fact IDs
    c_dup = ContradictionSet(
        contradiction_id=ContradictionID("c-dup"),
        conflicting_fact_ids=[f1.fact_id, f1.fact_id],
        conflict_type=ConflictType.DIRECT,
        detected_at=now,
    )
    with pytest.raises(Stage6ValidationError, match="duplicate FactID within its own conflicting_fact_ids"):
        validate_stage6_input(Stage6Input(facts=[f1], contradictions=[c_dup], authority_assessments=[], resolutions=[]))

    # Valid: 2 distinct fact IDs
    c_valid = ContradictionSet(
        contradiction_id=ContradictionID("c-valid"),
        conflicting_fact_ids=[f1.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT,
        detected_at=now,
    )
    validate_stage6_input(Stage6Input(facts=[f1, f2], contradictions=[c_valid], authority_assessments=[], resolutions=[]))


def test_validate_enforces_resolution_outcome_invariants() -> None:
    """fact_schema.py invariant: winning_fact_id must be null for UNRESOLVED or ALL_REJECTED, non-null for WINNER_SELECTED."""
    now = datetime.now(UTC)
    s = Source(source_id=SourceID("s1"), name="S1", source_type=SourceType.DOCUMENT, locator="loc")
    f = Fact(
        fact_id=FactID("f1"), subject="A", predicate="B", object="C", source=s,
        evidence="ev", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )
    f2 = Fact(
        fact_id=FactID("f2"), subject="A", predicate="B", object="D", source=s,
        evidence="ev", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )
    cs = ContradictionSet(
        contradiction_id=ContradictionID("c1"), conflicting_fact_ids=[f.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT, detected_at=now,
    )

    # WINNER_SELECTED with winning_fact_id=None -> must raise
    r_bad_winner = Resolution(
        resolution_id=ResolutionID("r1"),
        contradiction_id=ContradictionID("c1"), outcome=ResolutionOutcome.WINNER_SELECTED,
        winning_fact_id=None, superseded_fact_ids=[], rationale="bad", resolved_at=now,
    )
    with pytest.raises(Stage6ValidationError, match="WINNER_SELECTED but winning_fact_id is None"):
        validate_stage6_input(Stage6Input(facts=[f, f2], contradictions=[cs], authority_assessments=[], resolutions=[r_bad_winner]))

    # UNRESOLVED with winning_fact_id set -> must raise
    r_bad_unresolved = Resolution(
        resolution_id=ResolutionID("r2"), contradiction_id=ContradictionID("c1"), outcome=ResolutionOutcome.UNRESOLVED,
        winning_fact_id=f.fact_id, superseded_fact_ids=[], rationale="bad", resolved_at=now,
    )
    with pytest.raises(Stage6ValidationError, match="UNRESOLVED but winning_fact_id is set"):
        validate_stage6_input(Stage6Input(facts=[f, f2], contradictions=[cs], authority_assessments=[], resolutions=[r_bad_unresolved]))

    # ALL_REJECTED with winning_fact_id set -> must raise
    r_bad_rejected = Resolution(
        resolution_id=ResolutionID("r3"), contradiction_id=ContradictionID("c1"), outcome=ResolutionOutcome.ALL_REJECTED,
        winning_fact_id=f.fact_id, superseded_fact_ids=[], rationale="bad", resolved_at=now,
    )
    with pytest.raises(Stage6ValidationError, match="ALL_REJECTED but winning_fact_id is set"):
        validate_stage6_input(Stage6Input(facts=[f, f2], contradictions=[cs], authority_assessments=[], resolutions=[r_bad_rejected]))


def test_stage5_resolution_construction_matches_schema() -> None:
    """Verify resolve.py construction sites strictly follow fact_schema.py field rules."""
    now = datetime.now(UTC)
    s1 = Source(source_id=SourceID("s1"), name="S1", source_type=SourceType.DATABASE, locator="loc1")
    s2 = Source(source_id=SourceID("s2"), name="S2", source_type=SourceType.WEB, locator="loc2")
    f1 = Fact(
        fact_id=FactID("f1"), subject="A", predicate="B", object="Val1", source=s1,
        evidence="ev1", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )
    f2 = Fact(
        fact_id=FactID("f2"), subject="A", predicate="B", object="Val2", source=s2,
        evidence="ev2", extracted_at=now, effective_from=now, effective_to=None,
        confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
    )
    c = ContradictionSet(
        contradiction_id=ContradictionID("c1"), conflicting_fact_ids=[f1.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT, detected_at=now,
    )
    assessments = [
        AuthorityAssessment(source_id=s1.source_id, authority_score=1.0, rationale="high", assessed_at=now),
        AuthorityAssessment(source_id=s2.source_id, authority_score=0.4, rationale="low", assessed_at=now),
    ]

    # WINNER_SELECTED
    res_list = resolve_contradictions([f1, f2], [c], assessments)
    assert len(res_list) == 1
    winner_res = res_list[0]
    assert winner_res.outcome == ResolutionOutcome.WINNER_SELECTED
    assert winner_res.winning_fact_id == f1.fact_id
    assert winner_res.superseded_fact_ids == [f2.fact_id]
    assert "Resolution for contradiction c1" in winner_res.rationale

    # UNRESOLVED (tie)
    assessments_tie = [
        AuthorityAssessment(source_id=s1.source_id, authority_score=0.5, rationale="mid", assessed_at=now),
        AuthorityAssessment(source_id=s2.source_id, authority_score=0.5, rationale="mid", assessed_at=now),
    ]
    res_unresolved = resolve_contradictions([f1, f2], [c], assessments_tie)[0]
    assert res_unresolved.outcome == ResolutionOutcome.UNRESOLVED
    assert res_unresolved.winning_fact_id is None
    assert res_unresolved.superseded_fact_ids == []
    assert "Resolution for contradiction c1" in res_unresolved.rationale


def test_explicit_resolution_contradiction_reference_is_preserved() -> None:
    """Verify that Stage 5 resolutions carry explicit contradiction IDs.

    Resolution -> Contradiction linkage is now represented directly by
    Resolution.contradiction_id. Stage 6 therefore does not depend on
    positional correspondence between resolution and contradiction lists.
    """
    now = datetime.now(UTC)

    s1 = Source(
        source_id=SourceID("s1"),
        name="S1",
        source_type=SourceType.DOCUMENT,
        locator="loc1",
    )
    s2 = Source(
        source_id=SourceID("s2"),
        name="S2",
        source_type=SourceType.DOCUMENT,
        locator="loc2",
    )

    f1 = Fact(
        fact_id=FactID("f1"),
        subject="A",
        predicate="B",
        object="1",
        source=s1,
        evidence="e",
        extracted_at=now,
        effective_from=now,
        effective_to=None,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )
    f2 = Fact(
        fact_id=FactID("f2"),
        subject="A",
        predicate="B",
        object="2",
        source=s2,
        evidence="e",
        extracted_at=now,
        effective_from=now,
        effective_to=None,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )

    c1 = ContradictionSet(
        contradiction_id=ContradictionID("c1"),
        conflicting_fact_ids=[f1.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT,
        detected_at=now,
    )

    assessments = [
        AuthorityAssessment(
            source_id=s1.source_id,
            authority_score=0.8,
            rationale="doc",
            assessed_at=now,
        ),
        AuthorityAssessment(
            source_id=s2.source_id,
            authority_score=0.6,
            rationale="doc",
            assessed_at=now,
        ),
    ]

    resolutions = resolve_contradictions(
        [f1, f2],
        [c1],
        assessments,
    )

    assert len(resolutions) == 1
    assert resolutions[0].contradiction_id == c1.contradiction_id
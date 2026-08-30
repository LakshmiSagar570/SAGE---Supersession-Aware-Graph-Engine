"""
Stage 6 — Structural Validation.

Responsibility: verify that a Stage6Input's cross-references are
internally consistent, before any future materialization step touches
it.

    Stage6Input
          |
          v
    validate_stage6_input()
          |
          ├── valid   -> returns normally (no return value)
          └── invalid -> raises Stage6ValidationError

This module is deliberately narrow. It validates only what the
EXISTING contracts already make checkable — reference integrity and ID
uniqueness. It does not construct a graph, does not define or return a
Stage6Output (the real contract explicitly leaves that type
undefined — see contracts/stage_io.py's Stage6Input docstring), does
not create nodes or relationships, does not infer any relationship
that Stage 5 didn't already establish, and never mutates its input.

What this module checks, per spec:

    1. Every Resolution.winning_fact_id, when non-null, exists in
       Stage6Input.facts.
    2. Every ID in Resolution.superseded_fact_ids exists in facts.
    3. Every ContradictionSet.conflicting_fact_ids entry exists in
       facts.
    4. fact_id values are unique within the input.
    5. source_id values are internally consistent: if two Facts'
       Source objects share a source_id, they must be the same
       Source (same source_type/name/locator) — not two different
       sources accidentally colliding on an ID.
    6. contradiction_id values are unique.
    7. resolution_id values are unique.
    8. Every AuthorityAssessment.source_id corresponds to a source_id
       actually present among facts' sources, and AuthorityAssessment
       entries themselves don't duplicate a source_id (Stage 4's own
       "one assessment per source" invariant, re-checked here as a
       structural property of the input rather than trusted blindly).

What this module does NOT do: repair a bad reference, drop an invalid
entry and continue, or guess at what a broken reference "probably"
meant. Every violation is a hard failure via Stage6ValidationError,
naming the exact broken reference — fail closed, per spec.
"""

from __future__ import annotations

from contracts.fact_schema import (
    AuthorityAssessment,
    ContradictionSet,
    Fact,
    FactID,
    Resolution,
    Source,
    SourceID,
)
from contracts.stage_io import Stage6Input


class Stage6ValidationError(Exception):
    """Raised when a Stage6Input's cross-references are not internally
    consistent. The message always names the specific broken
    reference — never a generic "validation failed"."""


def validate_stage6_input(stage_input: Stage6Input) -> None:
    """Validate a Stage6Input's structural integrity.

    Returns None on success. Raises Stage6ValidationError on the first
    violation found, naming the exact broken reference. Does not
    mutate stage_input or anything inside it.

    Checks run in a fixed order (uniqueness checks first, then
    reference checks) so that a given invalid input always fails on
    the same check for the same reason — required for the
    determinism test (spec item K).
    """
    _check_unique_fact_ids(stage_input.facts)
    _check_unique_contradiction_ids(stage_input.contradictions)
    _check_unique_resolution_ids(stage_input.resolutions)
    _check_consistent_source_ids(stage_input.facts)
    _check_unique_assessment_source_ids(stage_input.authority_assessments)

    fact_ids = {fact.fact_id for fact in stage_input.facts}
    source_ids = {fact.source.source_id for fact in stage_input.facts}

    _check_contradiction_fact_references(stage_input.contradictions, fact_ids)
    _check_resolution_fact_references(stage_input.resolutions, fact_ids)
    _check_assessment_source_references(stage_input.authority_assessments, source_ids)


def _check_unique_fact_ids(facts: list[Fact]) -> None:
    seen: set[FactID] = set()
    for fact in facts:
        if fact.fact_id in seen:
            raise Stage6ValidationError(
                f"Duplicate fact_id in input: {fact.fact_id} appears more "
                f"than once among facts."
            )
        seen.add(fact.fact_id)


def _check_unique_contradiction_ids(contradictions: list[ContradictionSet]) -> None:
    seen: set[str] = set()
    for contradiction in contradictions:
        key = str(contradiction.contradiction_id)
        if key in seen:
            raise Stage6ValidationError(
                f"Duplicate contradiction_id in input: "
                f"{contradiction.contradiction_id} appears more than once "
                f"among contradictions."
            )
        seen.add(key)


def _check_unique_resolution_ids(resolutions: list[Resolution]) -> None:
    seen: set[str] = set()
    for resolution in resolutions:
        key = str(resolution.resolution_id)
        if key in seen:
            raise Stage6ValidationError(
                f"Duplicate resolution_id in input: {resolution.resolution_id} "
                f"appears more than once among resolutions."
            )
        seen.add(key)


def _check_consistent_source_ids(facts: list[Fact]) -> None:
    """If two facts' Source objects share a source_id, they must
    describe the same Source — not two different sources that happen
    to collide on the same identifier."""
    sources_by_id: dict[str, Source] = {}
    for fact in facts:
        source = fact.source
        key = str(source.source_id)
        existing = sources_by_id.get(key)
        if existing is None:
            sources_by_id[key] = source
        elif existing != source:
            raise Stage6ValidationError(
                f"Inconsistent Source for source_id {source.source_id}: "
                f"fact {fact.fact_id} references a Source that differs "
                f"from another fact already using the same source_id "
                f"({existing!r} vs {source!r})."
            )


def _check_unique_assessment_source_ids(
    authority_assessments: list[AuthorityAssessment],
) -> None:
    """Stage 4's own invariant (one assessment per source) re-checked
    here as a property of the Stage 6 input, rather than trusted
    blindly from an upstream stage."""
    seen: set[str] = set()
    for assessment in authority_assessments:
        key = str(assessment.source_id)
        if key in seen:
            raise Stage6ValidationError(
                f"Duplicate AuthorityAssessment for source_id "
                f"{assessment.source_id}: an authority assessment for "
                f"this source appears more than once in the input."
            )
        seen.add(key)


def _check_contradiction_fact_references(
    contradictions: list[ContradictionSet], fact_ids: set[FactID]
) -> None:
    for contradiction in contradictions:
        for fact_id in contradiction.conflicting_fact_ids:
            if fact_id not in fact_ids:
                raise Stage6ValidationError(
                    f"ContradictionSet {contradiction.contradiction_id} "
                    f"references unknown FactID {fact_id}."
                )


def _check_resolution_fact_references(
    resolutions: list[Resolution], fact_ids: set[FactID]
) -> None:
    for resolution in resolutions:
        if (
            resolution.winning_fact_id is not None
            and resolution.winning_fact_id not in fact_ids
        ):
            raise Stage6ValidationError(
                f"Resolution {resolution.resolution_id} references unknown "
                f"winning_fact_id {resolution.winning_fact_id}."
            )
        for fact_id in resolution.superseded_fact_ids:
            if fact_id not in fact_ids:
                raise Stage6ValidationError(
                    f"Resolution {resolution.resolution_id} references "
                    f"unknown superseded FactID {fact_id}."
                )


def _check_assessment_source_references(
    authority_assessments: list[AuthorityAssessment], fact_source_ids: set[SourceID]
) -> None:
    for assessment in authority_assessments:
        if assessment.source_id not in fact_source_ids:
            raise Stage6ValidationError(
                f"AuthorityAssessment references unknown source_id "
                f"{assessment.source_id}: no fact in the input has a "
                f"Source with this source_id."
            )
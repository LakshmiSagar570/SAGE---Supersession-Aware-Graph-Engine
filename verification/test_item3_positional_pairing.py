"""Verification for Open Item 3: explicit Resolution -> Contradiction reference.

The Resolution contract now contains a required `contradiction_id`.
Stage 6 must therefore use that explicit reference rather than positional
correspondence between resolutions and contradictions.

Verifies:
1. Each Resolution carries its originating ContradictionSet ID.
2. Resolution-to-Contradiction mapping remains correct when resolutions
   are reordered.
3. The Resolution reference is independent of list position.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.fact_schema import (
    ConflictType,
    ContradictionID,
    ContradictionSet,
    FactID,
    Resolution,
    ResolutionID,
    ResolutionOutcome,
)


def _make_contradiction(name: str) -> ContradictionSet:
    return ContradictionSet(
        contradiction_id=ContradictionID(f"contra-{name}"),
        conflicting_fact_ids=[FactID("f1"), FactID("f2")],
        conflict_type=ConflictType.DIRECT,
        detected_at=datetime.now(UTC),
    )


def _make_resolution(
    name: str,
    contradiction_id: ContradictionID,
) -> Resolution:
    return Resolution(
        resolution_id=ResolutionID(f"res-{name}"),
        contradiction_id=contradiction_id,
        outcome=ResolutionOutcome.UNRESOLVED,
        winning_fact_id=None,
        superseded_fact_ids=[],
        rationale=f"Rationale for {name}",
        resolved_at=datetime.now(UTC),
    )


def test_resolution_contains_explicit_contradiction_reference() -> None:
    c1 = _make_contradiction("1")
    c2 = _make_contradiction("2")

    r1 = _make_resolution("1", c1.contradiction_id)
    r2 = _make_resolution("2", c2.contradiction_id)

    assert r1.contradiction_id == c1.contradiction_id
    assert r2.contradiction_id == c2.contradiction_id


def test_resolution_reference_survives_reordering() -> None:
    c1 = _make_contradiction("1")
    c2 = _make_contradiction("2")

    r1 = _make_resolution("1", c1.contradiction_id)
    r2 = _make_resolution("2", c2.contradiction_id)

    # Deliberately reorder the resolutions.
    resolutions = [r2, r1]

    mapping = {
        str(r.resolution_id): str(r.contradiction_id)
        for r in resolutions
    }

    # Mapping comes from each Resolution's explicit ID, not list position.
    assert mapping["res-1"] == "contra-1"
    assert mapping["res-2"] == "contra-2"


def test_different_resolution_order_does_not_change_references() -> None:
    c1 = _make_contradiction("1")
    c2 = _make_contradiction("2")

    r1 = _make_resolution("1", c1.contradiction_id)
    r2 = _make_resolution("2", c2.contradiction_id)

    original = {
        str(r.resolution_id): str(r.contradiction_id)
        for r in [r1, r2]
    }

    reordered = {
        str(r.resolution_id): str(r.contradiction_id)
        for r in [r2, r1]
    }

    assert reordered == original
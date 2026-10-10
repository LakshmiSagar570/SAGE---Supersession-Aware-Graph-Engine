"""
Stage 3 — Contradiction Detection (contract-level packaging).

Converts the candidate fact pairs identified by pairing.py into real
ContradictionSet objects, using the confirmed contract:

    ContradictionSet
    ├── contradiction_id: ContradictionID
    ├── conflicting_fact_ids: list[FactID]
    ├── conflict_type: ConflictType
    └── detected_at: datetime

Pipeline:

    Stage3Input.facts
            |
            v
    pairing.find_contradiction_pairs()
            |
            v
    [(Fact, Fact), ...]
            |
            v
    ContradictionSet
            |
            v
    Stage3Output.contradictions

Facts are never modified here — this module only reads pairing.py's
output and repackages it. No status changes, no new fact_ids, no
deletion, no merging.

--------------------------------------------------------------------
CONFLICT_TYPE CLASSIFICATION (a real interpretive call, flagged
explicitly rather than left implicit):

The confirmed contract defines exactly two ConflictType values, DIRECT
and TEMPORAL_OVERLAP, but pairing.py's find_contradiction_pairs() does
not itself distinguish between them — it only determines whether a
pair overlaps at all. This module adds the classification layer:

    DIRECT           — the two facts' effective_from values are equal.
                        Both claims are asserted for the same starting
                        point in time; the conflict is a straightforward
                        disagreement about the same moment, not really
                        a temporal-boundary question.

    TEMPORAL_OVERLAP — the two facts' effective_from values differ, but
                        their validity intervals still overlap (e.g.
                        Austin from 2020, Boston from 2022, both open-
                        ended). The conflict exists specifically because
                        the intervals overlap despite starting at
                        different points.

This is the most defensible reading available given the two-value
enum and the information already present on Fact — it does not invent
new information, and it does not touch pairing.py's core overlap
logic. But it IS an interpretive choice, not something the contract
states explicitly, and should be treated as such.
--------------------------------------------------------------------
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from contracts.fact_schema import ConflictType, ContradictionID, ContradictionSet, Fact

from .pairing import find_contradiction_pairs


def detect_contradictions(facts: list[Fact]) -> list[ContradictionSet]:
    """Detect contradictions among the given facts and package them as
    ContradictionSet objects.

    One detected_at timestamp is shared across every ContradictionSet
    produced by a single call, matching the operation-level timestamp
    convention already used in Stage 1 (extracted_at) and mirrored here
    per spec.

    Facts are never mutated. Canonical pair ordering from pairing.py is
    reused directly — this function does not independently re-derive
    or re-order pairs. Empty input returns an empty list.
    """
    detected_at = datetime.now(UTC)
    pairs = find_contradiction_pairs(facts)

    return [_build_contradiction_set(pair, detected_at) for pair in pairs]


def _build_contradiction_set(
    pair: tuple[Fact, Fact], detected_at: datetime
) -> ContradictionSet:
    """Wrap one canonical fact pair into a ContradictionSet.

    conflicting_fact_ids preserves the exact order pairing.py already
    established (canonical, fact_id-based) — this function does not
    independently generate [A, B] vs [B, A] ordering.
    """
    fact_a, fact_b = pair
    return ContradictionSet(
        contradiction_id=ContradictionID(str(uuid4())),
        conflicting_fact_ids=[fact_a.fact_id, fact_b.fact_id],
        conflict_type=_classify_conflict(fact_a, fact_b),
        detected_at=detected_at,
    )


def _classify_conflict(fact_a: Fact, fact_b: Fact) -> ConflictType:
    """See module docstring, CONFLICT_TYPE CLASSIFICATION, for the full
    reasoning behind this rule. Summary: identical effective_from means
    DIRECT (same asserted moment); differing-but-overlapping means
    TEMPORAL_OVERLAP.
    """
    if fact_a.effective_from == fact_b.effective_from:
        return ConflictType.DIRECT
    return ConflictType.TEMPORAL_OVERLAP
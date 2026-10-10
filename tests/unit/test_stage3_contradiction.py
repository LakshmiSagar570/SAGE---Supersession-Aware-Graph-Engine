"""Tests for Stage 3 contradiction-candidate pairing logic (pairing.py).

These tests cover every required case from the Stage 3 spec (A-J) that
does not depend on the real ContradictionSet contract shape. Tests for
detect.py's actual return type and stage.py's orchestration are
deliberately deferred until the real contract is confirmed — see
pairing.py's module docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from contracts.fact_schema import Fact, FactID, FactStatus, Source, SourceID, SourceType
from sage.pipeline.stage_3.pairing import find_contradiction_pairs

_DUMMY_SOURCE = Source(
    source_id=SourceID("test-source"),
    name="test-source",
    source_type=SourceType.DOCUMENT,
    locator="test-source",
)


def _make_fact(
    *,
    subject: str,
    predicate: str,
    obj: str,
    effective_from: datetime,
    effective_to: datetime | None = None,
) -> Fact:
    """Build a Fact for pairing tests. fact_id is always a fresh UUID4,
    since these tests care about pairing behavior, not specific IDs."""
    now = datetime.now(UTC)
    return Fact(
        fact_id=FactID(str(uuid4())),
        subject=subject,
        predicate=predicate,
        object=obj,
        source=_DUMMY_SOURCE,
        evidence=f"{subject} {predicate} {obj}.",
        extracted_at=now,
        effective_from=effective_from,
        effective_to=effective_to,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )


class TestFindContradictionPairs:
    def test_a_no_contradictions_different_predicates_across_facts(self) -> None:
        """CompanyCorp headquartered Austin + CompanyCorp founded 2018
        → zero contradiction sets (different predicates entirely)."""
        hq = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2018, 1, 1, tzinfo=UTC),
        )
        founded = _make_fact(
            subject="CompanyCorp",
            predicate="was founded on",
            obj="2018-03-12",
            effective_from=datetime(2018, 3, 12, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([hq, founded])
        assert pairs == []

    def test_b_direct_contradiction_overlapping_validity(self) -> None:
        """Same subject/predicate, different object, overlapping validity
        → exactly one contradiction pair."""
        austin = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        boston = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Boston",
            effective_from=datetime(2020, 6, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([austin, boston])
        assert len(pairs) == 1

    def test_c_identical_claim_is_not_a_contradiction(self) -> None:
        """Same subject/predicate/object twice → not a contradiction.
        A claim never contradicts itself."""
        austin_1 = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        austin_2 = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([austin_1, austin_2])
        assert pairs == []

    def test_d_different_predicates_no_contradiction(self) -> None:
        """CompanyCorp founded 2018 + CompanyCorp headquartered Austin
        → no contradiction."""
        founded = _make_fact(
            subject="CompanyCorp",
            predicate="was founded on",
            obj="2018-03-12",
            effective_from=datetime(2018, 3, 12, tzinfo=UTC),
        )
        hq = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2018, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([founded, hq])
        assert pairs == []

    def test_e_non_overlapping_temporal_facts_no_contradiction(self) -> None:
        """Austin [2018, 2023) then Boston [2024, open) — sequential, not
        overlapping → no contradiction. The company could have moved."""
        austin = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2018, 1, 1, tzinfo=UTC),
            effective_to=datetime(2023, 12, 31, tzinfo=UTC),
        )
        boston = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Boston",
            effective_from=datetime(2024, 1, 1, tzinfo=UTC),
            effective_to=None,
        )
        pairs = find_contradiction_pairs([austin, boston])
        assert pairs == []

    def test_f_overlapping_temporal_facts_contradiction(self) -> None:
        """Austin [2020, open) and Boston [2022, open) — both open-ended,
        overlapping through the present → contradiction.

        This is the exact case that establishes effective_to=None means
        'open interval to +infinity', not 'unknown'."""
        austin = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
            effective_to=None,
        )
        boston = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Boston",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
            effective_to=None,
        )
        pairs = find_contradiction_pairs([austin, boston])
        assert len(pairs) == 1

    def test_g_ceo_fixture_pair_not_a_contradiction(self) -> None:
        """'is the CEO of' and 'was appointed CEO of' are different
        predicates (different propositions), even though they describe
        the same role — must not be treated as contradictory."""
        is_ceo = _make_fact(
            subject="Maria Chen",
            predicate="is the Chief Executive Officer of",
            obj="CompanyCorp",
            effective_from=datetime.now(UTC),
        )
        appointed_ceo = _make_fact(
            subject="Maria Chen",
            predicate="was appointed Chief Executive Officer of",
            obj="CompanyCorp",
            effective_from=datetime(2024, 1, 10, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([is_ceo, appointed_ceo])
        assert pairs == []

    def test_h_facts_remain_unchanged(self) -> None:
        """Snapshot input facts and verify pairing logic does not modify
        them — this is pure read-only analysis."""
        austin = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        boston = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Boston",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        snapshot_austin = austin.model_copy(deep=True)
        snapshot_boston = boston.model_copy(deep=True)

        find_contradiction_pairs([austin, boston])

        assert austin == snapshot_austin
        assert boston == snapshot_boston

    def test_i_empty_input(self) -> None:
        assert find_contradiction_pairs([]) == []

    def test_i_single_fact_input(self) -> None:
        """A single fact can't contradict anything by itself."""
        only_fact = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert find_contradiction_pairs([only_fact]) == []

    def test_j_no_duplicate_pairs_across_three_facts(self) -> None:
        """Three mutually-conflicting facts about the same
        subject/predicate must not produce the same pair twice, and
        must not produce (A,B) and (B,A) as separate entries."""
        austin = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        boston = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Boston",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        chicago = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Chicago",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )

        pairs = find_contradiction_pairs([austin, boston, chicago])

        # 3 facts, all mutually overlapping and all distinct objects:
        # exactly 3 unordered pairs (Austin-Boston, Austin-Chicago,
        # Boston-Chicago), no duplicates.
        assert len(pairs) == 3
        pair_id_sets = [frozenset(f.fact_id for f in pair) for pair in pairs]
        assert len(pair_id_sets) == len(set(pair_id_sets))

    def test_deterministic_across_repeated_calls(self) -> None:
        """Same input, called twice, must produce identical output
        (same pairs, same order) — Stage 3 must be deterministic."""
        austin = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        boston = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Boston",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        facts = [austin, boston]

        first_call = find_contradiction_pairs(facts)
        second_call = find_contradiction_pairs(facts)

        assert first_call == second_call

    def test_deterministic_regardless_of_input_order(self) -> None:
        """The same two facts, passed in reversed order, must still
        produce the same canonical pair — not a mirrored duplicate."""
        austin = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Austin",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        boston = _make_fact(
            subject="CompanyCorp",
            predicate="is headquartered in",
            obj="Boston",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )

        forward = find_contradiction_pairs([austin, boston])
        reversed_order = find_contradiction_pairs([boston, austin])

        forward_ids = [frozenset(f.fact_id for f in pair) for pair in forward]
        reversed_ids = [frozenset(f.fact_id for f in pair) for pair in reversed_order]
        assert forward_ids == reversed_ids



# tests/unit/test_stage3_role_contradictions.py
"""Integration-level tests for find_contradiction_pairs (pairing.py)
covering the Stage 3 semantic-identity fix's effect on role-shaped
facts.

These are additive to test_stage3_contradiction.py, not a replacement
-- that file's existing tests must continue to pass unmodified, since
this fix's default (SUBJECT_ANCHORED) path is required to reproduce
identical behavior to before. This file specifically covers the new
OBJECT_ANCHORED behavior and its boundary conditions, matching the
exact required-case table from the accepted Stage 3 semantic-identity
design.
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
    """Build a Fact for pairing tests. Matches the helper in
    test_stage3_contradiction.py exactly, duplicated here rather than
    imported so this file has no test-to-test coupling."""
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


class TestRoleBasedContradictions:
    def test_1_alice_ceo_of_x_vs_bob_ceo_of_x_is_a_contradiction(self) -> None:
        """Two different people claiming the same role at the same
        company, overlapping validity -> exactly one contradiction
        pair. This is the case the Stage 3 semantic-identity fix
        exists to correctly detect (previously: 0 contradictions,
        confirmed empirically in verification Cases C/D)."""
        alice = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        bob = _make_fact(
            subject="Bob",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2024, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([alice, bob])
        assert len(pairs) == 1

    def test_2_alice_appointed_ceo_of_x_vs_bob_appointed_ceo_of_x_is_a_contradiction(
        self,
    ) -> None:
        """Same as test 1, but using the 'was appointed {role} of'
        template instead of 'is the {role} of' -- both role-shaped
        templates must be recognized."""
        alice = _make_fact(
            subject="Alice",
            predicate="was appointed Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        bob = _make_fact(
            subject="Bob",
            predicate="was appointed Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2024, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([alice, bob])
        assert len(pairs) == 1

    def test_3_headquarters_contradiction_unchanged_by_this_fix(self) -> None:
        """X headquartered Austin vs X headquartered Miami must remain
        a contradiction exactly as before this fix -- the
        SUBJECT_ANCHORED path is untouched. This is the hard
        compatibility invariant: Cases A/B/E's shape must never change
        behavior as a result of this fix."""
        austin = _make_fact(
            subject="Company X",
            predicate="is headquartered in",
            obj="Austin, Texas",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        miami = _make_fact(
            subject="Company X",
            predicate="is headquartered in",
            obj="Miami, Florida",
            effective_from=datetime(2021, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([austin, miami])
        assert len(pairs) == 1

    def test_4_same_person_different_companies_is_not_a_contradiction(
        self,
    ) -> None:
        """Alice CEO of X vs Alice CEO of Y -- same person, same role,
        but different companies. These are not competing claims about
        the same slot (a person can legitimately be CEO of two
        different companies), so this must NOT be a contradiction."""
        alice_x = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        alice_y = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company Y",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([alice_x, alice_y])
        assert pairs == []

    def test_5_same_company_different_roles_is_not_a_contradiction(
        self,
    ) -> None:
        """Alice CEO of X vs Bob CFO of X -- different claim types
        (different roles) at the same company. A CEO and a CFO are not
        competing for the same slot, so this must NOT be a
        contradiction, even though both facts are OBJECT_ANCHORED and
        share the same anchor (Company X)."""
        alice_ceo = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        bob_cfo = _make_fact(
            subject="Bob",
            predicate="is the Chief Financial Officer of",
            obj="Company X",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([alice_ceo, bob_cfo])
        assert pairs == []

    def test_6_identical_role_claim_is_not_a_contradiction(self) -> None:
        """Same person, same role, same company stated twice is not a
        contradiction -- a claim never contradicts itself. This
        generalizes test_stage3_contradiction.py's existing
        identical-claim test to the OBJECT_ANCHORED path."""
        alice_1 = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2022, 1, 1, tzinfo=UTC),
        )
        alice_2 = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2023, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([alice_1, alice_2])
        assert pairs == []

    def test_7_non_overlapping_role_succession_is_not_flagged_as_direct_conflict_but_is_still_a_candidate(
        self,
    ) -> None:
        """Sanity check on temporal interaction: if Alice's tenure has
        a closed effective_to strictly before Bob's effective_from,
        the intervals do not overlap and this pair must not be a
        contradiction candidate at all -- confirming
        _temporal_intervals_overlap is still consulted after the claim
        key match, unchanged by this fix."""
        alice = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
            effective_to=datetime(2022, 1, 1, tzinfo=UTC),
        )
        bob = _make_fact(
            subject="Bob",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
            effective_from=datetime(2023, 1, 1, tzinfo=UTC),
        )
        pairs = find_contradiction_pairs([alice, bob])
        assert pairs == []
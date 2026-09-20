# tests/unit/test_stage3_claim_policy.py
"""Tests for Stage 3's claim-key derivation policy (claim_policy.py).

These tests cover the Stage 3 semantic-identity fix (accepted design
v2): derive_claim_key's classification of SUBJECT_ANCHORED vs.
OBJECT_ANCHORED predicates, and the exact key each produces. Written to
match the existing test_stage3_contradiction.py conventions (_make_fact
helper, _DUMMY_SOURCE, class-based grouping).

Per the accepted design, Fact itself is unchanged -- these tests
exercise a pure function that only reads fact.subject, fact.predicate,
and fact.object.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from contracts.fact_schema import Fact, FactID, FactStatus, Source, SourceID, SourceType
from sage.pipeline.stage_3.claim_policy import ClaimKey, derive_claim_key

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
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> Fact:
    """Build a Fact for claim-policy tests. fact_id is always a fresh
    UUID4, since these tests care about key derivation, not specific
    IDs. effective_from defaults to "now" since these tests do not
    exercise temporal overlap (that remains pairing.py's concern,
    unchanged by this fix)."""
    now = datetime.now(UTC)
    return Fact(
        fact_id=FactID(str(uuid4())),
        subject=subject,
        predicate=predicate,
        object=obj,
        source=_DUMMY_SOURCE,
        evidence=f"{subject} {predicate} {obj}.",
        extracted_at=now,
        effective_from=effective_from or now,
        effective_to=effective_to,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )


class TestDeriveClaimKeySubjectAnchored:
    """Predicates that do not match either role-shaped template must
    fall back to SUBJECT_ANCHORED, reproducing pre-fix behavior exactly."""

    def test_a_headquarters_predicate_is_subject_anchored(self) -> None:
        fact = _make_fact(
            subject="Company X",
            predicate="is headquartered in",
            obj="Austin, Texas",
        )
        key = derive_claim_key(fact)
        assert key == ClaimKey(
            anchor="Company X",
            claim_type="is headquartered in",
            contested_value="Austin, Texas",
        )

    def test_b_founded_on_predicate_is_subject_anchored(self) -> None:
        fact = _make_fact(
            subject="Company X",
            predicate="was founded on",
            obj="2018-03-12",
        )
        key = derive_claim_key(fact)
        assert key == ClaimKey(
            anchor="Company X",
            claim_type="was founded on",
            contested_value="2018-03-12",
        )

    def test_c_unrecognized_predicate_shape_falls_back_to_subject_anchored(
        self,
    ) -> None:
        """Safety-default test: a predicate that doesn't match either
        known object-anchored shape must never be silently treated as
        OBJECT_ANCHORED, since that could fabricate contradictions
        between facts that were never actually competing claims."""
        fact = _make_fact(
            subject="Company X",
            predicate="acquired",
            obj="Company Y",
        )
        key = derive_claim_key(fact)
        assert key == ClaimKey(
            anchor="Company X",
            claim_type="acquired",
            contested_value="Company Y",
        )


class TestDeriveClaimKeyObjectAnchored:
    """The two role-shaped predicate templates Stage 1 can produce
    ("is the {role} of", "was appointed {role} of") must be recognized
    by shape, with the company as anchor and person as contested value."""

    def test_d_is_the_role_of_shape_is_object_anchored(self) -> None:
        fact = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
        )
        key = derive_claim_key(fact)
        assert key == ClaimKey(
            anchor="Company X",
            claim_type="chief executive officer",
            contested_value="Alice",
        )

    def test_e_was_appointed_role_of_shape_is_object_anchored(self) -> None:
        fact = _make_fact(
            subject="Bob",
            predicate="was appointed Chief Financial Officer of",
            obj="Company X",
        )
        key = derive_claim_key(fact)
        assert key == ClaimKey(
            anchor="Company X",
            claim_type="chief financial officer",
            contested_value="Bob",
        )

    def test_f_role_text_normalized_for_case_and_whitespace(self) -> None:
        """Trivial formatting differences in role text must not
        fracture the claim key -- both facts should produce the same
        claim_type despite differing case."""
        fact_a = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
        )
        fact_b = _make_fact(
            subject="Bob",
            predicate="is the chief executive officer of",
            obj="Company X",
        )
        key_a = derive_claim_key(fact_a)
        key_b = derive_claim_key(fact_b)
        assert key_a.claim_type == key_b.claim_type == "chief executive officer"
        assert key_a.anchor == key_b.anchor == "Company X"

    def test_g_role_synonyms_are_not_resolved_to_the_same_claim_type(
        self,
    ) -> None:
        """Named, accepted limitation: 'CEO' and 'Chief Executive
        Officer' are different strings and therefore different claim
        types under this policy. This must be asserted as current,
        intended behavior -- not silently treated as a bug to fix
        later. Entity/term synonym resolution is explicitly out of
        scope for this fix."""
        fact_a = _make_fact(
            subject="Alice",
            predicate="is the CEO of",
            obj="Company X",
        )
        fact_b = _make_fact(
            subject="Bob",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
        )
        key_a = derive_claim_key(fact_a)
        key_b = derive_claim_key(fact_b)
        assert key_a.claim_type != key_b.claim_type

    def test_h_different_companies_produce_different_anchors(self) -> None:
        """Same role, different companies -- must not share a claim
        key, since they are not competing for the same slot."""
        fact_a = _make_fact(
            subject="Alice",
            predicate="is the Chief Executive Officer of",
            obj="Company X",
        )
        fact_b = _make_fact(
            subject="Bob",
            predicate="is the Chief Executive Officer of",
            obj="Company Y",
        )
        key_a = derive_claim_key(fact_a)
        key_b = derive_claim_key(fact_b)
        assert key_a.anchor != key_b.anchor
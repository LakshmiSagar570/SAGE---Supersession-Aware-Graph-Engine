# tests/unit/test_source_span_required.py
"""Phase 4C Step 4b: source_span joins the required-field check.

PHASE4B_PRODUCTION_CONTRACT.md section 5, check 1: "subject, predicate,
object, and source_span must all be non-empty strings after stripping
whitespace." Before this fix, source_span was checked for CONTAINMENT
("source_span in raw_text") but never for non-emptiness. An empty string
is trivially contained in any string, so a candidate with an empty or
whitespace-only source_span passed both checks and could become a Fact
with zero real grounding in the document -- exactly the gap Sagar
identified: source_span verification is supposed to be part of the
deterministic validation boundary, and an unenforced part of that
boundary is a validation defect, not an experiment finding.

This is a correction to the validation contract as already specified in
4B, not a new rule -- so these tests check that the fix brings behavior
into line with the written contract, not that new behavior was invented.
"""

from __future__ import annotations

import pytest

from contracts.fact_schema import Source, SourceID, SourceType
from experiments.semantic_extraction.candidate import (
    CandidateResult,
    ExtractionCandidate,
    ExtractionOrigin,
    RejectionReason,
    validate_and_build_fact,
)

_SOURCE = Source(
    source_id=SourceID("test-source"),
    name="test-source",
    source_type=SourceType.DOCUMENT,
    locator="test-source",
)

_REAL_RAW_TEXT = "Mr. Thompson is the chief executive officer of Virtual Instruments."


def _validate(
    span: str,
    *,
    subject: str = "Someone Else",
    predicate: str = "is the chief executive officer of",
    obj: str = "Some Other Co",
    raw_text: str = _REAL_RAW_TEXT,
) -> CandidateResult:
    candidate = ExtractionCandidate(
        subject=subject,
        predicate=predicate,
        object=obj,
        source_span=span,
        origin=ExtractionOrigin.SEMANTIC,
    )
    return validate_and_build_fact(candidate, raw_text, _SOURCE)


class TestEmptySourceSpanIsNowRejected:
    def test_empty_string_span_rejected_as_empty_required_field(self) -> None:
        """The exact gap: before the fix, this was ACCEPTED with
        evidence=''. It must now be rejected, and rejected for the right
        reason -- EMPTY_REQUIRED_FIELD, not UNVERIFIABLE_SOURCE_SPAN,
        since 4B section 5 lists this as check 1, before the containment
        check at check 2."""
        result = _validate("")

        assert result.fact is None
        assert result.rejection_reason is RejectionReason.EMPTY_REQUIRED_FIELD

    @pytest.mark.parametrize("span", [" ", "  ", "\t", "\n", "\t\n  \t"])
    def test_whitespace_only_span_rejected(self, span: str) -> None:
        """Whitespace-only is also empty 'after stripping whitespace'
        (4B section 5's exact wording) -- not just the literal empty
        string."""
        result = _validate(span)

        assert result.fact is None
        assert result.rejection_reason is RejectionReason.EMPTY_REQUIRED_FIELD

    def test_a_claim_unrelated_to_the_document_no_longer_slips_through(self) -> None:
        """Concrete reproduction of the real risk: a candidate whose
        subject/predicate/object describe something the document never
        says, submitted with an empty span, must not become a Fact."""
        result = _validate(
            "",
            subject="Unrelated Person",
            predicate="was appointed Chief Financial Officer of",
            obj="Unrelated Company",
            raw_text=_REAL_RAW_TEXT,
        )

        assert result.fact is None


class TestCheckOrderingWithSourceSpan:
    """4B section 5: required-field check (1) comes before the span
    containment check (2). An empty span must fail at check 1, not
    check 2 -- the rejection reason is how a caller tells the two
    checks apart, so which one fires is observable behavior, not an
    implementation detail."""

    def test_empty_span_fails_required_field_not_containment(self) -> None:
        result = _validate("")

        assert result.rejection_reason is RejectionReason.EMPTY_REQUIRED_FIELD

    def test_nonempty_but_absent_span_still_fails_containment(self) -> None:
        """Distinguishes the two checks: a NON-empty span that just
        isn't in the document must still be caught, by check 2, and
        this fix must not have disturbed that."""
        result = _validate("text that is not in the document at all")

        assert result.fact is None
        assert result.rejection_reason is RejectionReason.UNVERIFIABLE_SOURCE_SPAN


class TestRealSpanStillAccepted:
    """The fix must not reject legitimate candidates."""

    def test_real_verbatim_span_from_the_document_is_accepted(self) -> None:
        result = _validate(
            _REAL_RAW_TEXT,
            subject="Mr. Thompson",
            predicate="is the chief executive officer of",
            obj="Virtual Instruments",
        )

        assert result.rejection_reason is None
        assert result.fact is not None
        assert result.fact.evidence == _REAL_RAW_TEXT

    def test_real_short_span_within_a_longer_document_is_accepted(self) -> None:
        raw_text = "Some preamble. " + _REAL_RAW_TEXT + " Some trailing text."
        result = _validate(
            _REAL_RAW_TEXT,
            subject="Mr. Thompson",
            predicate="is the chief executive officer of",
            obj="Virtual Instruments",
            raw_text=raw_text,
        )

        assert result.fact is not None


class TestRuleOriginCandidatesUnaffected:
    """RULE candidates always carry a real, non-empty source_span (the
    regex match itself -- Step 2), so this fix should never fire for
    them in practice. Confirmed here rather than assumed."""

    def test_rule_origin_candidate_with_real_span_still_accepted(self) -> None:
        candidate = ExtractionCandidate(
            subject="Mr. Thompson",
            predicate="is the chief executive officer of",
            object="Virtual Instruments",
            source_span=_REAL_RAW_TEXT,
            origin=ExtractionOrigin.RULE,
        )
        result = validate_and_build_fact(candidate, _REAL_RAW_TEXT, _SOURCE)

        assert result.fact is not None
# tests/unit/test_candidate_validation.py
"""Phase 4C Step 4 tests: the two new deterministic rejection rules.

PHASE4B_PRODUCTION_CONTRACT.md section 5 specifies four checks, in order,
first failure wins:

    1. required fields non-empty      -> EMPTY_REQUIRED_FIELD      (Phase 2)
    2. source_span found in raw_text  -> UNVERIFIABLE_SOURCE_SPAN  (Phase 2)
    3. subject != object              -> SUBJECT_EQUALS_OBJECT     (NEW)
    4. predicate is not a bare copula -> BARE_COPULA_PREDICATE     (NEW)

Real examples are used verbatim from SEMANTIC_EXTRACTION_RESULTS.md (the
triples), and the real EDGAR fixtures supply the source text. For most
cases the span is the whole stripped fixture text: that is a genuine
substring of the real document, so check 2 passes and the test isolates
checks 3 and 4. It says nothing about whether the span "supports" the
claim -- span verification proves provenance only (4B section 5).

The most important test here is `test_phase2_accepted_facts_partition`:
it runs ALL 17 facts Phase 2 accepted through the new validation and
asserts exactly which are newly rejected and which still pass. That is
the plan's Step 4 rollback boundary made executable -- a rule broader
than the failure it was written for would show up as an unexpected
rejection there.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from contracts.fact_schema import Source, SourceID, SourceType
from experiments.semantic_extraction import candidate as candidate_module
from experiments.semantic_extraction.candidate import (
    CandidateResult,
    ExtractionCandidate,
    ExtractionOrigin,
    RejectionReason,
    validate_and_build_fact,
)

_EDGAR_DIR = Path(__file__).parent.parent.parent / "fixtures" / "edgar"

_SOURCE = Source(
    source_id=SourceID("test-source"),
    name="test-source",
    source_type=SourceType.DOCUMENT,
    locator="test-source",
)

_TALENT = "apple_10k_2024_talent_risk.txt"
_EIGHTX8 = "8x8_8k_cfo_appointment.txt"
_MSFT_CLEAN = "msft_def14a_thompson_ceo.txt"
_MSFT_COMPOUND = "msft_def14a_thompson_ceo_verbatim_compound.txt"
_APPLE_PROPS = "apple_10k_2024_properties.txt"
_TENET = "tenet_10k_incorporation.txt"
_ICT = "ict_8k_cfo_appointment.txt"


def _real_text(name: str) -> str:
    return (_EDGAR_DIR / name).read_text()


def _validate(
    subject: str,
    predicate: str,
    obj: str,
    *,
    raw_text: str,
    span: str | None = None,
    origin: ExtractionOrigin = ExtractionOrigin.SEMANTIC,
) -> CandidateResult:
    candidate = ExtractionCandidate(
        subject=subject,
        predicate=predicate,
        object=obj,
        effective_from_text=None,
        llm_confidence=None,
        source_span=raw_text.strip() if span is None else span,
        origin=origin,
    )
    return validate_and_build_fact(candidate, raw_text, _SOURCE)


def _assert_rejected(result: CandidateResult, reason: RejectionReason) -> None:
    assert result.rejection_reason is reason
    assert result.fact is None


def _assert_accepted(result: CandidateResult) -> None:
    assert result.rejection_reason is None
    assert result.fact is not None


class TestRejectionReasonEnum:
    def test_new_reasons_exist_with_contract_names(self) -> None:
        assert RejectionReason.SUBJECT_EQUALS_OBJECT.value == "SUBJECT_EQUALS_OBJECT"
        assert RejectionReason.BARE_COPULA_PREDICATE.value == "BARE_COPULA_PREDICATE"

    def test_phase2_reasons_unchanged(self) -> None:
        assert RejectionReason.UNVERIFIABLE_SOURCE_SPAN.value == "UNVERIFIABLE_SOURCE_SPAN"
        assert RejectionReason.EMPTY_REQUIRED_FIELD.value == "EMPTY_REQUIRED_FIELD"

    def test_exactly_four_reasons(self) -> None:
        assert {r.value for r in RejectionReason} == {
            "EMPTY_REQUIRED_FIELD",
            "UNVERIFIABLE_SOURCE_SPAN",
            "SUBJECT_EQUALS_OBJECT",
            "BARE_COPULA_PREDICATE",
        }


class TestSubjectEqualsObject:
    def test_real_david_stoll_self_reference_rejected(self) -> None:
        """SEMANTIC_EXTRACTION_RESULTS.md 3.6, triple verbatim. This passed
        span verification in Phase 2 and became an accepted 'fact'."""
        raw = _real_text(_EIGHTX8)
        assert "replacing David Stoll" in raw, (
            "8x8 fixture no longer contains the phrase the Phase 2 result was based on"
        )

        result = _validate(
            "David Stoll", "replacing", "David Stoll", raw_text=raw, span="replacing David Stoll"
        )

        _assert_rejected(result, RejectionReason.SUBJECT_EQUALS_OBJECT)

    def test_rejected_result_carries_the_original_candidate(self) -> None:
        raw = "David Stoll replacing David Stoll."
        candidate = ExtractionCandidate(
            subject="David Stoll",
            predicate="replacing",
            object="David Stoll",
            source_span=raw,
            origin=ExtractionOrigin.SEMANTIC,
        )
        result = validate_and_build_fact(candidate, raw, _SOURCE)

        assert result.candidate is candidate

    @pytest.mark.parametrize(
        "subject,obj",
        [
            ("David Stoll ", "David Stoll"),
            ("David Stoll", "  David Stoll"),
            ("\tDavid Stoll\n", " David Stoll "),
        ],
    )
    def test_equality_is_checked_after_strip(self, subject: str, obj: str) -> None:
        raw = "some real text about David Stoll"
        _assert_rejected(
            _validate(subject, "replacing", obj, raw_text=raw),
            RejectionReason.SUBJECT_EQUALS_OBJECT,
        )

    def test_case_difference_is_not_rejected(self) -> None:
        """Locked behavior (4B section 5): EXACT match after .strip(), no
        case folding. Asserted as current behavior, not treated as a bug."""
        raw = "some real text about David Stoll"
        _assert_accepted(_validate("david stoll", "replacing", "David Stoll", raw_text=raw))

    @pytest.mark.parametrize(
        "subject,obj",
        [
            ("Acme", "Acme Holdings"),  # subject is a prefix of object
            ("Holdings", "Acme Holdings"),  # subject is a suffix of object
            ("Acme Holdings", "Acme"),  # object is contained in subject
            ("Apple", "Apple Park, Cupertino"),
        ],
    )
    def test_containment_is_not_equality(self, subject: str, obj: str) -> None:
        """The rule is exact equality after strip (4B section 5, check 3), NOT
        'one contains the other'. Distinct entities routinely share words:
        'Acme' acquired 'Acme Holdings' is a valid claim. Widening the rule
        to containment would silently reject real facts."""
        raw = "some real text about Acme"
        _assert_accepted(_validate(subject, "acquired", obj, raw_text=raw))

    def test_distinct_subject_and_object_pass(self) -> None:
        raw = _real_text(_MSFT_CLEAN)
        _assert_accepted(
            _validate(
                "Mr. Thompson",
                "is the chief executive officer of",
                "Virtual Instruments",
                raw_text=raw,
            )
        )


class TestBareCopulaPredicate:
    def test_real_talent_risk_fragment_rejected(self) -> None:
        """SEMANTIC_EXTRACTION_RESULTS.md 3.3, triple verbatim."""
        raw = _real_text(_TALENT)

        result = _validate("its Chief Executive Officer", "is", "a key personnel", raw_text=raw)

        _assert_rejected(result, RejectionReason.BARE_COPULA_PREDICATE)

    @pytest.mark.parametrize(
        "predicate",
        ["is", "are", "was", "were", " is ", "IS", "Are", "\tWas\n", "WERE"],
    )
    def test_bare_copula_rejected_regardless_of_case_and_whitespace(
        self, predicate: str
    ) -> None:
        raw = "some real text mentioning a key personnel"
        _assert_rejected(
            _validate("its executive team", predicate, "a key personnel", raw_text=raw),
            RejectionReason.BARE_COPULA_PREDICATE,
        )

    @pytest.mark.parametrize(
        "predicate",
        [
            "is headquartered in",
            "is the chief executive officer of",
            "was appointed Chief Financial Officer of",
            "was incorporated in",
            "are located in",  # real predicate from 3.3 -- NOT bare, so not caught
        ],
    )
    def test_predicates_that_merely_contain_a_copula_are_not_bare(self, predicate: str) -> None:
        raw = "some real text"
        _assert_accepted(_validate("Acme Corp", predicate, "Denver, Colorado", raw_text=raw))

    @pytest.mark.parametrize(
        "predicate",
        [
            "files",  # real bare one-word predicate, SEMANTIC_EXTRACTION_RESULTS.md 3.4
            "replacing",  # real bare one-word predicate, 3.6 (David Stoll case)
            "has",  # single-word, but not in the locked set
        ],
    )
    def test_single_word_predicates_outside_the_locked_set_pass(self, predicate: str) -> None:
        """The rule is 'is one of exactly four words', not 'is a single word'
        or 'is a common verb'. Widening it is a deliberate Phase 4B change."""
        raw = "some real text"
        _assert_accepted(_validate("Acme Corp", predicate, "Beta Corp", raw_text=raw))

    def test_locked_copula_set_is_exactly_four_words(self) -> None:
        """Phase 4B section 5, check 4: 'a small fixed set: is, are, was, were'."""
        assert candidate_module._BARE_COPULA_PREDICATES == frozenset(
            {"is", "are", "was", "were"}
        )


# The six real facts Phase 2 accepted from the talent-risk control document
# (SEMANTIC_EXTRACTION_RESULTS.md 3.3), triples verbatim.
_TALENT_FRAGMENTS: list[tuple[str, str, str]] = [
    ("the Company's team members", "depends on the talents and efforts of", "its future success"),
    ("its Chief Executive Officer", "is", "a key personnel"),
    ("its executive team", "is", "a key personnel"),
    ("its other highly skilled employees", "is", "a key personnel"),
    ("their talents", "is", "in high demand"),
    ("key personnel", "are located in", "Silicon Valley"),
]


class TestKnownLimitOfBareCopulaRule:
    """Characterization, not aspiration. Phase 4A locked the bare-copula rule
    as a NARROW guard and explicitly left the general fragmentary-claims
    problem open (4A item 3, to be informed by Phase 4D). This pins down
    exactly how much of the one real over-extraction failure it covers, so
    nobody later assumes 'the talent-risk problem is solved'. If the rule is
    ever deliberately widened, this test should be updated on purpose."""

    def test_rule_catches_four_of_six_real_talent_risk_fragments(self) -> None:
        raw = _real_text(_TALENT)
        rejected: list[tuple[str, str, str]] = []
        passed: list[tuple[str, str, str]] = []

        for triple in _TALENT_FRAGMENTS:
            result = _validate(*triple, raw_text=raw)
            if result.rejection_reason is RejectionReason.BARE_COPULA_PREDICATE:
                rejected.append(triple)
            else:
                assert result.fact is not None, f"unexpected rejection: {result}"
                passed.append(triple)

        assert rejected == [t for t in _TALENT_FRAGMENTS if t[1] == "is"]
        assert len(rejected) == 4
        # The two the rule does NOT catch -- still valid Facts today:
        assert passed == [
            ("the Company's team members", "depends on the talents and efforts of",
             "its future success"),
            ("key personnel", "are located in", "Silicon Valley"),
        ]


class TestCheckOrdering:
    """First failing check wins; later checks are not evaluated."""

    def test_empty_field_wins_over_subject_equals_object(self) -> None:
        # subject == object == "" would ALSO trip check 3; check 1 must win.
        _assert_rejected(
            _validate("", "replacing", "", raw_text="some text", span="some text"),
            RejectionReason.EMPTY_REQUIRED_FIELD,
        )

    def test_empty_predicate_wins_over_everything_after_it(self) -> None:
        _assert_rejected(
            _validate("Acme", "   ", "Acme", raw_text="some text", span="some text"),
            RejectionReason.EMPTY_REQUIRED_FIELD,
        )

    def test_unverifiable_span_wins_over_subject_equals_object(self) -> None:
        _assert_rejected(
            _validate(
                "David Stoll",
                "replacing",
                "David Stoll",
                raw_text="the real document text",
                span="text that is not in the document",
            ),
            RejectionReason.UNVERIFIABLE_SOURCE_SPAN,
        )

    def test_unverifiable_span_wins_over_bare_copula(self) -> None:
        _assert_rejected(
            _validate(
                "its executive team",
                "is",
                "a key personnel",
                raw_text="the real document text",
                span="text that is not in the document",
            ),
            RejectionReason.UNVERIFIABLE_SOURCE_SPAN,
        )

    def test_subject_equals_object_wins_over_bare_copula(self) -> None:
        """Fails checks 3 AND 4; check 3 comes first."""
        _assert_rejected(
            _validate("Acme", "is", "Acme", raw_text="Acme is Acme."),
            RejectionReason.SUBJECT_EQUALS_OBJECT,
        )


# (fixture, subject, predicate, object) for ALL 17 facts Phase 2 accepted,
# triples verbatim from SEMANTIC_EXTRACTION_RESULTS.md sections 3.1-3.8.
# (Apple cybersecurity produced MALFORMED_RESPONSE, so contributes none.)
_PHASE2_ACCEPTED: list[tuple[str, str, str, str]] = [
    # 3.1 Apple properties
    (_APPLE_PROPS, "The Company", "is located in", "Cupertino, California"),
    (
        _APPLE_PROPS,
        "The Company",
        "owned or leased facilities and land for",
        "corporate functions, R&D, data centers, retail and other purposes",
    ),
    # 3.3 Apple talent risk
    (_TALENT, *_TALENT_FRAGMENTS[0]),
    (_TALENT, *_TALENT_FRAGMENTS[1]),
    (_TALENT, *_TALENT_FRAGMENTS[2]),
    (_TALENT, *_TALENT_FRAGMENTS[3]),
    (_TALENT, *_TALENT_FRAGMENTS[4]),
    (_TALENT, *_TALENT_FRAGMENTS[5]),
    # 3.4 Tenet
    (_TENET, "Tenet Healthcare Corporation", "was incorporated in", "the State of Nevada"),
    (
        _TENET,
        "Tenet Healthcare Corporation",
        "files",
        "annual, quarterly and current reports, proxy statements and other documents",
    ),
    # 3.5 ICT
    (_ICT, "Ryan LeBon", "was appointed Chief Financial Officer of", "the Company"),
    (_ICT, "Richard Ransom", "continues as President of", "the Company"),
    # 3.6 8x8
    (_EIGHTX8, "James Sullivan", "has been appointed chief financial officer of", "8x8, Inc."),
    (_EIGHTX8, "David Stoll", "replacing", "David Stoll"),
    # 3.7 Microsoft clean clause
    (_MSFT_CLEAN, "Mr. Thompson", "is the chief executive officer of", "Virtual Instruments"),
    # 3.8 Microsoft compound (the case SEMANTIC got right where RULE didn't)
    (_MSFT_COMPOUND, "Mr. Thompson", "is the chief executive officer of", "Virtual Instruments"),
    (
        _MSFT_COMPOUND,
        "Mr. Thompson",
        "has a less-than-10% beneficial interest in",
        "Virtual Instruments",
    ),
]

_EXPECTED_NEWLY_REJECTED: dict[tuple[str, str, str], RejectionReason] = {
    ("David Stoll", "replacing", "David Stoll"): RejectionReason.SUBJECT_EQUALS_OBJECT,
    ("its Chief Executive Officer", "is", "a key personnel"): RejectionReason.BARE_COPULA_PREDICATE,
    ("its executive team", "is", "a key personnel"): RejectionReason.BARE_COPULA_PREDICATE,
    (
        "its other highly skilled employees",
        "is",
        "a key personnel",
    ): RejectionReason.BARE_COPULA_PREDICATE,
    ("their talents", "is", "in high demand"): RejectionReason.BARE_COPULA_PREDICATE,
}


class TestPhase2AcceptedFactsPartition:
    def test_table_has_all_seventeen_phase2_facts(self) -> None:
        assert len(_PHASE2_ACCEPTED) == 17

    @pytest.mark.parametrize(
        "origin", [ExtractionOrigin.SEMANTIC, ExtractionOrigin.RULE], ids=lambda o: o.value
    )
    def test_phase2_accepted_facts_partition(self, origin: ExtractionOrigin) -> None:
        """Step 4 rollback boundary, executable. Exactly five of the 17 facts
        Phase 2 accepted are now rejected -- the David Stoll self-reference and
        the four bare-'is' talent-risk fragments -- each for the RIGHT reason.
        The other twelve, including every genuinely correct recovery (ICT,
        Microsoft compound, 8x8 Sullivan), must remain accepted. A rule broader
        than the failure it targets would show up here as an unexpected
        rejection."""
        newly_rejected: dict[tuple[str, str, str], RejectionReason] = {}
        still_accepted: list[tuple[str, str, str]] = []

        for fixture, subject, predicate, obj in _PHASE2_ACCEPTED:
            raw = _real_text(fixture)
            result = _validate(subject, predicate, obj, raw_text=raw, origin=origin)
            triple = (subject, predicate, obj)
            if result.fact is not None:
                still_accepted.append(triple)
            else:
                assert result.rejection_reason is not None
                newly_rejected[triple] = result.rejection_reason

        assert newly_rejected == _EXPECTED_NEWLY_REJECTED
        assert len(still_accepted) == 12

    def test_the_genuinely_correct_recoveries_survive(self) -> None:
        """The specific real successes Phase 3 called out as the value of
        SEMANTIC extraction must not be collateral damage of the new rules."""
        must_survive = [
            (_ICT, "Ryan LeBon", "was appointed Chief Financial Officer of", "the Company"),
            (_ICT, "Richard Ransom", "continues as President of", "the Company"),
            (
                _EIGHTX8,
                "James Sullivan",
                "has been appointed chief financial officer of",
                "8x8, Inc.",
            ),
            (
                _MSFT_COMPOUND,
                "Mr. Thompson",
                "is the chief executive officer of",
                "Virtual Instruments",
            ),
        ]
        for fixture, subject, predicate, obj in must_survive:
            _assert_accepted(_validate(subject, predicate, obj, raw_text=_real_text(fixture)))


class TestRulesApplyIdenticallyToBothOrigins:
    """Phase 4A/4B: once a candidate is a Fact nothing downstream may know
    which extractor made it, so validation cannot treat origins differently."""

    @pytest.mark.parametrize(
        "origin", [ExtractionOrigin.RULE, ExtractionOrigin.SEMANTIC], ids=lambda o: o.value
    )
    def test_subject_equals_object_rejected_for_both(self, origin: ExtractionOrigin) -> None:
        _assert_rejected(
            _validate("Acme", "acquired", "Acme", raw_text="Acme acquired Acme.", origin=origin),
            RejectionReason.SUBJECT_EQUALS_OBJECT,
        )

    @pytest.mark.parametrize(
        "origin", [ExtractionOrigin.RULE, ExtractionOrigin.SEMANTIC], ids=lambda o: o.value
    )
    def test_bare_copula_rejected_for_both(self, origin: ExtractionOrigin) -> None:
        _assert_rejected(
            _validate("Acme", "is", "large", raw_text="Acme is large.", origin=origin),
            RejectionReason.BARE_COPULA_PREDICATE,
        )

    @pytest.mark.parametrize(
        "origin", [ExtractionOrigin.RULE, ExtractionOrigin.SEMANTIC], ids=lambda o: o.value
    )
    def test_valid_candidate_accepted_for_both(self, origin: ExtractionOrigin) -> None:
        raw = _real_text(_MSFT_CLEAN)
        result = _validate(
            "Mr. Thompson",
            "is the chief executive officer of",
            "Virtual Instruments",
            raw_text=raw,
            origin=origin,
        )
        _assert_accepted(result)
        assert result.fact is not None
        assert result.fact.subject == "Mr. Thompson"
        assert result.fact.object == "Virtual Instruments"

    def test_validation_function_never_reads_origin(self) -> None:
        """Structural guard for 'no origin-specific branching anywhere in the
        validation function'. Uses the AST so a docstring that merely mentions
        the word cannot cause a false failure."""
        source = textwrap.dedent(inspect.getsource(validate_and_build_fact))
        tree = ast.parse(source)

        origin_references = [
            node
            for node in ast.walk(tree)
            if (isinstance(node, ast.Attribute) and node.attr == "origin")
            or (isinstance(node, ast.Name) and node.id == "ExtractionOrigin")
        ]

        assert origin_references == []

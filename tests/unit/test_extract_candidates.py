# tests/unit/test_extract_candidates.py
"""Phase 4C Step 2 tests: RULE extraction expressed as ExtractionCandidates.

The central requirement (PHASE4C_IMPLEMENTATION_PLAN.md, Step 2): the
candidate path must provably agree with the frozen extract() on the same
input. Every agreement test below runs BOTH code paths inside the same
test and compares them directly -- it does not assert each path against a
hand-typed expectation separately and trust that the two agree.

Also asserted, per Phase 4B section 1.2: PATTERNS is shared with
extract.py (imported, never redefined), and extract_candidates never
calls extract().
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.fact_schema import Fact, Source, SourceID, SourceType
from experiments.semantic_extraction.candidate import (
    ExtractionCandidate,
    ExtractionOrigin,
    validate_and_build_fact,
)
from sage.pipeline.stage_1.extract import extract
from sage.pipeline.stage_1.extract_candidates import extract_as_candidates

# Loaded via importlib rather than `from sage.pipeline.stage_1 import
# extract`, so a package __init__ that re-exports the extract() function
# under the same name cannot shadow the submodule.
_extract_module = importlib.import_module("sage.pipeline.stage_1.extract")
_candidates_module = importlib.import_module("sage.pipeline.stage_1.extract_candidates")

_SOURCE = Source(
    source_id=SourceID("test-source"),
    name="test-source",
    source_type=SourceType.DOCUMENT,
    locator="test-source",
)

_EDGAR_DIR = Path(__file__).parent.parent.parent / "fixtures" / "edgar"


def _triples_from_facts(facts: list[Fact]) -> list[tuple[str, str, str]]:
    return [(f.subject, f.predicate, f.object) for f in facts]


def _triples_from_candidates(
    candidates: list[ExtractionCandidate],
) -> list[tuple[str, str, str]]:
    return [(c.subject, c.predicate, c.object) for c in candidates]


# (sentence, subject, predicate, object, effective_from_text) -- one per
# frozen RULE pattern. Expected values here are typed by hand from the
# frozen patterns' documented behavior (E2E report, Stage 1 patterns).
_PATTERN_CASES = [
    pytest.param(
        "John Smith was appointed Chief Financial Officer of Company A on 2025-03-01.",
        "John Smith",
        "was appointed Chief Financial Officer of",
        "Company A",
        "2025-03-01",
        id="appointed_role_with_date",
    ),
    pytest.param(
        "Acme Corp was founded on 2020-05-17.",
        "Acme Corp",
        "was founded on",
        "2020-05-17",
        "2020-05-17",
        id="founded_on_date",
    ),
    pytest.param(
        "Company A is headquartered in Austin, Texas.",
        "Company A",
        "is headquartered in",
        "Austin, Texas",
        None,
        id="headquartered_in",
    ),
    pytest.param(
        "John Carter is the Chief Executive Officer of Company C.",
        "John Carter",
        "is the Chief Executive Officer of",
        "Company C",
        None,
        id="is_the_role_of",
    ),
]


class TestEachPatternProducesACandidate:
    @pytest.mark.parametrize(
        "sentence,subject,predicate,obj,date_text", _PATTERN_CASES
    )
    def test_candidate_fields(
        self,
        sentence: str,
        subject: str,
        predicate: str,
        obj: str,
        date_text: str | None,
    ) -> None:
        candidates = extract_as_candidates(sentence)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.subject == subject
        assert c.predicate == predicate
        assert c.object == obj
        assert c.effective_from_text == date_text
        assert c.source_span == sentence
        assert c.origin == ExtractionOrigin.RULE
        assert c.llm_confidence is None

    @pytest.mark.parametrize(
        "sentence,subject,predicate,obj,date_text", _PATTERN_CASES
    )
    def test_agrees_with_extract_on_same_input(
        self,
        sentence: str,
        subject: str,
        predicate: str,
        obj: str,
        date_text: str | None,
    ) -> None:
        """Both paths run here, on identical input, compared directly."""
        facts = extract(sentence, _SOURCE)
        candidates = extract_as_candidates(sentence)

        assert len(facts) == 1
        assert len(candidates) == 1
        assert _triples_from_candidates(candidates) == _triples_from_facts(facts)
        # source_span must be exactly the text extract() keeps as evidence.
        assert candidates[0].source_span == facts[0].evidence

    @pytest.mark.parametrize(
        "sentence,subject,predicate,obj,date_text", _PATTERN_CASES
    )
    def test_span_is_verifiable_against_input(
        self,
        sentence: str,
        subject: str,
        predicate: str,
        obj: str,
        date_text: str | None,
    ) -> None:
        candidates = extract_as_candidates(sentence)
        assert candidates[0].source_span in sentence


class TestDatePathAgreesWithExtract:
    """RULE candidates carry RAW date text; the shared wrapper parses it.
    For dated patterns that must land on the exact instant extract() does."""

    @pytest.mark.parametrize(
        "sentence",
        [
            "John Smith was appointed Chief Financial Officer of Company A on 2025-03-01.",
            "Acme Corp was founded on 2020-05-17.",
        ],
    )
    def test_dated_pattern_effective_from_matches_extract(self, sentence: str) -> None:
        fact_direct = extract(sentence, _SOURCE)[0]
        candidate = extract_as_candidates(sentence)[0]

        outcome = validate_and_build_fact(candidate, sentence, _SOURCE)

        assert outcome.fact is not None
        assert outcome.fact.effective_from == fact_direct.effective_from
        assert outcome.fact.effective_from.tzinfo is not None
        assert outcome.fact.effective_from.utcoffset() == UTC.utcoffset(None)

    @pytest.mark.parametrize(
        "sentence",
        [
            "Company A is headquartered in Austin, Texas.",
            "John Carter is the Chief Executive Officer of Company C.",
        ],
    )
    def test_undated_pattern_falls_back_to_extracted_at_on_both_paths(
        self, sentence: str
    ) -> None:
        """No explicit date -> effective_from == extracted_at on BOTH paths.
        (The two extracted_at values differ by microseconds; what must
        agree is the fallback semantics, not the wall-clock instant.)"""
        fact_direct = extract(sentence, _SOURCE)[0]
        candidate = extract_as_candidates(sentence)[0]
        outcome = validate_and_build_fact(candidate, sentence, _SOURCE)

        assert fact_direct.effective_from == fact_direct.extracted_at
        assert outcome.fact is not None
        assert outcome.fact.effective_from == outcome.fact.extracted_at


class TestTraversalMatchesExtract:
    def test_multiline_document_order_and_skips(self) -> None:
        text = (
            "Quarterly Filing Summary\n"
            "\n"
            "   Company A is headquartered in Austin, Texas.   \n"
            "This line is not a claim shape.\n"
            "\n"
            "John Carter is the Chief Executive Officer of Company C.\n"
            "Acme Corp was founded on 2020-05-17.\n"
        )
        facts = extract(text, _SOURCE)
        candidates = extract_as_candidates(text)

        assert len(candidates) == 3
        assert _triples_from_candidates(candidates) == _triples_from_facts(facts)
        assert [c.source_span for c in candidates] == [f.evidence for f in facts]

    def test_indented_line_span_is_the_stripped_sentence(self) -> None:
        text = "    Company A is headquartered in Austin, Texas.    "
        candidates = extract_as_candidates(text)

        assert len(candidates) == 1
        assert candidates[0].source_span == "Company A is headquartered in Austin, Texas."
        assert candidates[0].source_span == extract(text, _SOURCE)[0].evidence

    def test_first_matching_pattern_wins_like_extract(self) -> None:
        """This sentence matches BOTH the 'was appointed ... on DATE'
        pattern and the 'is the ROLE of' pattern. extract.py documents
        that pattern order matters; the candidate path must pick the
        same one, and emit exactly one candidate for the line."""
        sentence = "Ann is the chair of the board and was appointed CFO of Acme on 2020-01-01."
        facts = extract(sentence, _SOURCE)
        candidates = extract_as_candidates(sentence)

        assert len(candidates) == 1
        assert candidates[0].predicate == "was appointed CFO of"
        assert _triples_from_candidates(candidates) == _triples_from_facts(facts)

    def test_sentence_without_terminal_period_is_not_matched(self) -> None:
        text = "Company A is headquartered in Austin, Texas"
        assert extract(text, _SOURCE) == []
        assert extract_as_candidates(text) == []

    @pytest.mark.parametrize("text", ["", "\n", "   \n\t\n  "])
    def test_empty_and_whitespace_only_input(self, text: str) -> None:
        assert extract(text, _SOURCE) == []
        assert extract_as_candidates(text) == []


class TestFrozenDefectIsReproducedNotFixed:
    """Phase 4C must reproduce RULE's frozen behavior exactly, defects
    included (EDGAR_BASELINE_FINDINGS.md). Fixing the compound-sentence
    corruption here would silently change the 'before' side of the
    RULE-vs-SEMANTIC comparison."""

    def test_clean_clause_extracts_correctly(self) -> None:
        text = "Mr. Thompson is the chief executive officer of Virtual Instruments."
        candidates = extract_as_candidates(text)

        assert len(candidates) == 1
        assert candidates[0].object == "Virtual Instruments"
        assert _triples_from_candidates(candidates) == _triples_from_facts(
            extract(text, _SOURCE)
        )

    def test_compound_sentence_object_is_corrupted_exactly_as_baseline(self) -> None:
        text = (
            "Mr. Thompson is the chief executive officer of and has a "
            "less-than-10% beneficial interest in Virtual Instruments."
        )
        candidates = extract_as_candidates(text)

        assert len(candidates) == 1
        # The frozen defect, deliberately preserved:
        assert candidates[0].object == (
            "and has a less-than-10% beneficial interest in Virtual Instruments"
        )
        assert _triples_from_candidates(candidates) == _triples_from_facts(
            extract(text, _SOURCE)
        )


class TestStructuralGuarantees:
    def test_patterns_are_shared_not_copied(self) -> None:
        """Phase 4B section 1.2: PATTERNS is imported from extract.py, not
        redefined -- so the two paths cannot drift on what a claim is."""
        assert _candidates_module.PATTERNS is _extract_module.PATTERNS

    def test_candidate_module_does_not_call_extract(self) -> None:
        """Phase 4B section 1.2: does its own matching; never wraps extract()
        or reaches into its private parser."""
        assert not hasattr(_candidates_module, "extract")
        assert not hasattr(_candidates_module, "_parse_claim_sentence")

    def test_extract_public_behavior_unchanged_by_visibility_rename(self) -> None:
        """The one permitted edit to extract.py renamed _PATTERNS -> PATTERNS.
        extract() must still return the same Fact shape it always did."""
        facts = extract("Company A is headquartered in Austin, Texas.", _SOURCE)
        assert len(facts) == 1
        assert facts[0].confidence == 1.0
        assert facts[0].metadata == {}
        assert facts[0].effective_to is None
        assert isinstance(facts[0].extracted_at, datetime)


# ---------------------------------------------------------------------
# Real EDGAR fixtures (committed in fixtures/edgar/). These read the
# actual frozen files, so they check real behavior, not typed-in strings.
# ---------------------------------------------------------------------

_EDGAR_ALL = [
    "apple_10k_2024_properties.txt",
    "apple_10k_2024_cybersecurity.txt",
    "apple_10k_2024_talent_risk.txt",
    "tenet_10k_incorporation.txt",
    "ict_8k_cfo_appointment.txt",
    "8x8_8k_cfo_appointment.txt",
    "msft_def14a_thompson_ceo.txt",
    "msft_def14a_thompson_ceo_verbatim_compound.txt",
]

# The six documents the frozen baseline (EDGAR_BASELINE_FINDINGS.md)
# records as clean misses: zero facts extracted.
_EDGAR_KNOWN_MISSES = _EDGAR_ALL[:6]


class TestRealEdgarFixtures:
    @pytest.mark.parametrize("name", _EDGAR_ALL)
    def test_candidates_match_extract_on_every_fixture(self, name: str) -> None:
        raw_text = (_EDGAR_DIR / name).read_text()

        facts = extract(raw_text, _SOURCE)
        candidates = extract_as_candidates(raw_text)

        assert _triples_from_candidates(candidates) == _triples_from_facts(facts)
        assert [c.source_span for c in candidates] == [f.evidence for f in facts]
        assert all(c.source_span in raw_text for c in candidates)

    @pytest.mark.parametrize("name", _EDGAR_KNOWN_MISSES)
    def test_known_baseline_misses_yield_no_candidates(self, name: str) -> None:
        raw_text = (_EDGAR_DIR / name).read_text()

        assert extract(raw_text, _SOURCE) == []
        assert extract_as_candidates(raw_text) == []
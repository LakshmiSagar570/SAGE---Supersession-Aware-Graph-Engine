# tests/unit/test_rule_path_baseline_parity.py
"""Phase 4C Step 5: RULE-via-the-new-path must reproduce the frozen baseline.

PHASE4C_IMPLEMENTATION_PLAN.md, Step 5: run the real EDGAR fixtures through
    extract_as_candidates -> validate_and_build_fact -> Fact
and confirm the resulting Facts are field-identical to what the frozen
extract() produces on the same input -- reproducing
EDGAR_BASELINE_FINDINGS.md's 1 correct / 1 corrupted / 6 missed EXACTLY,
not approximately. "Any divergence ... means the new candidate path is not
yet a faithful reproduction of RULE's real behavior."

Step 2 already proved candidate triples and source_span agree with
extract(). What Step 5 adds, and what these tests cover:
    - the candidates go through Step 4's shared validation and NONE of them
      is rejected (so the new rules did not disturb RULE's behavior);
    - the constructed Facts match extract()'s Facts on every field that is
      not intrinsically per-run (fact_id, extracted_at, effective_from are
      freshly generated -- 4B section 7 -- so they are compared by
      semantics, not by value);
    - the frozen defect survives the whole path. The corrupted compound
      object must come out corrupted: "fixing" it here would silently move
      the 'before' side of the RULE-vs-SEMANTIC comparison.

Two additions beyond Step 5's letter, both cheap and both real-file:
    - the nine synthetic Case A-E fixtures, because Case D is the only
      real-file coverage of a DATED pattern through the candidate path;
    - a structural check that no RULE predicate template can ever be a
      bare copula, so RULE can never trip the Step 4 copula rule.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.fact_schema import Fact, Source, SourceID, SourceType
from experiments.semantic_extraction import candidate as candidate_module
from experiments.semantic_extraction.candidate import (
    RejectionReason,
    validate_and_build_fact,
)
from sage.pipeline.stage_1.extract import PATTERNS, extract
from sage.pipeline.stage_1.extract_candidates import extract_as_candidates

_ROOT = Path(__file__).parent.parent.parent
_EDGAR_DIR = _ROOT / "fixtures" / "edgar"
_E2E_DIR = _ROOT / "fixtures" / "e2e"

_SOURCE = Source(
    source_id=SourceID("test-source"),
    name="test-source",
    source_type=SourceType.DOCUMENT,
    locator="test-source",
)

# The 8 real excerpts of the frozen baseline, in the order of
# EDGAR_BASELINE_FINDINGS.md's sample table.
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
_MSFT_CLEAN = "msft_def14a_thompson_ceo.txt"
_MSFT_COMPOUND = "msft_def14a_thompson_ceo_verbatim_compound.txt"

# What the compound sentence's object SHOULD be, per EDGAR_BASELINE_FINDINGS.md.
_TRUE_OBJECT = "Virtual Instruments"
# What frozen RULE actually extracts for it -- the documented defect.
_CORRUPTED_OBJECT = "and has a less-than-10% beneficial interest in Virtual Instruments"

# Per-run values (4B section 7) -- compared by semantics, not by value.
_PER_RUN_FIELDS = {"fact_id", "extracted_at", "effective_from"}


def _read(directory: Path, name: str) -> str:
    return (directory / name).read_text()


def _via_candidate_path(raw_text: str) -> tuple[list[Fact], list[RejectionReason]]:
    """RULE candidates -> shared validation -> Facts. Returns (facts, rejections)."""
    facts: list[Fact] = []
    rejections: list[RejectionReason] = []
    for candidate in extract_as_candidates(raw_text):
        result = validate_and_build_fact(candidate, raw_text, _SOURCE)
        if result.fact is not None:
            facts.append(result.fact)
        else:
            assert result.rejection_reason is not None
            rejections.append(result.rejection_reason)
    return facts, rejections


def _stable_fields(fact: Fact) -> dict[str, object]:
    """Every Fact field that is not per-run. Includes source, evidence,
    confidence, status, effective_to and metadata -- i.e. the whole contract
    surface except the three freshly generated values."""
    return fact.model_dump(exclude=_PER_RUN_FIELDS)


def _effective_from_is_fallback(fact: Fact) -> bool:
    return fact.effective_from == fact.extracted_at


def _assert_facts_match(direct: list[Fact], via: list[Fact]) -> None:
    assert len(via) == len(direct)
    for d, v in zip(direct, via, strict=True):
        assert _stable_fields(v) == _stable_fields(d)
        # Temporal semantics: both fall back to extracted_at, or both carry
        # the same explicit date. (The two extracted_at values themselves
        # differ by microseconds -- not comparable.)
        assert _effective_from_is_fallback(v) == _effective_from_is_fallback(d)
        if not _effective_from_is_fallback(d):
            assert v.effective_from == d.effective_from
        # Fresh identity on every construction, never shared across paths.
        assert v.fact_id != d.fact_id


class TestEightEdgarFixtures:
    @pytest.mark.parametrize("name", _EDGAR_ALL)
    def test_facts_are_field_identical_to_frozen_extract(self, name: str) -> None:
        raw_text = _read(_EDGAR_DIR, name)

        direct = extract(raw_text, _SOURCE)
        via, _ = _via_candidate_path(raw_text)

        _assert_facts_match(direct, via)

    @pytest.mark.parametrize("name", _EDGAR_ALL)
    def test_no_rule_candidate_is_rejected_by_shared_validation(self, name: str) -> None:
        """RULE candidates pass all four checks on every real fixture: the
        span is the real sentence, and no RULE output here is a self-reference
        or a bare copula. A rejection would mean the new rules disturbed RULE."""
        _, rejections = _via_candidate_path(_read(_EDGAR_DIR, name))

        assert rejections == []

    def test_frozen_baseline_is_1_correct_1_corrupted_6_missed(self) -> None:
        """EDGAR_BASELINE_FINDINGS.md's headline numbers, recomputed from data
        on BOTH paths, and required to agree."""

        def classify(facts: list[Fact]) -> str:
            if not facts:
                return "missed"
            assert len(facts) == 1
            return "correct" if facts[0].object == _TRUE_OBJECT else "corrupted"

        via_counts: Counter[str] = Counter()
        direct_counts: Counter[str] = Counter()
        for name in _EDGAR_ALL:
            raw_text = _read(_EDGAR_DIR, name)
            via_counts[classify(_via_candidate_path(raw_text)[0])] += 1
            direct_counts[classify(extract(raw_text, _SOURCE))] += 1

        assert dict(direct_counts) == {"correct": 1, "corrupted": 1, "missed": 6}
        assert dict(via_counts) == dict(direct_counts)

    def test_clean_clause_is_the_one_correct_extraction(self) -> None:
        facts, _ = _via_candidate_path(_read(_EDGAR_DIR, _MSFT_CLEAN))

        assert len(facts) == 1
        assert facts[0].subject == "Mr. Thompson"
        assert facts[0].predicate == "is the chief executive officer of"
        assert facts[0].object == _TRUE_OBJECT

    def test_compound_sentence_defect_survives_the_whole_path_unfixed(self) -> None:
        """The frozen corrupted extraction must come out CORRUPTED. It passes
        validation as an ordinary Fact -- nothing in the shared rules can tell
        that its object is wrong, which is exactly the point of the baseline."""
        facts, rejections = _via_candidate_path(_read(_EDGAR_DIR, _MSFT_COMPOUND))

        assert rejections == []
        assert len(facts) == 1
        assert facts[0].object == _CORRUPTED_OBJECT
        assert facts[0].object != _TRUE_OBJECT


_E2E_ALL = [
    "case_a_new_fact.txt",
    "case_b_headquarters_update_v1.txt",
    "case_b_headquarters_update_v2.txt",
    "case_c_conflict_source_1.txt",
    "case_c_conflict_source_2.txt",
    "case_d_cfo_v1.txt",
    "case_d_cfo_v2.txt",
    "case_e_winner_supersession_v1.txt",
    "case_e_winner_supersession_v2.txt",
]


class TestSyntheticCaseFixtures:
    """Cases A-E, Stage 1 only. Full Stage 1-6 byte-identity for these is
    Step 12 item 3; this is the cheap early check, and the only real-file
    coverage of a dated pattern through the candidate path."""

    @pytest.mark.parametrize("name", _E2E_ALL)
    def test_facts_are_field_identical_to_frozen_extract(self, name: str) -> None:
        raw_text = _read(_E2E_DIR, name)

        direct = extract(raw_text, _SOURCE)
        via, rejections = _via_candidate_path(raw_text)

        assert rejections == []
        assert len(direct) >= 1
        _assert_facts_match(direct, via)

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("case_d_cfo_v1.txt", datetime(2025, 3, 1, tzinfo=UTC)),
            ("case_d_cfo_v2.txt", datetime(2025, 7, 1, tzinfo=UTC)),
        ],
    )
    def test_case_d_explicit_dates_survive_the_candidate_path(
        self, name: str, expected: datetime
    ) -> None:
        """E2E report Case D: 'dates correctly extracted from text'."""
        facts, _ = _via_candidate_path(_read(_E2E_DIR, name))

        assert len(facts) == 1
        assert facts[0].effective_from == expected
        assert not _effective_from_is_fallback(facts[0])


class TestRuleCanNeverTripTheCopulaRule:
    @pytest.mark.parametrize(
        "index", range(len(PATTERNS)), ids=[t for _, t in PATTERNS]
    )
    def test_predicate_template_is_never_a_bare_copula(self, index: int) -> None:
        """Structural: every RULE predicate carries a role/preposition, so the
        Step 4 copula rule can only ever reject SEMANTIC output in practice."""
        _, template = PATTERNS[index]

        for role in ("Chief Executive Officer", "X"):
            rendered = template.format(role=role).strip().lower()
            assert rendered not in candidate_module._BARE_COPULA_PREDICATES
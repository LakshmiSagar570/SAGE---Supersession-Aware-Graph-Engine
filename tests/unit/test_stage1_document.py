"""
tests/unit/test_stage1_document.py

Unit tests for Stage 1 DOCUMENT ingestion (plain-text .txt only, v0.1).

Run with the deterministic fixture at fixtures/sample_document.txt,
which contains five claims specifically chosen to exercise:
  - a baseline claim with no explicit date
  - a claim with an explicit date
  - two distinct subjects
  - a pair of claims about the same role (Maria Chen / CEO /
    CompanyCorp) at two different times, reserved for future Stage 3
    testing -- Stage 1 must extract both as independent facts and must
    NOT merge, compare, or resolve them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.fact_schema import FactStatus, SourceType
from contracts.stage_io import Stage1Input
from sage.pipeline.stage_1.ingest import (
    IngestionError,
    UnsupportedSourceTypeError,
    ingest,
)
from sage.pipeline.stage_1.stage import run_stage1

FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "sample_document.txt"


@pytest.fixture
def stage1_input() -> Stage1Input:
    return Stage1Input(
        source_type=SourceType.DOCUMENT,
        reference=str(FIXTURE_PATH),
    )


# --- ingest.py ---------------------------------------------------------


def test_ingest_reads_local_file_when_raw_payload_none(stage1_input: Stage1Input) -> None:
    text = ingest(stage1_input)
    assert "CompanyCorp is headquartered in Austin." in text


def test_ingest_uses_raw_payload_when_already_populated() -> None:
    stage_input = Stage1Input(
        source_type=SourceType.DOCUMENT,
        reference="irrelevant-when-payload-present.txt",
        raw_payload="X is headquartered in Y.",
    )
    text = ingest(stage_input)
    assert text == "X is headquartered in Y."


def test_ingest_rejects_non_document_source_types() -> None:
    stage_input = Stage1Input(source_type=SourceType.WEB, reference="https://example.com")
    with pytest.raises(UnsupportedSourceTypeError):
        ingest(stage_input)


def test_ingest_raises_on_missing_file() -> None:
    stage_input = Stage1Input(source_type=SourceType.DOCUMENT, reference="/no/such/file.txt")
    with pytest.raises(IngestionError):
        ingest(stage_input)


# --- extract.py / stage.py ---------------------------------------------


def test_extract_returns_correct_fact_count(stage1_input: Stage1Input) -> None:
    output = run_stage1(stage1_input)
    assert len(output.facts) == 5


def test_extract_maps_subject_predicate_object_correctly(stage1_input: Stage1Input) -> None:
    output = run_stage1(stage1_input)
    austin_fact = next(f for f in output.facts if f.object == "Austin")
    assert austin_fact.subject == "CompanyCorp"
    assert austin_fact.predicate == "is headquartered in"


def test_extract_derives_effective_from_from_explicit_date(stage1_input: Stage1Input) -> None:
    output = run_stage1(stage1_input)
    founded_fact = next(f for f in output.facts if "founded" in f.predicate)
    assert founded_fact.effective_from == datetime(2018, 3, 12, tzinfo=UTC)


def test_extract_effective_from_falls_back_to_extracted_at_when_no_date_in_claim(
    stage1_input: Stage1Input,
) -> None:
    """
    Locked correction from design review: a claim with no explicit date
    gets effective_from = extracted_at, NEVER the document's own
    "Generated:" date. This test specifically guards against the
    document-date fallback that was flagged and removed during review.
    """
    output = run_stage1(stage1_input)
    austin_fact = next(f for f in output.facts if f.object == "Austin")
    assert austin_fact.effective_from == austin_fact.extracted_at
    # The document's Generated: date (2026-08-15) must NOT appear as
    # this fact's effective_from.
    assert austin_fact.effective_from.date() != datetime(2026, 8, 15, tzinfo=UTC).date()


def test_extract_preserves_source_sentence_as_evidence(stage1_input: Stage1Input) -> None:
    output = run_stage1(stage1_input)
    austin_fact = next(f for f in output.facts if f.object == "Austin")
    assert austin_fact.evidence == "CompanyCorp is headquartered in Austin."


def test_extract_sets_status_discovered_and_confidence_1_0(stage1_input: Stage1Input) -> None:
    output = run_stage1(stage1_input)
    for fact in output.facts:
        assert fact.status == FactStatus.DISCOVERED
        assert fact.confidence == 1.0


def test_two_ceo_claims_produce_two_distinct_facts(stage1_input: Stage1Input) -> None:
    """
    Confirms Stage 1 does not merge, compare, or resolve the two CEO
    claims about Maria Chen / CompanyCorp at different times -- that
    is Stage 3's responsibility. Stage 1 must simply extract both as
    independent facts with different effective_from values.
    """
    output = run_stage1(stage1_input)
    ceo_facts = [f for f in output.facts if "Maria Chen" in f.subject]
    assert len(ceo_facts) == 2
    assert ceo_facts[0].fact_id != ceo_facts[1].fact_id
    effective_dates = {f.effective_from for f in ceo_facts}
    assert len(effective_dates) == 2  # different times, not deduplicated


def test_fact_ids_are_unique_across_all_extracted_facts(stage1_input: Stage1Input) -> None:
    """
    Per review note: test fact_id uniqueness and structure, not exact
    UUID values -- the specific UUID generated is an implementation
    accident, not a property worth pinning in a test.
    """
    output = run_stage1(stage1_input)
    fact_ids = [f.fact_id for f in output.facts]
    assert len(fact_ids) == len(set(fact_ids))
    for fact_id in fact_ids:
        assert len(str(fact_id)) == 36  # well-formed UUID4 string length
def test_extract_maps_founded_date_as_object(
    stage1_input: Stage1Input,
) -> None:
    output = run_stage1(stage1_input)

    founded_fact = next(
        f
        for f in output.facts
        if f.subject == "CompanyCorp"
        and f.predicate == "was founded on"
    )

    assert founded_fact.object == "2018-03-12"
    assert founded_fact.effective_from == datetime(2018, 3, 12, tzinfo=UTC)
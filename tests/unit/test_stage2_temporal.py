"""Tests for Stage 2 (Temporal Reasoning).

These tests deliberately do NOT stop at `isinstance(output, Stage2Output)`
— that check would pass even if Stage 2 illegally mutated a locked field,
since Pydantic's contract has no way to detect that on its own. Instead,
every test that touches the mutation boundary builds an input snapshot,
runs it through Stage 2, and compares locked fields one by one, matched
by fact_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from contracts.fact_schema import Fact, FactStatus, SourceType
from contracts.stage_io import Stage1Input, Stage2Input
from sage.pipeline.stage_1.stage import run_stage1
from sage.pipeline.stage_2.stage import run_stage2
from sage.pipeline.stage_2.temporal import enrich_temporally

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
SAMPLE_DOCUMENT = FIXTURES_DIR / "sample_document.txt"

# Fields Stage 2 must preserve exactly, per the locked mutation contract.
_LOCKED_FIELDS = (
    "fact_id",
    "subject",
    "predicate",
    "object",
    "source",
    "evidence",
    "extracted_at",
    "confidence",
    "status",
)


def _stage1_facts() -> list[Fact]:
    """Run the real Stage 1 pipeline against the shared fixture, giving
    Stage 2 tests genuine upstream output rather than hand-built facts
    that might not reflect what Stage 1 actually produces."""
    stage_input = Stage1Input(
        source_type=SourceType.DOCUMENT,
        reference=str(SAMPLE_DOCUMENT),
    )
    return run_stage1(stage_input).facts


def _by_fact_id(facts: list[Fact]) -> dict[object, Fact]:
    return {f.fact_id: f for f in facts}


def _assert_locked_fields_identical(before: Fact, after: Fact) -> None:
    """Assert every field in _LOCKED_FIELDS is unchanged between the two
    Fact snapshots. This is the concrete enforcement the spec calls for
    in place of relying on the Pydantic contract alone."""
    for field_name in _LOCKED_FIELDS:
        before_value = getattr(before, field_name)
        after_value = getattr(after, field_name)
        assert before_value == after_value, (
            f"Locked field {field_name!r} changed: "
            f"{before_value!r} -> {after_value!r} (fact_id={before.fact_id})"
        )


class TestEnrichTemporally:
    def test_input_output_cardinality(self) -> None:
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)
        assert len(output_facts) == len(input_facts) == 5

    def test_fact_ids_preserved(self) -> None:
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)

        input_ids = {f.fact_id for f in input_facts}
        output_ids = {f.fact_id for f in output_facts}
        assert input_ids == output_ids

    def test_immutable_fields_preserved(self) -> None:
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)

        output_by_id = _by_fact_id(output_facts)
        for before in input_facts:
            after = output_by_id[before.fact_id]
            _assert_locked_fields_identical(before, after)

    def test_explicit_temporal_dates_preserved(self) -> None:
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)
        output_by_evidence = {f.evidence: f for f in output_facts}

        founded_fact = output_by_evidence["CompanyCorp was founded on 2018-03-12."]
        assert founded_fact.effective_from == datetime(2018, 3, 12, tzinfo=UTC)

        appointed_fact = output_by_evidence[
            "Maria Chen was appointed Chief Executive Officer of "
            "CompanyCorp on 2024-01-10."
        ]
        assert appointed_fact.effective_from == datetime(2024, 1, 10, tzinfo=UTC)

    def test_no_fabricated_temporal_dates(self) -> None:
        """Undated facts must not suddenly acquire the document's
        Generated: date (2026-08-15) as their effective_from."""
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)

        generated_date = datetime(2026, 8, 15, tzinfo=UTC)
        for fact in output_facts:
            assert fact.effective_from != generated_date

    def test_undated_facts_effective_from_unchanged_by_stage2(self) -> None:
        """For facts with no explicit date, Stage 1's extracted_at
        fallback must survive Stage 2 untouched — v0.1 has no evidence
        basis to do anything else, per spec section 4/8."""
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)
        output_by_id = _by_fact_id(output_facts)

        for before in input_facts:
            if before.evidence in (
                "CompanyCorp is headquartered in Austin.",
                "Maria Chen is the Chief Executive Officer of CompanyCorp.",
                "Innovex Ltd is headquartered in Boston.",
            ):
                after = output_by_id[before.fact_id]
                assert after.effective_from == before.effective_from

    def test_no_fact_merging(self) -> None:
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)

        ceo_related = [
            f
            for f in output_facts
            if "Maria Chen" in f.subject
            and "Chief Executive Officer" in f.predicate
        ]
        assert len(ceo_related) == 2
        assert ceo_related[0].fact_id != ceo_related[1].fact_id

    def test_no_status_mutation(self) -> None:
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)
        assert all(f.status is FactStatus.DISCOVERED for f in output_facts)

    def test_no_confidence_mutation(self) -> None:
        input_facts = _stage1_facts()
        output_facts = enrich_temporally(input_facts)
        assert all(f.confidence == 1.0 for f in output_facts)

    def test_empty_input(self) -> None:
        assert enrich_temporally([]) == []


class TestRunStage2:
    def test_produces_valid_stage2_output_from_stage1_facts(self) -> None:
        input_facts = _stage1_facts()
        stage2_input = Stage2Input(facts=input_facts)

        output = run_stage2(stage2_input)

        assert len(output.facts) == len(input_facts)
        output_by_id = _by_fact_id(output.facts)
        for before in input_facts:
            after = output_by_id[before.fact_id]
            _assert_locked_fields_identical(before, after)

    def test_empty_input(self) -> None:
        output = run_stage2(Stage2Input(facts=[]))
        assert output.facts == []
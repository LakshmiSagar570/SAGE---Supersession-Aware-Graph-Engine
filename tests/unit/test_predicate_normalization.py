"""Phase 4C Step 7 -- predicate normalization (Phase 4B section 3).

Three required verifications from the plan:
  (a) the one real mapping applies (real 8x8 CFO phrasing);
  (b) "is located in" / "was incorporated in" pass through UNNORMALIZED --
      this fails if either removed mapping is ever reintroduced;
  (c) a normalized SEMANTIC CFO candidate gets the same Stage 3 claim key
      shape as an equivalent RULE candidate (verified concretely through
      claim_policy.derive_claim_key, not assumed from reading it).
Plus structural checks that normalization lives only at SEMANTIC
construction time and never inside the shared validator.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from typing import Any

import pytest

from contracts.fact_schema import Fact, Source, SourceID, SourceType
from experiments.semantic_extraction import candidate as candidate_module
from experiments.semantic_extraction import semantic_extract as semantic_module
from experiments.semantic_extraction.candidate import (
    _PREDICATE_NORMALIZATION_MAP,
    ExtractionCandidate,
    ExtractionOrigin,
    normalize_semantic_predicate,
    validate_and_build_fact,
)
from experiments.semantic_extraction.semantic_extract import (
    SemanticStatus,
    extract_semantic,
)
from sage.pipeline.stage_1 import extract_candidates as rule_module
from sage.pipeline.stage_1.extract_candidates import extract_as_candidates
from sage.pipeline.stage_3.claim_policy import derive_claim_key

SEMANTIC_CFO = "has been appointed chief financial officer of"
CANONICAL_CFO = "was appointed Chief Financial Officer of"


_SOURCE = Source(
    source_id=SourceID("test-source"),
    name="test-source",
    source_type=SourceType.DOCUMENT,
    locator="test-source",
)


def _source() -> Source:
    return _SOURCE


def _llm_returning(items: list[dict[str, Any]]) -> Any:
    return lambda _text: json.dumps(items)


def _semantic_candidates(items: list[dict[str, Any]]) -> list[ExtractionCandidate]:
    result = extract_semantic("ignored", _llm_returning(items), max_retries=0)
    assert result.status is SemanticStatus.OK
    return result.candidates


# ---------------------------------------------------------------- (a)


def test_real_cfo_mapping_applies() -> None:
    assert normalize_semantic_predicate(SEMANTIC_CFO) == CANONICAL_CFO


def test_table_has_exactly_the_one_locked_entry() -> None:
    assert _PREDICATE_NORMALIZATION_MAP == {SEMANTIC_CFO: CANONICAL_CFO}


# ---------------------------------------------------------------- (b)


@pytest.mark.parametrize(
    "predicate",
    [
        "is located in",  # removed mapping #1 -> "is headquartered in"
        "was incorporated in",  # removed mapping #2 -> "was founded on"
        "is headquartered in",  # RULE canonical forms stay as they are
        "was founded on",
        CANONICAL_CFO,  # already canonical: unchanged
        "replacing",
        "",
    ],
)
def test_other_predicates_pass_through_unchanged(predicate: str) -> None:
    assert normalize_semantic_predicate(predicate) == predicate


def test_matching_is_exact_not_case_folded() -> None:
    # Characterization of the locked behavior: exact string equality only.
    variant = "Has Been Appointed Chief Financial Officer Of"
    assert normalize_semantic_predicate(variant) == variant
    padded = f" {SEMANTIC_CFO} "
    assert normalize_semantic_predicate(padded) == padded


def test_removed_mappings_pass_through_end_to_end() -> None:
    cands = _semantic_candidates(
        [
            {
                "subject": "Apple",
                "predicate": "is located in",
                "object": "Cupertino, California",
                "source_span": "x",
            },
            {
                "subject": "Tenet",
                "predicate": "was incorporated in",
                "object": "the State of Nevada",
                "source_span": "y",
            },
        ]
    )
    assert [c.predicate for c in cands] == ["is located in", "was incorporated in"]


# ------------------------------------------- construction-time wiring


def test_semantic_construction_normalizes_cfo_predicate() -> None:
    (cand,) = _semantic_candidates(
        [
            {
                "subject": "James Sullivan",
                "predicate": SEMANTIC_CFO,
                "object": "8x8, Inc.",
                "source_span": "James Sullivan has been appointed",
            }
        ]
    )
    assert cand.predicate == CANONICAL_CFO
    assert cand.origin is ExtractionOrigin.SEMANTIC


def test_model_supplied_origin_still_overridden_with_normalization() -> None:
    (cand,) = _semantic_candidates(
        [
            {
                "subject": "A",
                "predicate": SEMANTIC_CFO,
                "object": "B",
                "source_span": "A",
                "origin": "RULE",
            }
        ]
    )
    assert cand.origin is ExtractionOrigin.SEMANTIC
    assert cand.predicate == CANONICAL_CFO


@pytest.mark.parametrize(
    "bad_item",
    [
        {"subject": "A", "predicate": None, "object": "B", "source_span": "A"},
        {"subject": "A", "object": "B", "source_span": "A"},  # no predicate key
        {"subject": "A", "predicate": 7, "object": "B", "source_span": "A"},
    ],
)
def test_non_string_or_missing_predicate_is_rejected_not_crashed(
    bad_item: dict[str, Any],
) -> None:
    good = {
        "subject": "C",
        "predicate": SEMANTIC_CFO,
        "object": "D",
        "source_span": "C",
    }
    result = extract_semantic(
        "ignored", _llm_returning([bad_item, good]), max_retries=0
    )
    assert result.status is SemanticStatus.OK
    assert [c.subject for c in result.candidates] == ["C"]
    assert result.error_detail is not None and "item 0" in result.error_detail


# ------------------------------- origin-agnostic validator (structural)


def _function_source(fn: Any) -> str:
    return textwrap.dedent(inspect.getsource(fn))


def test_validator_does_not_reference_normalization() -> None:
    tree = ast.parse(_function_source(validate_and_build_fact))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "normalize_semantic_predicate" not in names
    assert "_PREDICATE_NORMALIZATION_MAP" not in names


@pytest.mark.parametrize("origin", list(ExtractionOrigin))
def test_validator_does_not_normalize_for_any_origin(origin: ExtractionOrigin) -> None:
    raw = "James Sullivan has been appointed chief financial officer of 8x8."
    cand = ExtractionCandidate(
        subject="James Sullivan",
        predicate=SEMANTIC_CFO,
        object="8x8",
        source_span=raw,
        origin=origin,
    )
    result = validate_and_build_fact(cand, raw, _source())
    assert result.fact is not None
    assert result.fact.predicate == SEMANTIC_CFO  # untouched by the validator


def test_normalization_is_wired_into_semantic_path_only() -> None:
    assert "normalize_semantic_predicate" in inspect.getsource(
        semantic_module._parse_response
    )
    assert "normalize_semantic_predicate" not in inspect.getsource(rule_module)
    assert "_PREDICATE_NORMALIZATION_MAP" not in inspect.getsource(rule_module)
    # and the table itself lives in candidate.py, not duplicated elsewhere
    assert "_PREDICATE_NORMALIZATION_MAP" not in inspect.getsource(semantic_module)
    assert hasattr(candidate_module, "_PREDICATE_NORMALIZATION_MAP")


# ---------------------------------------------------------------- (c)

_RULE_TEXT = (
    "Ryan LeBon was appointed Chief Financial Officer of Company A on 2025-03-01."
)
_SEM_TEXT = "James Sullivan has been appointed chief financial officer of Company A."


def _rule_fact() -> Fact:
    (cand,) = extract_as_candidates(_RULE_TEXT)
    assert cand.origin is ExtractionOrigin.RULE
    result = validate_and_build_fact(cand, _RULE_TEXT, _source())
    assert result.fact is not None
    return result.fact


def _semantic_fact(predicate_in_model_output: str) -> Fact:
    (cand,) = _semantic_candidates(
        [
            {
                "subject": "James Sullivan",
                "predicate": predicate_in_model_output,
                "object": "Company A",
                "source_span": _SEM_TEXT,
            }
        ]
    )
    result = validate_and_build_fact(cand, _SEM_TEXT, _source())
    assert result.fact is not None
    return result.fact


def test_stage3_claim_key_parity_normalized_semantic_vs_rule() -> None:
    rule_key = derive_claim_key(_rule_fact())
    sem_key = derive_claim_key(_semantic_fact(SEMANTIC_CFO))

    # Non-vacuous: assert the concrete values, not just rule == semantic.
    assert rule_key.anchor == "Company A"
    assert rule_key.claim_type == "chief financial officer"
    assert rule_key.contested_value == "Ryan LeBon"

    assert sem_key.anchor == rule_key.anchor
    assert sem_key.claim_type == rule_key.claim_type
    assert sem_key.contested_value == "James Sullivan"
    assert sem_key.contested_value != rule_key.contested_value


def test_unnormalized_semantic_phrasing_would_not_be_compatible() -> None:
    # Control: shows normalization is what makes the SEMANTIC fact land on
    # the OBJECT_ANCHORED path. Without it the raw phrasing matches no
    # object-anchored shape and falls to SUBJECT_ANCHORED.
    raw_fact = _semantic_fact_without_normalization()
    raw_key = derive_claim_key(raw_fact)
    rule_key = derive_claim_key(_rule_fact())
    assert raw_key.anchor == "James Sullivan"  # SUBJECT_ANCHORED
    assert raw_key.claim_type == SEMANTIC_CFO
    assert (raw_key.anchor, raw_key.claim_type) != (
        rule_key.anchor,
        rule_key.claim_type,
    )


def _semantic_fact_without_normalization() -> Fact:
    cand = ExtractionCandidate(
        subject="James Sullivan",
        predicate=SEMANTIC_CFO,
        object="Company A",
        source_span=_SEM_TEXT,
        origin=ExtractionOrigin.SEMANTIC,
    )
    result = validate_and_build_fact(cand, _SEM_TEXT, _source())
    assert result.fact is not None
    return result.fact

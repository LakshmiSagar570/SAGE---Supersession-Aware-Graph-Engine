# tests/unit/test_extraction_candidate_model.py
"""Phase 4C Step 2 prerequisite: the ExtractionCandidate model change.

PHASE4B_PRODUCTION_CONTRACT.md section 1 requires:
    - `origin: ExtractionOrigin` -- REQUIRED, no default.
    - `llm_confidence: float | None` -- optional, default None
      (RULE candidates have no model-reported confidence).

And, because the model never emits `origin`, the SEMANTIC parser must
stamp it -- and must not trust an `origin` the model tries to supply.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from experiments.semantic_extraction.candidate import (
    ExtractionCandidate,
    ExtractionOrigin,
)
from experiments.semantic_extraction.semantic_extract import (
    SemanticStatus,
    extract_semantic,
)


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "subject": "Company A",
        "predicate": "is headquartered in",
        "object": "Austin, Texas",
        "source_span": "Company A is headquartered in Austin, Texas.",
        "origin": ExtractionOrigin.RULE,
    }
    base.update(overrides)
    return base


class TestOriginField:
    def test_enum_values_match_contract(self) -> None:
        assert ExtractionOrigin.RULE.value == "RULE"
        assert ExtractionOrigin.SEMANTIC.value == "SEMANTIC"
        assert {o.value for o in ExtractionOrigin} == {"RULE", "SEMANTIC"}

    def test_origin_is_required(self) -> None:
        kwargs = _valid_kwargs()
        del kwargs["origin"]
        with pytest.raises(ValidationError):
            ExtractionCandidate(**kwargs)  # type: ignore[arg-type]

    def test_origin_accepts_string_value(self) -> None:
        c = ExtractionCandidate(**_valid_kwargs(origin="SEMANTIC"))  # type: ignore[arg-type]
        assert c.origin is ExtractionOrigin.SEMANTIC

    def test_origin_rejects_unknown_value(self) -> None:
        with pytest.raises(ValidationError):
            ExtractionCandidate(**_valid_kwargs(origin="HUMAN"))  # type: ignore[arg-type]


class TestLlmConfidenceField:
    def test_defaults_to_none(self) -> None:
        c = ExtractionCandidate(**_valid_kwargs())  # type: ignore[arg-type]
        assert c.llm_confidence is None

    def test_explicit_none_accepted(self) -> None:
        c = ExtractionCandidate(**_valid_kwargs(llm_confidence=None))  # type: ignore[arg-type]
        assert c.llm_confidence is None

    @pytest.mark.parametrize("value", [0.0, 0.3, 1.0])
    def test_in_range_float_accepted(self, value: float) -> None:
        c = ExtractionCandidate(**_valid_kwargs(llm_confidence=value))  # type: ignore[arg-type]
        assert c.llm_confidence == value

    @pytest.mark.parametrize("value", [-0.1, 1.5])
    def test_out_of_range_float_still_rejected(self, value: float) -> None:
        """Making the field optional must not have dropped the 0..1 bound."""
        with pytest.raises(ValidationError):
            ExtractionCandidate(**_valid_kwargs(llm_confidence=value))  # type: ignore[arg-type]


def _model_item(**overrides: object) -> dict[str, object]:
    """What a model actually emits: NO origin key (the prompt never asks)."""
    item: dict[str, object] = {
        "subject": "Mr. Thompson",
        "predicate": "is the chief executive officer of",
        "object": "Virtual Instruments",
        "effective_from_text": None,
        "llm_confidence": 1.0,
        "source_span": "Mr. Thompson is the chief executive officer of Virtual Instruments.",
    }
    item.update(overrides)
    return item


class TestSemanticParserStampsOrigin:
    def test_model_response_without_origin_parses_and_is_stamped_semantic(self) -> None:
        result = extract_semantic("ignored", lambda _text: json.dumps([_model_item()]))

        assert result.status is SemanticStatus.OK
        assert len(result.candidates) == 1
        assert result.candidates[0].origin is ExtractionOrigin.SEMANTIC
        assert result.error_detail is None

    def test_model_supplied_origin_is_overridden_not_trusted(self) -> None:
        """A model must never be able to label its own output as RULE."""
        payload = json.dumps([_model_item(origin="RULE")])
        result = extract_semantic("ignored", lambda _text: payload)

        assert result.status is SemanticStatus.OK
        assert result.candidates[0].origin is ExtractionOrigin.SEMANTIC

    def test_one_bad_item_rejects_only_that_item(self) -> None:
        """Phase 2 behavior preserved: per-candidate independence (design 2.5)."""
        bad = _model_item()
        del bad["source_span"]
        payload = json.dumps([_model_item(), bad, _model_item(object="Other Co")])
        result = extract_semantic("ignored", lambda _text: payload)

        assert result.status is SemanticStatus.OK
        assert [c.object for c in result.candidates] == ["Virtual Instruments", "Other Co"]
        assert all(c.origin is ExtractionOrigin.SEMANTIC for c in result.candidates)
        assert result.error_detail is not None
        assert "item 1" in result.error_detail

    def test_empty_array_is_still_ok_with_zero_candidates(self) -> None:
        """Design 2.6: legitimate 'found nothing' is not MALFORMED/UNAVAILABLE."""
        result = extract_semantic("ignored", lambda _text: "[]")

        assert result.status is SemanticStatus.OK
        assert result.candidates == []

    def test_malformed_json_still_classified_malformed(self) -> None:
        result = extract_semantic("ignored", lambda _text: "not json at all")

        assert result.status is SemanticStatus.MALFORMED_RESPONSE
        assert result.candidates == []

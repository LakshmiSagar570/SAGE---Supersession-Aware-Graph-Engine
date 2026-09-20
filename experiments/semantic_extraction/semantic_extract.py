# experiments/semantic_extraction/semantic_extract.py
"""
Phase 2 semantic-extraction experiment -- the LLM-calling layer.

Implements SEMANTIC_EXTRACTION_DESIGN.md section 2.6: API-unavailable
and legitimate-zero-candidate-response are kept as two distinct,
never-merged outcomes.

This module deliberately does NOT hardcode a specific LLM provider or
API client. `call_llm` is injected by the caller (see run_experiment.py)
so this experiment can be run against whatever API/model/credentials
the person running it has configured, without this code needing to
know or store any credentials itself.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, NamedTuple

from pydantic import ValidationError

from experiments.semantic_extraction.candidate import ExtractionCandidate

# Type of the injected LLM-calling function: takes the raw document
# text, returns the raw string response body from the API. Raises on
# network/timeout/non-2xx failure -- this module catches that and maps
# it to SemanticStatus.UNAVAILABLE, per design section 2.6. Parsing the
# response body into candidates is this module's job, not the caller's.
LLMCallFn = Callable[[str], str]


class SemanticStatus(str, Enum):
    """Per design section 2.6 -- kept distinct so later analysis never
    conflates "the API was unreachable" with "the API responded and
    found nothing." """

    OK = "OK"  # API reached, response parsed successfully (candidates list may still be empty)
    UNAVAILABLE = "SEMANTIC_UNAVAILABLE"  # API call itself failed (network, timeout, non-2xx, rate limit)
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"  # API reached, but response body didn't parse into candidates


class SemanticExtractionResult(NamedTuple):
    status: SemanticStatus
    candidates: list[ExtractionCandidate]
    raw_response: str | None
    error_detail: str | None


def extract_semantic(
    raw_text: str,
    call_llm: LLMCallFn,
    *,
    max_retries: int = 2,
) -> SemanticExtractionResult:
    """Call the semantic extractor once for this document and parse its
    response into ExtractionCandidate objects.

    Per design section 2.1: one call per document for this experiment
    (explicitly labeled an initial/experimental strategy, not a
    permanent architectural decision).

    Retry policy per design section 2.6: a small fixed retry budget for
    transient failures (network/timeout/5xx-shaped errors raised by
    call_llm) before falling to UNAVAILABLE. Malformed responses are
    NOT retried -- a well-formed request that produced a badly-shaped
    answer is unlikely to fix itself on retry.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            raw_response = call_llm(raw_text)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # transport-level failure (network, timeout, non-2xx, rate
            # limit) from the injected call_llm should be treated as a
            # candidate for retry/UNAVAILABLE, not crash the experiment.
            last_error = exc
            continue

        # API was reached and returned something. Parsing failure here
        # is NOT retried -- see docstring.
        return _parse_response(raw_response)

    return SemanticExtractionResult(
        status=SemanticStatus.UNAVAILABLE,
        candidates=[],
        raw_response=None,
        error_detail=str(last_error) if last_error else "unknown failure",
    )


def _parse_response(raw_response: str) -> SemanticExtractionResult:
    """Parse a successfully-received API response body into candidates.

    Expected shape: a JSON array of objects, each matching
    ExtractionCandidate's fields. An empty array `[]` is a legitimate,
    successful "found nothing" result -- SemanticStatus.OK, not
    MALFORMED_RESPONSE and not UNAVAILABLE. Per design section 2.6,
    this distinction must never be lost.
    """
    import json

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return SemanticExtractionResult(
            status=SemanticStatus.MALFORMED_RESPONSE,
            candidates=[],
            raw_response=raw_response,
            error_detail=f"JSON parse failure: {exc}",
        )

    if not isinstance(parsed, list):
        return SemanticExtractionResult(
            status=SemanticStatus.MALFORMED_RESPONSE,
            candidates=[],
            raw_response=raw_response,
            error_detail="Response was valid JSON but not a list.",
        )

    candidates: list[ExtractionCandidate] = []
    parse_errors: list[str] = []
    for i, item in enumerate(parsed):
        try:
            candidates.append(ExtractionCandidate(**item))
        except ValidationError as exc:
            # Per design section 2.5: a single malformed candidate within
            # an otherwise-valid response is rejected individually --
            # other valid candidates in the same response still proceed.
            parse_errors.append(f"item {i}: {exc}")

    return SemanticExtractionResult(
        status=SemanticStatus.OK,
        candidates=candidates,
        raw_response=raw_response,
        error_detail="; ".join(parse_errors) if parse_errors else None,
    )
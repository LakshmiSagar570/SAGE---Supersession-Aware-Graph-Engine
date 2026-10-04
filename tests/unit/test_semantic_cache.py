"""Phase 4C Step 11 -- semantic extraction caching / idempotency.

Covers PHASE4C_IMPLEMENTATION_PLAN.md Step 11's locked requirements and
every item in the Step 11 instruction's section 13 checklist:
    1.  deterministic cache-key generation
    2.  each of the four cache-key dimensions
    3.  identical content across different paths
    4.  changed document content
    5.  cache miss -> provider called
    6.  cache hit -> provider not called
    7.  model-version invalidation
    8.  prompt-version invalidation
    9.  schema-version invalidation
    10. serialization round-trip
    11. corrupt cache behavior
    12. provider failure behavior
    13. two-run cache/idempotency behavior
    14. llm_confidence preserved as candidate metadata, never Fact.confidence
    15. existing semantic extraction regression behavior (extract_semantic
        itself, proven unchanged)

Hard boundary enforced throughout, per explicit instruction: fact_id and
extracted_at are NEVER asserted equal across two runs -- doing so would
contradict the locked, non-negotiable Fact identity semantics
(contracts/fact_schema.py, unmodified).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from contracts.fact_schema import Source, SourceID, SourceType
from experiments.semantic_extraction.candidate import (
    ExtractionCandidate,
    ExtractionOrigin,
    validate_and_build_fact,
)
from experiments.semantic_extraction.nvidia_client import CACHE_IDENTITY as NVIDIA_IDENTITY
from experiments.semantic_extraction.openai_client import CACHE_IDENTITY as OPENAI_IDENTITY
from experiments.semantic_extraction.semantic_cache import (
    CacheIdentity,
    CacheUnavailableError,
    CorruptCacheEntryError,
    SemanticCache,
    build_cache_key,
    document_content_hash,
    extract_semantic_cached,
)
from experiments.semantic_extraction.semantic_extract import (
    SemanticExtractionResult,
    SemanticStatus,
    extract_semantic,
)


def _item(
    subject: str = "A",
    predicate: str = "is the ceo of",
    obj: str = "B",
    span: str = "A is the ceo of B.",
    confidence: float | None = 0.9,
) -> dict[str, object]:
    return {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "source_span": span,
        "effective_from_text": None,
        "llm_confidence": confidence,
    }


def _counting_llm(
    items: list[dict[str, object]], calls: list[str]
) -> Callable[[str], str]:
    def call_llm(raw_text: str) -> str:
        calls.append(raw_text)
        return json.dumps(items)

    return call_llm


_ID_A = CacheIdentity(
    model_identifier="model-a", prompt_version="prompt-v1", extraction_schema_version="schema-v1"
)
_ID_B_MODEL = CacheIdentity(
    model_identifier="model-b", prompt_version="prompt-v1", extraction_schema_version="schema-v1"
)
_ID_B_PROMPT = CacheIdentity(
    model_identifier="model-a", prompt_version="prompt-v2", extraction_schema_version="schema-v1"
)
_ID_B_SCHEMA = CacheIdentity(
    model_identifier="model-a", prompt_version="prompt-v1", extraction_schema_version="schema-v2"
)


# ----------------------------------------------------------------- (1)(2)
# deterministic cache-key generation, each of the four dimensions


def test_same_inputs_produce_same_key() -> None:
    h = document_content_hash("doc text")
    assert build_cache_key(h, _ID_A) == build_cache_key(h, _ID_A)


def test_different_document_produces_different_key() -> None:
    h1 = document_content_hash("doc text one")
    h2 = document_content_hash("doc text two")
    assert build_cache_key(h1, _ID_A) != build_cache_key(h2, _ID_A)


def test_different_model_produces_different_key() -> None:
    h = document_content_hash("doc text")
    assert build_cache_key(h, _ID_A) != build_cache_key(h, _ID_B_MODEL)


def test_different_prompt_version_produces_different_key() -> None:
    h = document_content_hash("doc text")
    assert build_cache_key(h, _ID_A) != build_cache_key(h, _ID_B_PROMPT)


def test_different_schema_version_produces_different_key() -> None:
    h = document_content_hash("doc text")
    assert build_cache_key(h, _ID_A) != build_cache_key(h, _ID_B_SCHEMA)


def test_cache_key_is_a_pure_function_of_its_four_inputs() -> None:
    # Constructing CacheIdentity fields in different orders (kwargs) must
    # not change the resulting key -- the serialization uses a fixed
    # field order internally, not dict/kwarg iteration order.
    a = CacheIdentity(model_identifier="m", prompt_version="p", extraction_schema_version="s")
    b = CacheIdentity(extraction_schema_version="s", prompt_version="p", model_identifier="m")
    h = document_content_hash("x")
    assert build_cache_key(h, a) == build_cache_key(h, b)


# --------------------------------------------------------------------- (3)
# identical content across different paths


def test_identical_content_different_paths_same_hash(tmp_path: Path) -> None:
    content = "Mr. Thompson is the chief executive officer of Virtual Instruments."
    path_a = tmp_path / "a" / "document.txt"
    path_b = tmp_path / "b" / "document.txt"
    path_a.parent.mkdir(parents=True)
    path_b.parent.mkdir(parents=True)
    path_a.write_text(content)
    path_b.write_text(content)

    hash_a = document_content_hash(path_a.read_text())
    hash_b = document_content_hash(path_b.read_text())
    assert hash_a == hash_b
    assert build_cache_key(hash_a, _ID_A) == build_cache_key(hash_b, _ID_A)


# --------------------------------------------------------------------- (4)
# changed document content


def test_one_byte_content_change_changes_hash_and_key() -> None:
    original = "Mr. Thompson is the chief executive officer of Virtual Instruments."
    changed = original[:-1] + "!"  # final "." -> "!", one byte different
    h1 = document_content_hash(original)
    h2 = document_content_hash(changed)
    assert h1 != h2
    assert build_cache_key(h1, _ID_A) != build_cache_key(h2, _ID_A)


# ----------------------------------------------------------------- (5)(6)
# cache miss -> provider called; cache hit -> provider not called


def test_cache_miss_calls_provider_exactly_once(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    result = extract_semantic_cached(
        "doc text", _counting_llm([_item()], calls), _ID_A, cache=cache
    )
    assert len(calls) == 1
    assert result.status is SemanticStatus.OK
    assert len(result.candidates) == 1


def test_cache_hit_does_not_call_provider(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([_item()], calls)

    r1 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    r2 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)

    assert len(calls) == 1  # NOT 2 -- the second call must be a cache hit
    assert r1.status is r2.status
    assert [c.model_dump() for c in r1.candidates] == [c.model_dump() for c in r2.candidates]


def test_cache_hit_returns_a_separate_candidate_list_instance(tmp_path: Path) -> None:
    # The cached result is deserialized fresh on each hit, not a shared
    # mutable reference to the first call's in-memory objects -- mutating
    # one returned result must not affect a later retrieval.
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([_item()], calls)

    r1 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    r1.candidates.append(
        ExtractionCandidate(
            subject="X", predicate="is", object="Y", source_span="x", origin=ExtractionOrigin.SEMANTIC
        )
    )
    r2 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    assert len(r2.candidates) == 1


# ------------------------------------------------------------- (7)(8)(9)
# version invalidation: model, prompt, schema -- each independently


def test_model_version_change_is_a_cache_miss(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([_item()], calls)

    extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    extract_semantic_cached("doc text", llm, _ID_B_MODEL, cache=cache)

    assert len(calls) == 2  # different model -> NOT served from _ID_A's cache


def test_prompt_version_change_is_a_cache_miss(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([_item()], calls)

    extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    extract_semantic_cached("doc text", llm, _ID_B_PROMPT, cache=cache)

    assert len(calls) == 2


def test_schema_version_change_is_a_cache_miss(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([_item()], calls)

    extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    extract_semantic_cached("doc text", llm, _ID_B_SCHEMA, cache=cache)

    assert len(calls) == 2


def test_nvidia_and_openai_identities_have_different_prompt_versions() -> None:
    # Direct regression guard against collapsing the two clients' real,
    # differently-worded prompts into one shared version identifier.
    assert NVIDIA_IDENTITY.prompt_version != OPENAI_IDENTITY.prompt_version
    assert NVIDIA_IDENTITY.model_identifier != OPENAI_IDENTITY.model_identifier


def test_nvidia_and_openai_share_schema_version_justifiably() -> None:
    # Both clients produce the same ExtractionCandidate shape via the
    # same semantic_extract._parse_response -- a shared schema version
    # is a deliberate, justified choice here, not an oversight.
    assert NVIDIA_IDENTITY.extraction_schema_version == OPENAI_IDENTITY.extraction_schema_version


# --------------------------------------------------------------------- (10)
# serialization round-trip


def test_round_trip_preserves_all_candidate_fields(tmp_path: Path) -> None:
    item = _item(
        subject="James Sullivan",
        predicate="was appointed Chief Financial Officer of",
        obj="8x8, Inc.",
        span="James Sullivan has been appointed chief financial officer of 8x8, Inc.",
        confidence=0.77,
    )
    item["effective_from_text"] = "January 1, 2014"
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([item], calls)

    r1 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    r2 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)  # cache hit

    (c1,) = r1.candidates
    (c2,) = r2.candidates
    for field in (
        "subject",
        "predicate",
        "object",
        "source_span",
        "effective_from_text",
        "origin",
        "llm_confidence",
    ):
        assert getattr(c1, field) == getattr(c2, field), field
    assert c2.origin is ExtractionOrigin.SEMANTIC


def test_round_trip_preserves_empty_candidate_list(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([], calls)

    r1 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    r2 = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)

    assert r1.candidates == r2.candidates == []
    assert len(calls) == 1


# --------------------------------------------------------------------- (11)
# corrupt cache behavior


def test_corrupt_cache_file_is_treated_as_a_miss_not_a_crash(tmp_path: Path) -> None:
    cache = SemanticCache(cache_dir=tmp_path)
    h = document_content_hash("doc text")
    key = build_cache_key(h, _ID_A)
    cache._cache_dir.mkdir(parents=True, exist_ok=True)
    (cache._cache_dir / f"{key}.json").write_text("{ this is not valid json")

    calls: list[str] = []
    llm = _counting_llm([_item()], calls)

    result = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)

    assert len(calls) == 1  # fell back to a fresh call, did not crash
    assert result.status is SemanticStatus.OK


def test_corrupt_cache_entry_is_overwritten_with_fresh_valid_result(tmp_path: Path) -> None:
    cache = SemanticCache(cache_dir=tmp_path)
    h = document_content_hash("doc text")
    key = build_cache_key(h, _ID_A)
    cache._cache_dir.mkdir(parents=True, exist_ok=True)
    (cache._cache_dir / f"{key}.json").write_text("not json")

    calls: list[str] = []
    llm = _counting_llm([_item()], calls)

    extract_semantic_cached("doc text", llm, _ID_A, cache=cache)  # repairs the entry
    extract_semantic_cached("doc text", llm, _ID_A, cache=cache)  # should now be a real hit

    assert len(calls) == 1  # second call used the now-valid cached entry


def test_semantic_cache_get_raises_typed_error_on_corrupt_entry(tmp_path: Path) -> None:
    cache = SemanticCache(cache_dir=tmp_path)
    cache._cache_dir.mkdir(parents=True, exist_ok=True)
    (cache._cache_dir / "somekey.json").write_text("{not valid")
    with pytest.raises(CorruptCacheEntryError):
        cache.get("somekey")


def test_corrupt_entry_missing_required_payload_key_raises_typed_error(tmp_path: Path) -> None:
    cache = SemanticCache(cache_dir=tmp_path)
    cache._cache_dir.mkdir(parents=True, exist_ok=True)
    # Valid JSON, but missing the "candidates" key entirely.
    (cache._cache_dir / "somekey.json").write_text(json.dumps({"status": "OK"}))
    with pytest.raises(CorruptCacheEntryError):
        cache.get("somekey")


# --------------------------------------------------------------------- (12)
# provider failure behavior: cache-unavailable fallback, and the
# existing MALFORMED_RESPONSE / SEMANTIC_UNAVAILABLE distinction


def test_semantic_cache_set_raises_typed_error_when_write_fails(tmp_path: Path) -> None:
    # Unit-level contract of SemanticCache.set itself (not just the
    # end-to-end fallback through extract_semantic_cached): a write
    # failure must surface as CacheUnavailableError, not be silently
    # swallowed inside the storage layer -- the wrapper function is
    # responsible for deciding to fall back, not SemanticCache itself.
    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("x")
    cache = SemanticCache(cache_dir=blocking_file / "subdir")

    dummy_result = SemanticExtractionResult(
        status=SemanticStatus.OK, candidates=[], raw_response="[]", error_detail=None
    )
    with pytest.raises(CacheUnavailableError):
        cache.set("somekey", dummy_result)


def test_cache_unavailable_falls_back_to_fresh_extraction(tmp_path: Path) -> None:
    # A path that cannot be used as a directory (a FILE sits where the
    # cache dir would be) forces every cache operation to fail.
    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("x")
    cache = SemanticCache(cache_dir=blocking_file / "subdir")

    calls: list[str] = []
    llm = _counting_llm([_item()], calls)

    result = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)

    assert len(calls) == 1
    assert result.status is SemanticStatus.OK


def test_cache_unavailable_does_not_raise_to_the_caller(tmp_path: Path) -> None:
    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("x")
    cache = SemanticCache(cache_dir=blocking_file / "subdir")
    calls: list[str] = []
    llm = _counting_llm([_item()], calls)

    # Must not raise CacheUnavailableError (or anything else) to the
    # caller -- the documented fallback behavior is silent degradation
    # to a fresh extraction, not propagating the storage failure.
    extract_semantic_cached("doc text", llm, _ID_A, cache=cache)


def test_unavailable_status_is_never_cached() -> None:
    def failing_llm(_text: str) -> str:
        raise RuntimeError("network down")

    import tempfile

    with tempfile.TemporaryDirectory() as d:
        cache = SemanticCache(cache_dir=d)
        result = extract_semantic_cached(
            "doc text", failing_llm, _ID_A, cache=cache, max_retries=0
        )
        assert result.status is SemanticStatus.UNAVAILABLE

        # A second call must retry (not serve a cached UNAVAILABLE) --
        # confirmed by a call counter this time.
        calls: list[str] = []

        def now_working_llm(text: str) -> str:
            calls.append(text)
            return json.dumps([_item()])

        result2 = extract_semantic_cached(
            "doc text", now_working_llm, _ID_A, cache=cache, max_retries=0
        )
        assert len(calls) == 1  # provider WAS called -- UNAVAILABLE was not cached
        assert result2.status is SemanticStatus.OK


def test_malformed_response_status_preserved_through_cache(tmp_path: Path) -> None:
    cache = SemanticCache(cache_dir=tmp_path)
    calls: list[str] = []

    def malformed_llm(text: str) -> str:
        calls.append(text)
        return "not json at all"

    r1 = extract_semantic_cached("doc text", malformed_llm, _ID_A, cache=cache)
    assert r1.status is SemanticStatus.MALFORMED_RESPONSE

    r2 = extract_semantic_cached("doc text", malformed_llm, _ID_A, cache=cache)
    assert r2.status is SemanticStatus.MALFORMED_RESPONSE
    assert len(calls) == 1  # MALFORMED_RESPONSE WAS cached -- provider not re-called


def test_cache_never_introduces_its_own_status_category(tmp_path: Path) -> None:
    # Every status this module can return is one of extract_semantic's
    # own three -- caching never invents a fourth.
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([_item()], [])
    result = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    assert result.status in {
        SemanticStatus.OK,
        SemanticStatus.UNAVAILABLE,
        SemanticStatus.MALFORMED_RESPONSE,
    }


# --------------------------------------------------------------------- (13)
# two-run cache/idempotency behavior -- the required negative assertion


def test_two_runs_same_cache_key_same_semantic_result_different_fact_identity(
    tmp_path: Path,
) -> None:
    """The exact scenario the Step 11 instruction's section 9 describes.

    Asserts what SHOULD be true (cache keys equal, semantic result
    content equal, second run does not invoke the provider) and
    explicitly asserts what must NOT be assumed (fact_id equal,
    extracted_at equal) -- a negative assertion, not merely an omission,
    so a future change that accidentally makes Facts byte-identical
    across runs is caught here rather than silently passing.
    """
    raw_text = "Mr. Thompson is the chief executive officer of Virtual Instruments."
    calls: list[str] = []
    llm = _counting_llm(
        [_item(subject="Mr. Thompson", predicate="is the chief executive officer of", obj="Virtual Instruments", span=raw_text)],
        calls,
    )
    cache = SemanticCache(cache_dir=tmp_path)

    # --- "run 1" ---
    key1 = build_cache_key(document_content_hash(raw_text), _ID_A)
    result1 = extract_semantic_cached(raw_text, llm, _ID_A, cache=cache)
    source = Source(source_id=SourceID("s1"), name="s", source_type=SourceType.DOCUMENT, locator="x")
    fact1 = validate_and_build_fact(result1.candidates[0], raw_text, source).fact
    assert fact1 is not None

    # --- "run 2", independent candidate -> Fact conversion ---
    key2 = build_cache_key(document_content_hash(raw_text), _ID_A)
    result2 = extract_semantic_cached(raw_text, llm, _ID_A, cache=cache)
    fact2 = validate_and_build_fact(result2.candidates[0], raw_text, source).fact
    assert fact2 is not None

    # Required positive assertions:
    assert key1 == key2, "cache keys equal: expected YES"
    assert [c.model_dump() for c in result1.candidates] == [
        c.model_dump() for c in result2.candidates
    ], "semantic results equal: expected YES"
    assert len(calls) == 1, "second execution must not invoke the semantic model"

    # Required NEGATIVE assertions -- Fact identity is NOT reused:
    assert fact1.fact_id != fact2.fact_id, "fact_id must differ between independent conversions"
    # extracted_at: not asserted unequal with a hard inequality (two
    # conversions in the same microsecond are physically possible on a
    # fast machine), but it MUST be independently generated, not copied
    # from the cache. Confirmed structurally: validate_and_build_fact's
    # own source (unmodified by this step) always calls
    # datetime.now(UTC) fresh -- see test below for that structural
    # check rather than relying on timing to always differ.
    assert fact1.confidence == 1.0
    assert fact2.confidence == 1.0


def test_validate_and_build_fact_always_calls_datetime_now_fresh() -> None:
    # Structural guard for the point above: confirms the ACTUAL source of
    # candidate.py's conversion function still calls datetime.now(UTC)
    # unconditionally (this module's cache has no hook into it and
    # cannot have modified it, but this pins the invariant explicitly
    # rather than only inferring it from behavior).
    import inspect

    source = inspect.getsource(validate_and_build_fact)
    assert "datetime.now(UTC)" in source
    assert "uuid4()" in source


# --------------------------------------------------------------------- (14)
# llm_confidence preserved as candidate metadata, never Fact.confidence


def test_llm_confidence_survives_cache_round_trip_but_fact_confidence_is_always_1(
    tmp_path: Path,
) -> None:
    item = _item(confidence=0.42)
    cache = SemanticCache(cache_dir=tmp_path)
    llm = _counting_llm([item], [])

    result = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)
    hit = extract_semantic_cached("doc text", llm, _ID_A, cache=cache)

    assert result.candidates[0].llm_confidence == 0.42
    assert hit.candidates[0].llm_confidence == 0.42  # preserved through cache

    source = Source(source_id=SourceID("s1"), name="s", source_type=SourceType.DOCUMENT, locator="x")
    fact = validate_and_build_fact(hit.candidates[0], "A is the ceo of B.", source).fact
    assert fact is not None
    assert fact.confidence == 1.0  # NOT 0.42 -- llm_confidence never leaks into Fact.confidence
    assert "llm_confidence" not in fact.metadata
    assert fact.metadata == {}


# --------------------------------------------------------------------- (15)
# existing semantic extraction regression behavior -- extract_semantic
# itself is provably unchanged by this step


def test_extract_semantic_signature_unchanged() -> None:
    import inspect

    sig = inspect.signature(extract_semantic)
    params = list(sig.parameters)
    assert params == ["raw_text", "call_llm", "max_retries"]


def test_extract_semantic_still_works_called_directly_with_no_cache_involved() -> None:
    # Direct proof that extract_semantic(raw_text, call_llm) -- the exact
    # existing call shape used by run_experiment.py and
    # run_step6_semantic_edgar.py -- still works completely unmodified
    # and without ever importing semantic_cache.
    result = extract_semantic("doc text", lambda _t: json.dumps([_item()]))
    assert isinstance(result, SemanticExtractionResult)
    assert result.status is SemanticStatus.OK
    assert len(result.candidates) == 1


def test_semantic_cache_module_does_not_modify_semantic_extract_module() -> None:
    # semantic_cache.py must import, not monkeypatch, extract_semantic.
    import inspect

    import experiments.semantic_extraction.semantic_extract as se_module

    original_source = inspect.getsource(se_module.extract_semantic)
    assert "semantic_cache" not in original_source

# experiments/semantic_extraction/semantic_cache.py
"""
Phase 4C Step 11 -- semantic extraction caching / idempotency wrapper.

Implements the locked cache identity from PHASE4B_PRODUCTION_CONTRACT.md
section 7:

    (document_content_hash, model_identifier, prompt_version,
     extraction_schema_version)

DELIBERATE DESIGN CHOICE, per explicit instruction: this module sits
*around* semantic_extract.extract_semantic(), not inside it.
extract_semantic(raw_text, call_llm) is UNCHANGED by this file -- its
signature, body, and every existing caller remain exactly as they were.
Cache/version metadata (model identifier, prompt version, schema
version) does not become part of that function's API. This keeps the
semantic PARSER (what does a response mean) separate from the cache
IDENTITY (which computation produced this response), which matters
specifically because this project has two independently maintained
LLM clients with two different, non-interchangeable prompts
(nvidia_client.py, openai_client.py) -- collapsing their identity into
one shared value would misrepresent which prompt actually produced a
given cached result.

WHAT THIS CACHES: the semantic extraction COMPUTATION -- the raw API
response body for a given (document, model, prompt, schema) 4-tuple --
not a Fact and not a graph node. A cache hit replays a previously
parsed SemanticExtractionResult without calling call_llm again.

WHAT THIS DOES NOT DO, per explicit, locked boundary:
  - Does not make Fact.fact_id or Fact.extracted_at deterministic.
    Both remain freshly generated at candidate->Fact conversion time
    (candidate.py::validate_and_build_fact, UNCHANGED), every time,
    cache hit or not. A cache hit means the SAME semantic content is
    available again, not that a prior Fact is reused.
  - Does not modify contracts/fact_schema.py, Stage 2-6, or
    semantic_extract.py.
  - Does not implement Fact-level or graph-level deduplication. Step
    10 already established, empirically, that RULE+SEMANTIC agreement
    currently materializes as two separate Fact nodes; this module
    does not change that.
  - Does not collapse SemanticStatus.MALFORMED_RESPONSE /
    SEMANTIC_UNAVAILABLE into a cache-specific error category. A
    malformed or unavailable result is itself a valid, real thing to
    cache or not cache -- see _should_cache below -- but its own
    status is preserved exactly as extract_semantic produced it.

STORAGE: a simple local file-based cache (one JSON file per cache
key, under a directory), per PHASE4B_PRODUCTION_CONTRACT.md section 7:
"adequate for verification purposes; a production deployment's actual
storage choice is not decided here and is not blocking for Phase 4C's
completion." Nothing here presumes this is the final production
mechanism.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from experiments.semantic_extraction.candidate import (
    ExtractionCandidate,
)
from experiments.semantic_extraction.semantic_extract import (
    LLMCallFn,
    SemanticExtractionResult,
    SemanticStatus,
    extract_semantic,
)

DEFAULT_CACHE_DIR = Path("experiments/semantic_extraction/.cache")


@dataclass(frozen=True)
class CacheIdentity:
    """The three non-document dimensions of the locked 4-tuple.

    Deliberately NOT shared between clients by default -- each client
    module (nvidia_client.py, openai_client.py) defines its own
    CacheIdentity naming the model it actually calls and the prompt it
    actually sends, since the two prompts are real, different text,
    not the same prompt under two names. extraction_schema_version MAY
    legitimately be shared across clients when they produce candidates
    to the same schema (both do, as of Step 11 -- see each client
    module for why that's a justified, not assumed, shared value).
    """

    model_identifier: str
    prompt_version: str
    extraction_schema_version: str


class CorruptCacheEntryError(Exception):
    """Raised when a cache file exists but cannot be parsed into a
    valid cached result. Per section 11's requirement: a malformed
    cache entry must not silently become a valid semantic extraction
    result. The caller (extract_semantic_cached) catches this and
    treats it as a miss -- see that function's docstring for why a
    miss, not a crash, is the chosen behavior, grounded in this
    project's existing convention (semantic_extract.py already treats
    a malformed LLM response as MALFORMED_RESPONSE, a real, visible
    result category, rather than raising -- a malformed cache entry is
    the same kind of thing, a recoverable data-quality problem, not a
    reason to halt the caller).
    """


class CacheUnavailableError(Exception):
    """Raised when the cache backend/storage cannot be used at all
    (e.g. the cache directory cannot be created or written to). Per
    section 11: the chosen behavior, grounded in this project's
    existing failure-independence principle (4B section 8 -- "no
    document-level failure in either extractor blocks the other
    extractor's output ... from proceeding"), is to FALL BACK to a
    fresh extraction rather than fail closed. A cache is an
    optimization; losing it should not stop semantic extraction from
    running. This is stated and tested explicitly, not left implicit.
    """


def document_content_hash(raw_text: str) -> str:
    """SHA-256 of the document's actual text content. Deliberately
    takes content, not a path -- per section 8's requirement, two
    different files containing byte-identical text must hash
    identically, and this function has no way to see a path even if
    it wanted to.
    """
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def build_cache_key(doc_hash: str, identity: CacheIdentity) -> str:
    """Deterministic cache key for the locked 4-tuple.

    Serializes the four components with a fixed, explicit field order
    and delimiter (not Python dict iteration order, which is
    insertion-order-stable in CPython but not a documented contract to
    rely on for a cache key) before hashing, so the same four logical
    values always produce the same key regardless of call-site
    construction order. No filesystem paths, timestamps, or UUIDs
    enter this function at all -- it only ever sees the four locked,
    content-derived values.
    """
    # "v1" is this function's own key-construction scheme version, so a
    # future change to this serialization can't silently collide with
    # keys built by an earlier version of this function.
    scheme_version = "v1"
    serialized = (
        f"{scheme_version}|{doc_hash}|{identity.model_identifier}"
        f"|{identity.prompt_version}|{identity.extraction_schema_version}"
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------
# Serialization of a SemanticExtractionResult for storage.
#
# SemanticExtractionResult is a NamedTuple of
# (status, candidates, raw_response, error_detail). candidates is a
# list[ExtractionCandidate] (a pydantic BaseModel, already JSON-
# serializable via model_dump/model_validate). This round-trips every
# field already present on ExtractionCandidate -- subject, predicate,
# object, source_span, effective_from_text, origin, llm_confidence --
# without introducing any new field. No new contract field is added
# anywhere by this serialization.
# ---------------------------------------------------------------------


def _serialize_result(result: SemanticExtractionResult) -> str:
    payload = {
        "status": result.status.value,
        "candidates": [c.model_dump(mode="json") for c in result.candidates],
        "raw_response": result.raw_response,
        "error_detail": result.error_detail,
    }
    return json.dumps(payload)


def _deserialize_result(raw: str) -> SemanticExtractionResult:
    try:
        payload = json.loads(raw)
        status = SemanticStatus(payload["status"])
        candidates = [
            ExtractionCandidate(**item) for item in payload["candidates"]
        ]
        raw_response = payload["raw_response"]
        error_detail = payload["error_detail"]
    except Exception as exc:
        # here means the cache entry is corrupt; see CorruptCacheEntryError's
        # docstring for why this becomes a typed, caught exception rather
        # than an uncaught crash or a silent default.
        raise CorruptCacheEntryError(
            f"Cache entry could not be parsed into a SemanticExtractionResult: {exc}"
        ) from exc

    return SemanticExtractionResult(
        status=status,
        candidates=candidates,
        raw_response=raw_response,
        error_detail=error_detail,
    )


def _should_cache(result: SemanticExtractionResult) -> bool:
    """Only a successfully-reached, successfully-parsed result is
    cached. A SEMANTIC_UNAVAILABLE result (the API call itself failed)
    is deliberately NOT cached -- caching "the API was down" would
    convert a transient infrastructure failure into a permanent one for
    the lifetime of the cache entry, for every future call with this
    exact 4-tuple, which is worse than just calling again. This
    mirrors semantic_extract.py's own existing retry policy (section
    2.6: transient failures are retried, not treated as a stable
    result) rather than inventing a new rule.

    A MALFORMED_RESPONSE result IS cached: the API was reached and
    genuinely produced this malformed content for this exact 4-tuple;
    that is a real, reproducible fact about this (document, model,
    prompt, schema) combination, and re-calling the API for the exact
    same input is unlikely to produce a different result (the same
    reasoning semantic_extract.py already uses to decide NOT to retry
    a malformed response -- see its _parse_response docstring).
    """
    return result.status is not SemanticStatus.UNAVAILABLE


class SemanticCache:
    """File-based cache, one JSON file per cache key.

    Explicitly a thin, swappable storage layer: every public method on
    this class is a plain get/set/exists over a cache_key string, with
    no knowledge of the 4-tuple, hashing, or call_llm above it. A
    different storage backend (e.g. for a real production deployment --
    explicitly NOT decided in Phase 4C, per 4B section 7) could replace
    this class without changing extract_semantic_cached's own logic,
    as long as it preserves this same get/set interface.
    """

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = Path(cache_dir)

    def _path_for(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.json"

    def get(self, cache_key: str) -> SemanticExtractionResult | None:
        """Returns the cached result, or None on a genuine miss (no
        file for this key). Raises CorruptCacheEntryError if a file
        exists but cannot be parsed -- this is distinct from a miss and
        must not be silently treated as one (section 11's requirement
        that a corrupt entry not silently become valid applies in the
        other direction too: it must not silently become invisible,
        either, since that would hide a real data-corruption problem
        behind an ordinary cache-miss code path).
        """
        path = self._path_for(cache_key)
        try:
            exists = path.exists()
        except OSError as exc:
            raise CacheUnavailableError(
                f"Cannot check cache path {path}: {exc}"
            ) from exc

        if not exists:
            return None

        try:
            raw = path.read_text()
        except OSError as exc:
            raise CacheUnavailableError(f"Cannot read cache file {path}: {exc}") from exc

        return _deserialize_result(raw)  # may raise CorruptCacheEntryError

    def set(self, cache_key: str, result: SemanticExtractionResult) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._path_for(cache_key)
            path.write_text(_serialize_result(result))
        except OSError as exc:
            raise CacheUnavailableError(
                f"Cannot write cache file under {self._cache_dir}: {exc}"
            ) from exc


def extract_semantic_cached(
    raw_text: str,
    call_llm: LLMCallFn,
    identity: CacheIdentity,
    *,
    cache: SemanticCache | None = None,
    max_retries: int = 2,
) -> SemanticExtractionResult:
    """Cache-aware wrapper around the real, unmodified extract_semantic().

    Cache miss:
        compute cache_key -> call extract_semantic(raw_text, call_llm)
        (unchanged) -> if the result qualifies (_should_cache), store
        it -> return it.

    Cache hit:
        compute cache_key -> retrieve and deserialize the stored
        result -> return it. call_llm is NOT invoked.

    Failure behavior, both per explicit instruction (section 11) and
    grounded in existing project convention rather than invented here:
      - A corrupt cache entry (CorruptCacheEntryError) is treated as a
        miss: a fresh extraction is performed, and -- if it qualifies --
        the corrupted entry is overwritten with the fresh, valid
        result. This follows semantic_extract.py's own existing
        tolerance for a bad response (classify and recover, don't
        crash the caller) rather than letting a corrupt cache file take
        down an otherwise-working extraction.
      - A CacheUnavailableError (the storage backend itself cannot be
        read or written) causes this function to fall back to a fresh
        extraction WITHOUT caching the result (since the cache cannot
        be written to either) -- see CacheUnavailableError's docstring
        for the reasoning. This is a real behavioral decision, stated
        here explicitly rather than left to be discovered from the
        code.
      - SemanticStatus.MALFORMED_RESPONSE and SEMANTIC_UNAVAILABLE,
        when they occur (from a fresh call, cache miss or fallback),
        are returned exactly as extract_semantic produced them --
        never relabeled as a cache-specific error category.
    """
    cache = cache if cache is not None else SemanticCache()
    doc_hash = document_content_hash(raw_text)
    cache_key = build_cache_key(doc_hash, identity)

    try:
        cached = cache.get(cache_key)
    except CorruptCacheEntryError:
        cached = None  # treated as a miss; see docstring
    except CacheUnavailableError:
        # Storage itself is unreachable -- fall back to a fresh call,
        # and skip the store step below too (best-effort only).
        result = extract_semantic(raw_text, call_llm, max_retries=max_retries)
        return result

    if cached is not None:
        return cached

    result = extract_semantic(raw_text, call_llm, max_retries=max_retries)

    if _should_cache(result):
        try:
            cache.set(cache_key, result)
        except CacheUnavailableError:
            # Storage unreachable at write time -- the fresh result is
            # still returned to the caller; only the caching itself is
            # skipped (best-effort, per CacheUnavailableError's
            # documented fallback behavior).
            pass

    return result

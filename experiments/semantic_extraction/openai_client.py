# experiments/semantic_extraction/openai_client.py
"""
Real OpenAI-backed implementation of the call_llm function
run_experiment.py's build_call_llm() needs to return.

Usage: set the OPENAI_API_KEY environment variable, then in
run_experiment.py replace:

    def build_call_llm() -> LLMCallFn:
        raise NotImplementedError(...)

with:

    from experiments.semantic_extraction.openai_client import build_openai_call_llm

    def build_call_llm() -> LLMCallFn:
        return build_openai_call_llm()

Model default is "gpt-4o-mini" -- cheap, widely available, and
deliberately NOT the most capable model OpenAI offers. Per the
design's own stated purpose (measuring what a real semantic extractor
actually recovers, not showcasing best-case results), a weaker/cheaper
model is an honest choice, not a compromise -- it's also more likely to
surface real malformed-output and hallucinated-span cases, which the
harness (candidate.py, semantic_extract.py) already has a real,
tested path for handling rather than assuming won't happen.

This module does not import into or get called by anything under
src/sage/pipeline/ -- it's wired in only via run_experiment.py's
build_call_llm(), which is itself an isolated experiment entrypoint.
"""

from __future__ import annotations

import os

_SYSTEM_PROMPT = """You are a fact-extraction tool. You will be given a short excerpt of real text (often from a company's SEC filing). Your job is to identify factual claims explicitly stated in the text -- do not infer, guess, or add information that isn't directly written.

For each claim you find, return an object with these exact fields:
- "subject": the entity the claim is about (a person or company name, as written in the text)
- "predicate": a short phrase describing the relationship (e.g. "is headquartered in", "is the chief executive officer of", "was appointed Chief Financial Officer of", "was founded on")
- "object": the value of the claim (a place, a company name, a date, etc., as written in the text)
- "effective_from_text": if the text states an explicit date or effective date for this claim, the exact date phrase as written (e.g. "January 1, 2014" or "2014-01-01"); otherwise null
- "llm_confidence": your own estimate, from 0.0 to 1.0, of how confident you are that this is a correctly and completely extracted claim
- "source_span": the EXACT, VERBATIM substring of the input text that this claim was extracted from. This must be copied character-for-character from the input -- do not paraphrase, summarize, or lightly edit it. If you cannot produce an exact substring, do not include the claim.

Respond with ONLY a JSON array of these objects. If the text contains no such claims, respond with an empty array: []. Do not include any text before or after the JSON array."""



# Phase 4C Step 11 -- cache identity for this client's exact
# (model, prompt) combination. prompt_version="openai-semantic-v1" is
# a DIFFERENT value from nvidia_client.py's "nvidia-semantic-v1" on
# purpose: this module's _SYSTEM_PROMPT above has different wording
# for effective_from_text (it lacks the Step 6 narrowed clause-level
# instruction) -- the two are not the same prompt under two names, and
# must not share one version identifier. Bump this version if this
# module's _SYSTEM_PROMPT is ever edited.
from experiments.semantic_extraction.semantic_cache import CacheIdentity

CACHE_IDENTITY = CacheIdentity(
    model_identifier="gpt-4o-mini",
    prompt_version="openai-semantic-v1",
    extraction_schema_version="candidate-v1",
)


def build_openai_call_llm(model: str = "gpt-4o-mini"):
    """Returns a call_llm function (str -> str) backed by a real OpenAI
    chat completion call. Raises on any API-level failure (network,
    auth, rate limit, non-2xx) -- semantic_extract.py's extract_semantic()
    already catches this and maps it to SemanticStatus.UNAVAILABLE with
    retries, per the design's section 2.6.
    """
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set. This "
            "experiment does not hardcode or store any API key -- set "
            "it in your shell before running: export OPENAI_API_KEY=..."
        )

    client = OpenAI(api_key=api_key)

    def call_llm(raw_text: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI response had no content.")
        return _unwrap_json_array(content)

    return call_llm


def _unwrap_json_array(content: str) -> str:
    """OpenAI's response_format={"type": "json_object"} requires the
    model to return a JSON *object*, not a bare array -- some models
    will wrap the array in a key like {"claims": [...]}  or
    {"result": [...]} despite the system prompt asking for a bare
    array. This unwraps the first list-valued key found, so
    semantic_extract.py's parser (which expects a bare JSON array,
    per the design's candidate shape) still works regardless of how
    the model chose to wrap it.

    If the content is already a bare array, it's returned unchanged.
    If no list is found anywhere, the raw content is returned as-is --
    semantic_extract.py's _parse_response will then correctly classify
    it as MALFORMED_RESPONSE rather than this function silently
    guessing.
    """
    import json

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content

    if isinstance(parsed, list):
        return content

    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, list):
                return json.dumps(value)

    return content
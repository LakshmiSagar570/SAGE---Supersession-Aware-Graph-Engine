# experiments/semantic_extraction/nvidia_client.py
"""
NVIDIA NIM-backed implementation of the call_llm function
run_experiment.py's build_call_llm() needs to return.

NVIDIA's build.nvidia.com catalog exposes free-tier, OpenAI-compatible
endpoints -- same request/response shape as OpenAI's API, different
base_url, different API key format (nvapi-...), different model names.
Uses the same `openai` Python package (NVIDIA's endpoint is a drop-in
target for it), so no new dependency beyond what openai_client.py
already needed.

Usage:
    1. Sign up at https://build.nvidia.com, generate an API key
       (starts with "nvapi-").
    2. export NVIDIA_API_KEY=nvapi-...
    3. pip install openai   (if not already installed)
    4. In run_experiment.py:

        from experiments.semantic_extraction.nvidia_client import build_nvidia_call_llm

        def build_call_llm() -> LLMCallFn:
            return build_nvidia_call_llm()

Model default is "meta/llama-3.2-11b-vision-instruct" -- the only model,
among 8 real candidates tried, that a real chat completion call
actually succeeded against for this account. Note that /v1/models
listing a model ID does NOT guarantee your specific account/key has
call access to it -- NVIDIA's NIM catalog appears to scope access per
account even for models that show up in the general list. If you want
to try a different model, verify it works with a real call first
(a one-line "Say OK" completion is enough) rather than assuming
presence in models.list() means it's callable.

This is a vision-instruct model -- built for multimodal (image+text)
input -- but should function as a normal text-only instruct model for
this experiment's purposes. It is not necessarily the ideal model for
this task, just the one confirmed actually accessible; if a better
text-only model becomes available on this account later, swap it in
after confirming it with a real call the same way.

IMPORTANT CAVEAT, unlike openai_client.py: not every NIM-hosted model
reliably honors response_format={"type": "json_object"} the way
OpenAI's own models do -- support depends on the underlying model
server. This module still requests it (harmless if ignored), but does
NOT assume it worked. semantic_extract.py's _parse_response already
handles a response that isn't valid/expected JSON by classifying it as
MALFORMED_RESPONSE rather than crashing -- so an NIM model that ignores
the JSON instruction will show up as a real, visible experiment result
(a malformed-response rate), not a silent failure.
"""

from __future__ import annotations

import os

_SYSTEM_PROMPT = """You are a fact-extraction tool. You will be given a short excerpt of real text (often from a company's SEC filing). Your job is to identify factual claims explicitly stated in the text -- do not infer, guess, or add information that isn't directly written.

For each claim you find, return an object with these exact fields:
- "subject": the entity the claim is about (a person or company name, as written in the text)
- "predicate": a short phrase describing the relationship (e.g. "is headquartered in", "is the chief executive officer of", "was appointed Chief Financial Officer of", "was founded on")
- "object": the value of the claim (a place, a company name, a date, etc., as written in the text)
- "effective_from_text": the exact date phrase as written (e.g. "January 1, 2014" or "2014-01-01"), ONLY if the source text explicitly associates that date with THIS SPECIFIC claim -- the date must appear in the same clause or sentence as the claim itself, describing when THIS claim's event happened, not a date belonging to a different clause, a different sentence, or a different claim nearby. For example, in "The company was founded in 1980, and in 2024 the board appointed a new CFO", 1980 belongs ONLY to the founding claim and 2024 belongs ONLY to the CFO appointment claim -- never attach one claim's date to a different claim. If the text does not explicitly tie a date to this specific claim, use null. A null value here is expected and correct when no such date exists; do not guess or infer a date from context.
- "llm_confidence": your own estimate, from 0.0 to 1.0, of how confident you are that this is a correctly and completely extracted claim
- "source_span": the EXACT, VERBATIM substring of the input text that this claim was extracted from. This must be copied character-for-character from the input -- do not paraphrase, summarize, or lightly edit it. If you cannot produce an exact substring, do not include the claim.

Respond with ONLY a JSON array of these objects, and nothing else -- no explanation, no markdown code fences, no text before or after the array. If the text contains no such claims, respond with exactly: []"""


def build_nvidia_call_llm(model: str = "meta/llama-3.2-11b-vision-instruct"):
    """Returns a call_llm function (str -> str) backed by a real NVIDIA
    NIM chat completion call. Raises on any API-level failure (network,
    auth, rate limit, non-2xx) -- semantic_extract.py's extract_semantic()
    already catches this and maps it to SemanticStatus.UNAVAILABLE with
    retries, per the design's section 2.6.
    """
    from openai import OpenAI

    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY environment variable is not set. This "
            "experiment does not hardcode or store any API key -- set "
            "it in your shell before running: export NVIDIA_API_KEY=nvapi-..."
        )

    client = OpenAI(
        api_key=api_key,
        base_url="https://integrate.api.nvidia.com/v1",
    )

    def call_llm(raw_text: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
            temperature=0,
            max_tokens=2048,
            # NOTE: unlike openai_client.py, response_format is NOT
            # passed here -- NIM model support for it is inconsistent
            # across the catalog, and requesting an unsupported
            # response_format can itself cause a hard API error on some
            # models rather than being silently ignored. The system
            # prompt's explicit JSON instruction carries the real
            # weight of getting well-formed output; _strip_markdown_fences
            # below handles the most common real-world deviation
            # (wrapping the array in a ```json fence).
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("NVIDIA NIM response had no content.")
        return _strip_markdown_fences(content)

    return call_llm


def _strip_markdown_fences(content: str) -> str:
    """Some NIM-hosted models wrap JSON output in markdown code fences
    (```json ... ```) despite being told not to. This strips that
    wrapping if present. If no fences are present, content is returned
    unchanged. This does not attempt any other repair -- genuinely
    malformed output still reaches semantic_extract.py's parser
    unmodified, where it is correctly classified as
    MALFORMED_RESPONSE rather than this function guessing further.
    """
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Drop the opening fence line (``` or ```json) and, if present,
        # a trailing ``` fence line.
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return content
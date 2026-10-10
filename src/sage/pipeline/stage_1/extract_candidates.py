# src/sage/pipeline/stage_1/extract_candidates.py
"""
Stage 1 -- RULE extraction expressed as ExtractionCandidates.

Phase 4C Step 2, implementing PHASE4B_PRODUCTION_CONTRACT.md section 1.2.

Under the locked hybrid architecture (Phase 4A), RULE and SEMANTIC
candidates feed the SAME deterministic validation layer before either
can become a Fact. extract() returns finished Facts and never exposes
the regex match, so it cannot feed that layer. This module is the
sibling entry point that does the same matching but stops one step
earlier, returning ExtractionCandidate objects (origin=RULE).

What this module deliberately does NOT do:
    - It does NOT call extract(). It runs its own matching loop, per
      Phase 4B section 1.2. extract() is behaviorally unchanged.
    - It does NOT redefine the patterns. PATTERNS is imported from
      extract.py (the one visibility-only change Phase 4B permits),
      so the two paths cannot drift apart on what a claim shape is.
    - It does NOT validate, parse dates, or build Facts. That is the
      shared wrapper's job (candidate.validate_and_build_fact), applied
      identically to RULE and SEMANTIC candidates.
    - It does NOT improve any pattern. The compound-sentence object
      corruption documented in EDGAR_BASELINE_FINDINGS.md is
      reproduced faithfully on purpose: this path must reproduce
      RULE's frozen behavior exactly, defects included.

Accepted duplication (Phase 4B section 1.2): the few lines that derive
predicate and object from a match repeat logic in extract.py's private
_parse_claim_sentence, which returns no match object and so cannot be
reused for source_span. The cross-check tests in
tests/unit/test_extract_candidates.py are the drift guard: they assert
this module agrees with extract() field-for-field on the same input.

source_span == the stripped input line. Every pattern is anchored with
^...$, so match.group(0) is always the whole sentence -- the same text
extract() stores in Fact.evidence. source_span verification against
raw_text (validate_and_build_fact) therefore always passes for RULE
candidates. As with every candidate, that check proves provenance only,
never that the extracted subject/predicate/object are correct.

effective_from_text is the RAW date text captured by the pattern (e.g.
"2025-03-01"), unparsed. The shared wrapper parses it, so RULE and
SEMANTIC share one date path (Phase 4B section 2.2).

NOTE on one known divergence from extract(): for a date that matches
the regex shape but is not a real calendar date (e.g. "2020-13-45"),
extract() raises ValueError, while the shared wrapper's parser falls
back to extracted_at. See the Phase 4C Step 2 report; not changed here.
"""

from __future__ import annotations

from experiments.semantic_extraction.candidate import (
    ExtractionCandidate,
    ExtractionOrigin,
)
from sage.pipeline.stage_1.extract import PATTERNS


def extract_as_candidates(raw_text: str) -> list[ExtractionCandidate]:
    """Run RULE's frozen patterns over raw_text, returning candidates.

    Mirrors extract()'s traversal exactly: one line at a time, each line
    stripped, blank lines skipped, at most one candidate per line (the
    first matching pattern wins, so pattern order in PATTERNS matters
    exactly as it does in extract()).
    """
    candidates: list[ExtractionCandidate] = []
    for line in raw_text.splitlines():
        sentence = line.strip()
        if not sentence:
            continue

        candidate = _match_sentence(sentence)
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def _match_sentence(sentence: str) -> ExtractionCandidate | None:
    """Return a RULE candidate for `sentence`, or None if no pattern matches."""
    for pattern, predicate_template in PATTERNS:
        match = pattern.match(sentence)
        if match is None:
            continue

        groups = match.groupdict()

        predicate = predicate_template.format(role=groups.get("role", ""))
        explicit_date = groups.get("date")

        # For "was founded on DATE", the date is both the temporal
        # anchor and the object of the triple -- same special case as
        # extract.py's _parse_claim_sentence.
        if predicate == "was founded on":
            obj = groups["date"] or ""
        else:
            obj = groups.get("object") or ""

        return ExtractionCandidate(
            subject=groups["subject"],
            predicate=predicate,
            object=obj,
            effective_from_text=explicit_date,
            llm_confidence=None,
            source_span=match.group(0),
            origin=ExtractionOrigin.RULE,
        )

    return None
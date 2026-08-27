"""
src/sage/pipeline/stage_1/extract.py

Stage 1 extraction: turns raw usable text into Fact[].

Deliberately rule-based for v0.1, not LLM or NLP-pipeline based:
deterministic (same input always produces identical output), zero new
dependencies, and directly testable. This is intentionally narrow --
it recognizes only the claim shapes present in the v0.1 fixture and
will not generalize to arbitrary prose. Broader extraction is future
work building on top of a proven pattern, not something this module
should try to anticipate.

TEMPORAL BOUNDARY (locked in review, corrected from an earlier draft):
  effective_from is derived ONLY from an explicit date stated within
  the claim sentence itself. If no such date is present, effective_from
  falls back to extracted_at -- meaning "SAGE became aware of this
  claim at this moment", NOT a guess about when the underlying fact
  became true.

  Document-level metadata (e.g. a "Generated:" date) is NEVER used as
  an effective_from fallback. A document's generation date describes
  provenance, not the temporal validity of the claims it contains --
  conflating the two would let Stage 1 fabricate temporal semantics
  that are properly Stage 2's responsibility (Stage 2 exists
  specifically to perform temporal reasoning; Stage 1 must not
  pre-empt it with an unstated guess dressed as a derived value).

This module does not resolve, merge, or compare facts against each
other (e.g. the two CEO claims for the same role at different times
remain two independent Fact objects here) -- that is Stage 3's
responsibility, not Stage 1's.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from contracts.fact_schema import Fact, FactID, FactStatus, Source

# from contracts.fact_schema import Fact, FactID, FactStatus, Source, SourceID, SourceType

# One matcher per claim shape present in the v0.1 fixture. Each pattern
# captures (subject, predicate_literal, object[, date]) as applicable.
# Order matters: more specific patterns (with a role + date) must be
# tried before their more general counterparts.

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"^(?P<subject>.+?) was appointed (?P<role>.+?) of "
            r"(?P<object>.+?) on (?P<date>\d{4}-\d{2}-\d{2})\.$"
        ),
        "was appointed {role} of",
    ),
    (
        re.compile(
            r"^(?P<subject>.+?) was founded on "
            r"(?P<date>\d{4}-\d{2}-\d{2})\.$"
        ),
        "was founded on",
    ),
    (
        re.compile(
            r"^(?P<subject>.+?) is headquartered in "
            r"(?P<object>.+?)\.$"
        ),
        "is headquartered in",
    ),
    (
        re.compile(
            r"^(?P<subject>.+?) is the (?P<role>.+?) of "
            r"(?P<object>.+?)\.$"
        ),
        "is the {role} of",
    ),
]


def _parse_claim_sentence(
    sentence: str,
) -> tuple[str, str, str, str | None] | None:
    """
    Attempt to match `sentence` against known claim patterns.

    Returns:
        (subject, predicate, object, explicit_date_or_none)

    or None if the sentence does not match a known claim shape.
    """
    for pattern, predicate_template in _PATTERNS:
        match = pattern.match(sentence)

        if not match:
            continue

        groups = match.groupdict()

        subject = groups["subject"]
        predicate = predicate_template.format(
            role=groups.get("role", "")
        )

        # For "was founded on DATE", the date is both:
        #   - the explicit temporal anchor
        #   - the object of the semantic triple.
        if predicate == "was founded on":
            obj = groups["date"] or ""
        else:
            obj = groups.get("object") or ""

        explicit_date = groups.get("date")

        return subject, predicate, obj, explicit_date

    return None


def extract(raw_text: str, document_source: Source) -> list[Fact]:
    """
    Extract Fact objects from raw plain-text document content.

    document_source is the Source (already carrying source_id, name,
    source_type, locator) that every extracted Fact will cite as its
    provenance. Building the Source is the caller's (stage.py's)
    responsibility, not this function's -- extraction only decides
    WHAT was claimed, not how the document itself is identified.
    """
    facts: list[Fact] = []
    extracted_at = datetime.now(UTC)
    for line in raw_text.splitlines():
        sentence = line.strip()
        if not sentence:
            continue

        parsed = _parse_claim_sentence(sentence)
        if parsed is None:
            # Not a recognized claim shape (title, header, blank, etc.)
            # -- correctly skipped rather than forced into a fact.
            continue

        subject, predicate, obj, explicit_date = parsed

        if explicit_date is not None:
            effective_from = datetime.strptime(
                explicit_date, "%Y-%m-%d"
            ).replace(tzinfo=UTC)
        else:
            effective_from = extracted_at

        facts.append(
            Fact(
                fact_id=FactID(str(uuid4())),
                subject=subject,
                predicate=predicate,
                object=obj,
                source=document_source,
                evidence=sentence,
                extracted_at=extracted_at,
                effective_from=effective_from,
                effective_to=None,
                confidence=1.0,
                status=FactStatus.DISCOVERED,
                metadata={},
            )
        )

    return facts
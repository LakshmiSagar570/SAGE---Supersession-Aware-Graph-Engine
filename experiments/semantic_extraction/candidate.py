# experiments/semantic_extraction/candidate.py
"""
Phase 2 semantic-extraction experiment -- candidate model and
deterministic validation.

Deliberately isolated from src/sage/pipeline/: this is an experiment,
not a new permanent SAGE stage. Nothing here imports from or writes to
contracts/fact_schema.py, contracts/stage_io.py, or any Stage 1-6
module in a way that changes their behavior. The one import from the
real codebase (contracts.fact_schema.Fact) is read-only -- this module
constructs Fact instances using the existing, unmodified contract, the
same way stage_1/extract.py already does for RULE-origin facts.

Implements SEMANTIC_EXTRACTION_DESIGN.md sections 2.2 (candidate shape),
2.3 (source_span verification), 2.5 (rejection categories), and 2.7
(wrapper -- Fact construction, WITHOUT writing llm_confidence into
Fact.confidence).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from contracts.fact_schema import Fact, FactID, FactStatus, Source


class ExtractionOrigin(str, Enum):
    """Which extractor produced a candidate (Phase 4B section 1).

    Required on every ExtractionCandidate so that RULE- and SEMANTIC-
    origin candidates can share one validation path while remaining
    distinguishable for audit logging. It never becomes part of Fact
    (Phase 4B section 9): once a candidate is a Fact, downstream stages
    cannot tell which extractor produced it.
    """

    RULE = "RULE"
    SEMANTIC = "SEMANTIC"


class ExtractionCandidate(BaseModel):
    """One claim the semantic extractor believes a document expresses.

    Never persisted, never passed to Stage 2+. Consumed only by the
    deterministic wrapper (validate_and_build_fact, below) that
    converts a validated candidate into a real Fact.

    Per the accepted design (section 2.2), claim_type is deliberately NOT
    included here -- whether the wrapper needs it to normalize a
    candidate deterministically is a question this experiment's real
    output should inform, not a decision made in advance.
    """

    subject: str
    predicate: str
    object: str
    effective_from_text: str | None = None
    llm_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "LLM's own self-reported value. EXPERIMENTAL METADATA ONLY. "
            "Never treated as a calibrated probability, and never mapped "
            "onto Fact.confidence -- see design doc sections 2.4 and 2.7. "
            "None for RULE-origin candidates (Phase 4B section 1): a "
            "rule match has no model-reported confidence."
        ),
    )
    source_span: str = Field(
        description=(
            "Exact substring of the input document this candidate was "
            "derived from. Verified against the real input by "
            "validate_and_build_fact before a Fact is ever constructed."
        )
    )
    origin: ExtractionOrigin = Field(
        description=(
            "Which extractor produced this candidate. Required, no "
            "default (Phase 4B section 1). Audit/validation metadata "
            "only -- never copied into Fact or Fact.metadata."
        ),
    )


class RejectionReason(str, Enum):
    """Per design section 2.5 -- kept distinct so analysis never
    conflates different failure types with each other or with a
    legitimate zero-candidate result (section 2.6)."""

    UNVERIFIABLE_SOURCE_SPAN = "UNVERIFIABLE_SOURCE_SPAN"
    EMPTY_REQUIRED_FIELD = "EMPTY_REQUIRED_FIELD"
    # Locked in Phase 4A, specified in Phase 4B section 5:
    SUBJECT_EQUALS_OBJECT = "SUBJECT_EQUALS_OBJECT"
    BARE_COPULA_PREDICATE = "BARE_COPULA_PREDICATE"


# Phase 4B section 5, check 4. The predicate, after .strip().lower(), must
# not be exactly one of these. This is deliberately the ENTIRE rule: it
# targets predicates that are nothing but a copula ("its executive team"
# -- "is" -- "a key personnel"). It does not attempt general
# fragmentary-claim detection, which Phase 4A left explicitly open.
_BARE_COPULA_PREDICATES = frozenset({"is", "are", "was", "were"})


# Phase 4B section 3 / Phase 4C Step 7: SEMANTIC predicate normalization.
#
# EXACTLY ONE entry, by design. An entry belongs here only if a person has
# confirmed the SEMANTIC phrasing asserts the IDENTICAL real-world claim as
# an existing RULE predicate -- not a related or topically similar one.
#
# Two mappings were proposed in an earlier 4B draft and REJECTED as wrong
# (not merely imprecise). They must NOT be reintroduced:
#     "is located in"      -> "is headquartered in"   (different claims: a
#         company can have many locations but one headquarters)
#     "was incorporated in" -> "was founded on"       (different events:
#         legal incorporation is not the same as founding)
# Matching is exact string equality (no case-folding, no stripping):
# unrecognized predicates pass through UNCHANGED.
#
# Applied ONLY at SEMANTIC candidate construction time
# (semantic_extract._parse_response), never inside validate_and_build_fact,
# which must stay origin-agnostic (Phase 4A/4B).
_PREDICATE_NORMALIZATION_MAP: dict[str, str] = {
    "has been appointed chief financial officer of": (
        "was appointed Chief Financial Officer of"
    ),
}


def normalize_semantic_predicate(predicate: str) -> str:
    """Return the canonical predicate for a SEMANTIC-origin candidate, or
    `predicate` itself, unchanged, if it is not in the locked table."""
    return _PREDICATE_NORMALIZATION_MAP.get(predicate, predicate)


class CandidateResult(BaseModel):
    """The outcome of validating one ExtractionCandidate: either a real
    Fact was constructed, or it was rejected with a specific reason.
    Exactly one of fact / rejection_reason is set."""

    model_config = {"arbitrary_types_allowed": True}

    candidate: ExtractionCandidate
    fact: Fact | None = None
    rejection_reason: RejectionReason | None = None


def validate_and_build_fact(
    candidate: ExtractionCandidate,
    raw_text: str,
    source: Source,
) -> CandidateResult:
    """Deterministic wrapper: validates one candidate against the real
    source document and, if valid, builds a real Fact from it.

    Checks run in this order, and the first failure wins (Phase 4B
    section 5); later checks are not evaluated once one fails:
        1. required fields non-empty      -> EMPTY_REQUIRED_FIELD
        2. source_span found in raw_text  -> UNVERIFIABLE_SOURCE_SPAN
        3. subject != object              -> SUBJECT_EQUALS_OBJECT
        4. predicate is not a bare copula -> BARE_COPULA_PREDICATE
    Every check applies identically to RULE- and SEMANTIC-origin
    candidates. Nothing in this function reads candidate.origin, on
    purpose: once a candidate is a Fact, downstream stages must not be
    able to tell which extractor produced it (Phase 4A/4B).

    Per design section 2.3: source_span verification against raw_text is
    mandatory, not advisory. A candidate whose span cannot be found
    verbatim in the source is rejected outright -- never fuzzy-matched,
    never trimmed, never silently accepted.

    Per design section 2.7: Fact.confidence is set the same way it
    already is for every other Fact in the frozen contract. This
    function does NOT write llm_confidence into Fact.confidence --
    that value stays on the candidate itself, retrievable by the
    caller (see run_experiment.py) as experimental metadata keyed by
    the constructed Fact's fact_id, never inside the Fact.
    """
    # Phase 4C Step 4b: source_span belongs in the SAME required-field
    # check as subject/predicate/object (4B section 5, check 1: "subject,
    # predicate, object, and source_span must all be non-empty strings
    # after stripping whitespace"). Before this fix, an empty or
    # whitespace-only source_span passed both this check and the
    # containment check below ("" is trivially "in" any string), so a
    # candidate with zero real grounding in the document could still
    # become a Fact. This closes that gap; it is a correction to the
    # validation contract as already specified, not a new rule.
    if (
        not candidate.subject.strip()
        or not candidate.predicate.strip()
        or not candidate.object.strip()
        or not candidate.source_span.strip()
    ):
        return CandidateResult(
            candidate=candidate,
            rejection_reason=RejectionReason.EMPTY_REQUIRED_FIELD,
        )

    if candidate.source_span not in raw_text:
        # Mandatory, exact substring containment. No fuzzy matching --
        # see design section 2.3's explicit reasoning for why this must
        # not be relaxed.
        return CandidateResult(
            candidate=candidate,
            rejection_reason=RejectionReason.UNVERIFIABLE_SOURCE_SPAN,
        )

    # Passing the span check proves provenance only -- that this text
    # really exists in the document -- never that subject/predicate/
    # object correctly describe it (Phase 4B section 5, check 2 caveat).
    # The two checks below are the deterministic guards against the two
    # concrete content failures Phase 2 observed despite valid spans.

    # Exact string match after .strip() -- deliberately NOT case-folded
    # (Phase 4B section 5, check 3). Real case: "David Stoll" --
    # "replacing" -- "David Stoll" (SEMANTIC_EXTRACTION_RESULTS.md 3.6).
    if candidate.subject.strip() == candidate.object.strip():
        return CandidateResult(
            candidate=candidate,
            rejection_reason=RejectionReason.SUBJECT_EQUALS_OBJECT,
        )

    if candidate.predicate.strip().lower() in _BARE_COPULA_PREDICATES:
        return CandidateResult(
            candidate=candidate,
            rejection_reason=RejectionReason.BARE_COPULA_PREDICATE,
        )

    now = datetime.now(UTC)
    effective_from = _parse_effective_from(candidate.effective_from_text, fallback=now)

    fact = Fact(
        fact_id=FactID(str(uuid4())),
        subject=candidate.subject,
        predicate=candidate.predicate,
        object=candidate.object,
        source=source,
        evidence=candidate.source_span,
        extracted_at=now,
        effective_from=effective_from,
        effective_to=None,
        # Fact.confidence is set to the frozen contract's existing
        # default/meaning, exactly as RULE-origin facts already do in
        # stage_1/extract.py (confirmed: RULE facts hardcode 1.0).
        # llm_confidence is NOT written here -- see docstring above and
        # design section 2.7.
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )

    return CandidateResult(candidate=candidate, fact=fact)


def _parse_effective_from(text: str | None, *, fallback: datetime) -> datetime:
    """Deterministic date parsing -- NOT the LLM's job (design section
    2.2's explicit reasoning: date parsing is verifiable and
    non-semantic, so it belongs in the wrapper, not the model).

    Deliberately minimal for this experiment: attempts a small set of
    common explicit formats seen in the real EDGAR fixtures
    (e.g. "January 1, 2014", "2014-01-01"). Falls back to `fallback`
    (extracted_at) on any parse failure -- identical fallback semantics
    to RULE-origin facts with no explicit date, so SEMANTIC-origin facts
    don't get a different temporal contract than RULE-origin ones.
    """
    if not text:
        return fallback

    candidate_formats = ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%Y"]
    cleaned = text.strip().rstrip(".")
    for fmt in candidate_formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if fmt == "%Y":
            # Phase 4B section 4 / Phase 4C Step 8 -- PRECISION-LOSS
            # CONVENTION, not a precise date. A year-only expression
            # (e.g. "1975") is represented internally as January 1 of
            # that year SOLELY because Fact.effective_from is typed as
            # a datetime and requires a full date. This does NOT assert
            # the underlying event occurred on January 1st -- it
            # asserts only that the year is known and the exact day is
            # not. Any code or person reading effective_from for a fact
            # derived this way must not treat the month/day portion as
            # a real, known fact about when the event occurred.
            pass
        return parsed.replace(tzinfo=UTC)

    return fallback

"""
contracts/fact_schema.py

SAGE v0.1 FACT contract.

This file defines the canonical data structures that move across every
stage boundary in the SAGE pipeline. It contains NO stage logic, NO
inference logic, and NO persistence (Neo4j) code.

Governing principle (locked in project discussion):
    Every stage may enrich or transform pipeline data, but it cannot
    silently change the meaning or structure of a FACT. Supersession
    (and any other disposition of a fact -- rejection, contest, etc.)
    is represented explicitly through Resolution, never as an implicit
    or silent operation performed on a Fact itself.

Layer separation (locked):
    Fact                 -> what was observed/extracted (Stage 1, enriched by Stage 2)
    ContradictionSet      -> what Stage 3 discovered about relationships between facts
    AuthorityAssessment   -> what Stage 4 determined about source authority
    Resolution            -> what Stage 5 decided
    (Graph writer persists these decisions in Stage 6; it does not make them.)

Any change to the shape of these models MUST be recorded in
contracts/CONTRACT_CHANGELOG.md. Agents implementing stage logic must not
redefine these types locally.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import NewType, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Identifiers
#
# Distinct NewType wrappers, not bare str. This lets static analysis
# (mypy) catch a fact_id being passed where a source_id (or
# contradiction_id, etc.) is expected.
#
# IMPORTANT: NewType is a STATIC typing construct only. It creates no
# runtime distinction whatsoever -- FactID("abc") == "abc" is True, and
# Pydantic will not stop a SourceID from being passed where a FactID is
# expected at runtime. The actual protection here comes from mypy
# checking, test coverage, semantic naming, and contract discipline
# between agents -- not from any runtime enforcement in this file.
# ---------------------------------------------------------------------------

FactID = NewType("FactID", str)
SourceID = NewType("SourceID", str)
ContradictionID = NewType("ContradictionID", str)
ResolutionID = NewType("ResolutionID", str)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FactStatus(str, Enum):
    """
    Lifecycle / epistemic state of a Fact.

    Locked transition model:

        DISCOVERED
            |
            v
          VALID  <----------------+
            |                     |
            +--> CONTESTED -------+
            |         |
            |         v
            |    (Stage 4 authority + Stage 5 resolution)
            |         |
            v         v
       SUPERSEDED   REJECTED

    DISCOVERED and VALID are lifecycle states (has this been evaluated).
    CONTESTED is an epistemic condition (live disagreement exists).
    SUPERSEDED and REJECTED are resolution outcomes.
    These are intentionally kept in one enum for v0.1 simplicity, but the
    conceptual distinction is documented here and must be respected by
    stage implementations: a stage may not, for example, move a Fact
    directly from DISCOVERED to SUPERSEDED without passing through VALID
    or CONTESTED.
    """

    DISCOVERED = "DISCOVERED"
    VALID = "VALID"
    CONTESTED = "CONTESTED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class SourceType(str, Enum):
    """
    Category of a Source.

    NOTE: only the existence of a structured Source was locked in prior
    design discussion -- these specific five categories are a v0.1
    addition and must be recorded as such in CONTRACT_CHANGELOG.md, not
    treated as having been agreed independently. Extend via a documented
    contract change, not silently.
    """

    DOCUMENT = "DOCUMENT"
    DATABASE = "DATABASE"
    API = "API"
    WEB = "WEB"
    OTHER = "OTHER"


class ConflictType(str, Enum):
    """
    Category of contradiction detected by Stage 3.

    v0.1 starts with two mechanisms. Additional conflict types must be
    added through a documented contract change, not invented ad hoc by
    a stage implementation.
    """

    DIRECT = "DIRECT"
    TEMPORAL_OVERLAP = "TEMPORAL_OVERLAP"


class ResolutionOutcome(str, Enum):
    """What Stage 5 decided about a contested set of facts."""

    WINNER_SELECTED = "WINNER_SELECTED"
    UNRESOLVED = "UNRESOLVED"
    ALL_REJECTED = "ALL_REJECTED"


# ---------------------------------------------------------------------------
# Source
#
# Deliberately does NOT contain an authority score. Stage 1 (ingestion)
# cannot know how authoritative a source is -- that determination belongs
# to Stage 4 and is recorded separately in AuthorityAssessment. Keeping
# these concerns apart means Stage 4 produces new information rather than
# mutating something an earlier stage already wrote.
# ---------------------------------------------------------------------------


class Source(BaseModel):
    source_id: SourceID
    name: str
    source_type: SourceType
    locator: Optional[str] = Field(
        default=None,
        description="Optional URI/path/reference to the source origin.",
    )


# ---------------------------------------------------------------------------
# Fact
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    """
    The canonical unit that moves through the SAGE pipeline.

    Structural note: this model intentionally has NO `supersedes` /
    `superseded_by` fields. Supersession is a relationship Stage 5 decides
    and records in a separate Resolution object -- it is not intrinsic
    content a Fact carries about itself.
    """

    fact_id: FactID

    # --- claim ---
    subject: str
    predicate: str
    object: str

    # --- provenance ---
    source: Source
    evidence: Optional[str] = Field(
        default=None,
        description="Supporting evidence text/reference for this claim.",
    )

    # --- temporal ---
    # extracted_at: when SAGE learned this fact.
    # effective_from / effective_to: when the fact was/is actually true.
    # These are NOT the same thing -- a document from 2020 can state
    # something that was true in 2015. Stage 3 contradiction detection
    # depends on this distinction to avoid flagging facts that were both
    # true, just at different times, as contradictory.
    extracted_at: datetime
    effective_from: datetime
    effective_to: Optional[datetime] = Field(
        default=None,
        description="Null if the fact is still current / has no known end.",
    )

    # --- epistemic state ---
    confidence: float = Field(ge=0.0, le=1.0)
    status: FactStatus = FactStatus.DISCOVERED

    # --- metadata ---
    # Auxiliary information only. metadata MUST NOT be used to smuggle
    # in undeclared contract fields -- e.g. fact.metadata["authority_score"]
    # is a contract violation, since authority belongs exclusively in
    # AuthorityAssessment. If a stage needs a new structured field, that
    # goes through a documented contract change, not into this dict.
    metadata: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ContradictionSet
#
# Stage 3 output. Groups the specific facts that conflict with each other.
# A stage MUST NOT simply flag individual Facts with a boolean -- that
# would discard the grouping information Stage 4 depends on to know which
# facts are competing against which, particularly when a single Stage 3
# pass surfaces multiple, unrelated contradictions in one batch.
# ---------------------------------------------------------------------------


class ContradictionSet(BaseModel):
    """
    Documented invariant (not yet enforced by Pydantic, pending a
    uniqueness-aware validator in tests/unit):
        conflicting_fact_ids must contain at least two DISTINCT FactIDs.
        A ContradictionSet with fewer than two facts, or with a duplicate
        ID, is not a valid contradiction.
    """

    contradiction_id: ContradictionID
    conflicting_fact_ids: list[FactID]
    conflict_type: ConflictType
    detected_at: datetime


# ---------------------------------------------------------------------------
# AuthorityAssessment
#
# Stage 4 output. Kept separate from Source itself so that Stage 1
# ingestion is never required to populate a value it cannot actually know.
# ---------------------------------------------------------------------------


class AuthorityAssessment(BaseModel):
    source_id: SourceID
    authority_score: float = Field(ge=0.0, le=1.0)
    rationale: Optional[str] = None
    assessed_at: datetime


# ---------------------------------------------------------------------------
# Resolution
#
# Stage 5 output. Represents ONE coherent resolution decision -- not an
# arbitrary batch of unrelated facts. superseded_fact_ids is plural by
# design: a single more-authoritative fact may supersede several earlier
# facts about the same subject in one resolution event. This plurality is
# NOT license for a stage to dump unrelated facts into one Resolution;
# that constraint is conceptual and must be respected by Stage 5's
# implementation, since it cannot be enforced structurally here.
# ---------------------------------------------------------------------------


class Resolution(BaseModel):
    resolution_id: ResolutionID
    outcome: ResolutionOutcome
    winning_fact_id: Optional[FactID] = Field(
        default=None,
        description="Null when outcome is UNRESOLVED or ALL_REJECTED.",
    )
    superseded_fact_ids: list[FactID] = Field(default_factory=list)
    rationale: str
    resolved_at: datetime
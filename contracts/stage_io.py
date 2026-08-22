"""
contracts/stage_io.py

SAGE v0.1 stage input/output contract.

This file defines the explicit input and output shape for each of the six
SAGE pipeline stages. It contains NO stage logic, NO inference logic, and
NO persistence (Neo4j) code -- exactly the same boundary fact_schema.py
holds for the FACT contract itself.

Design decisions locked in project discussion:

1. Explicit named models per stage, not a generic StageInput[T]/
   StageOutput[T]. Codex/Antigravity debugging a live failure should be
   able to open this file and read a stage's contract directly, without
   tracing through a generic definition elsewhere.

2. Downstream stages receive FULL CUMULATIVE CONTEXT, not merely the
   object the immediately preceding stage produced. Stage 5, for example,
   needs to trace a Resolution back through the ContradictionSet that
   prompted it and the Facts actually in conflict -- reducing each
   stage's input to "only the newest object" would force stages to
   either re-derive context they already had, or force earlier stages
   to guess what might be needed later and over-bundle. Each stage's
   *Output model therefore repeats everything its *Input model held,
   plus whatever that stage newly produced.

3. Collections are `list[...]`, not `tuple[...]`. These are pipeline
   batches under active construction/enrichment; nothing about their
   use case argues for immutability in v0.1.

4. Stage 2 mutation policy (which Fact fields Stage 2 may change vs.
   must preserve) is NOT encoded here. This file defines WHAT enters
   and leaves each stage; tests/unit/ defines WHAT each stage is
   permitted to change. Encoding per-stage mutation policy into this
   file would couple a structural contract to implementation policy.

5. Stage 6 output is deliberately NOT fully defined yet. Its eventual
   shape (facts_written, errors, etc.) depends on the actual Neo4j
   persistence implementation, which does not exist yet. Only
   Stage6Input is defined now -- inventing an output schema against
   code that doesn't exist yet is exactly the mistake the foundation
   work earlier in this project existed to avoid repeating.

Any change to the shape of these models MUST be recorded in
contracts/CONTRACT_CHANGELOG.md. Agents implementing stage logic must
not redefine these types locally.
"""

from __future__ import annotations

from pydantic import BaseModel

from contracts.fact_schema import (
    AuthorityAssessment,
    ContradictionSet,
    Fact,
    Resolution,
)

# ---------------------------------------------------------------------------
# Stage 1 -- Ingestion
#
# Input is deliberately left unopinionated: ingestion sources (documents,
# APIs, etc.) are not yet part of the locked contract. Stage 1 is the
# pipeline's entry point -- there is no upstream stage to receive
# structured input from.
# ---------------------------------------------------------------------------


class Stage1Input(BaseModel):
    """
    Stage 1 is the pipeline entry point -- there is no upstream stage to
    receive structured input from.

    PROVISIONAL: raw_source_reference is a placeholder entry-point
    reference, not a locked ingestion design. The concrete raw-ingestion
    representation (which sources SAGE supports, what payload shape they
    carry) has not been specified. This field exists so Stage 1 has a
    concrete signature to implement against; when actual ingestion
    sources are designed, changing this field is an expected and
    legitimate contract change, not a violation of it.
    """

    raw_source_reference: str


class Stage1Output(BaseModel):
    facts: list[Fact]


# ---------------------------------------------------------------------------
# Stage 2 -- Temporal Reasoning
#
# Fact[] in, Fact[] out. Which fields Stage 2 may change (effective_from,
# effective_to, temporal metadata) versus must preserve (fact_id, subject,
# predicate, object, source, evidence, extracted_at, confidence, status)
# is a behavioral invariant enforced in tests/unit/, not a type-level
# distinction encoded here. See module docstring, point 4.
# ---------------------------------------------------------------------------


class Stage2Input(BaseModel):
    facts: list[Fact]


class Stage2Output(BaseModel):
    facts: list[Fact]


# ---------------------------------------------------------------------------
# Stage 3 -- Contradiction Detection
#
# Stage 3's contract carries the existing Fact[] plus ContradictionSet[].
# Preservation of individual Fact fields across this boundary is a
# behavioral invariant, not something this Pydantic model itself
# enforces -- Stage3Output would validate identically whether Stage 3
# left facts untouched or silently rewrote them. Stage 3 does not
# receive prior AuthorityAssessment/Resolution context because none
# exists yet at this point in the pipeline.
# ---------------------------------------------------------------------------


class Stage3Input(BaseModel):
    facts: list[Fact]


class Stage3Output(BaseModel):
    facts: list[Fact]
    contradictions: list[ContradictionSet]


# ---------------------------------------------------------------------------
# Stage 4 -- Authority Inference
#
# Receives full context from Stage 3 (facts + contradictions), since
# authority inference must reason about which facts are actually
# competing, not just which sources exist in isolation.
# ---------------------------------------------------------------------------


class Stage4Input(BaseModel):
    facts: list[Fact]
    contradictions: list[ContradictionSet]


class Stage4Output(BaseModel):
    facts: list[Fact]
    contradictions: list[ContradictionSet]
    authority_assessments: list[AuthorityAssessment]


# ---------------------------------------------------------------------------
# Stage 5 -- Resolution
#
# Receives full context from Stage 4. Resolution must be traceable back
# through the authority assessments that informed it, the contradiction
# set that prompted it, and the specific facts in conflict.
# ---------------------------------------------------------------------------


class Stage5Input(BaseModel):
    facts: list[Fact]
    contradictions: list[ContradictionSet]
    authority_assessments: list[AuthorityAssessment]


class Stage5Output(BaseModel):
    facts: list[Fact]
    contradictions: list[ContradictionSet]
    authority_assessments: list[AuthorityAssessment]
    resolutions: list[Resolution]


# ---------------------------------------------------------------------------
# Stage 6 -- Graph / Evidence Writing
#
# Stage6Input carries everything Stage 5 produced, since the graph writer
# needs full context to persist facts, contradictions, authority
# assessments, and resolutions as a coherent graph -- not resolutions in
# isolation.
#
# Stage6Output is INTENTIONALLY NOT DEFINED YET. See module docstring,
# point 5. Do not add fields here speculatively; this gets designed
# against the real Neo4j persistence implementation when it exists.
# ---------------------------------------------------------------------------


class Stage6Input(BaseModel):
    facts: list[Fact]
    contradictions: list[ContradictionSet]
    authority_assessments: list[AuthorityAssessment]
    resolutions: list[Resolution]


# Stage6Output intentionally omitted -- to be defined against the actual
# Neo4j persistence implementation, not speculatively in advance of it.
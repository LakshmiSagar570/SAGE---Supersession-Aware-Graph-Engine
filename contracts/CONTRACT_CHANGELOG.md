SAGE v0.1 Contract Baseline
============================

- Canonical Fact model established.
- FactID, SourceID, ContradictionID, ResolutionID established as NewType identifiers.
- Source separated from AuthorityAssessment.
- Fact temporal fields established:
  effective_from, effective_to, extracted_at.
- Fact status vocabulary established.
- ContradictionSet established as Stage 3 output.
- ContradictionSet represents relationships between 2+ distinct facts conceptually.
- AuthorityAssessment established as Stage 4 output.
- Resolution established as Stage 5 output.
- superseded_fact_ids intentionally plural.
- Stage I/O uses explicit named models rather than generics.
- Stage outputs carry cumulative pipeline context.
- Stage 2 mutation policy is behavioral and tested, not encoded in stage_io.py.
- Stage 1 raw_source_reference is explicitly provisional.
- Stage 6 output is intentionally undefined until persistence implementation exists.
- Source has a source_type field (DOCUMENT/DATABASE/API/WEB/OTHER);
  these specific categories are a v0.1 addition, not part of earlier
  locked design, and were introduced during contract review.

- Fact temporal fields established: effective_from, effective_to,
  extracted_at -- separating when a fact was true from when SAGE
  learned it, so Stage 3 can distinguish facts that genuinely
  contradict from facts that were both true at different times.
- **Contract change**: `Stage1Input.raw_source_reference: str` (provisional,
  established in the original stage_io.py commit) has been replaced by
  a shared source envelope:
  `source_type: SourceType`, `reference: str`,
  `raw_payload: str | bytes | None = None`.
  Reason: the earlier single-field placeholder could not distinguish
  fetch-pending sources (e.g. a URL, where content must still be
  retrieved) from already-loaded sources (e.g. an API response or a
  read file, where content is already in hand). The new envelope
  reuses the existing SourceType enum from fact_schema.py rather than
  introducing a parallel one. Source-specific input contracts
  (DocumentInput, WebInput, etc.) were deliberately NOT added --
  extraction logic per source type is an implementation concern below
  this shared boundary, not part of the public stage contract.
  v0.1 implementation proves the pattern with DOCUMENT first; WEB,
  API, DATABASE, and OTHER extractors follow later against this same
  envelope.


## Stage6Output added (v0.1 — Stage 6 implementation pass)

**What changed:** `contracts/stage_io.py` gains a new type, `Stage6Output`,
which was previously and deliberately absent.

**Why it was absent before:** the contract's own prior comment stated
Stage6Output was "intentionally not defined yet" and would be "designed
against the real Neo4j persistence implementation when it exists." That
was a correct call at the time — defining an output type before any
persistence design work had started would have meant guessing at its
shape.

**Why it's being added now:** Stage 6's persistence implementation
(`materialize.py`, `neo4j_client.py`, `queries.py`) is now being built.
Per the same principle that held the type back before, it's appropriate
to define it now that real design work justifies a specific shape,
rather than continue deferring it indefinitely.

**The shape added:**

```python
class Stage6Output(BaseModel):
    facts_written: int
    sources_written: int
    contradictions_written: int
    authority_assessments_written: int
    resolutions_written: int
    status: Literal["COMMITTED"]
```

**Design rationale for this specific shape:**
- Deliberately an operational result (write counts + commit status), not
  a graph dump. No database objects, no Neo4j driver objects, and no
  internal transaction state are exposed — those are Stage 6
  implementation details, not contract surface.
- `status: Literal["COMMITTED"]` rather than a broader enum: a returned
  `Stage6Output` means the transaction succeeded. Failure is represented
  by an exception, not by a `status="FAILED"` value — there is no
  partial/failed `Stage6Output` to construct, which keeps "did Stage 6
  produce output" and "did the write succeed" the same question rather
  than two things that could disagree.

**What did NOT change:** `Fact`, `Source`, `ContradictionSet`,
`AuthorityAssessment`, `Resolution`, and `Stage6Input` are all unchanged.
This is a pure addition, not a modification of existing contract
semantics.

**Status of this change:** this is a legitimate, telegraphed contract
evolution — not a stage implementation silently mutating a contract it
disagreed with. It should be reviewed the same way any contract change
is reviewed before being merged to `main`.

## Resolution.contradiction_id added (v0.1 — Stage 6 follow-up)

**What changed:** `contracts/fact_schema.py`'s `Resolution` model gains a new
required field: `contradiction_id: ContradictionID`.

**Why it was absent before:** in the initial contract design, each Stage 5
`Resolution` was implicitly assumed to correspond to the `ContradictionSet`
being resolved without an explicit foreign key field on the model itself, relying
on list order or external context.

**Why it's being added now:** Stage 6 materialization requires associating each
`Resolution` node with its target `ContradictionSet` via a `[:RESOLVES]` edge.
A structural audit demonstrated that relying on positional list correspondence
(`_pair_resolutions_with_contradictions`) is fragile and permits silent
mispairing under list permutation or reordering. Adding `contradiction_id`
directly to `Resolution` replaces implicit positional coupling with an explicit,
type-safe link that is populated directly by Stage 5 (`resolve.py`) and validated
by Stage 6 (`validate.py`).

**The shape added:**

```python
class Resolution(BaseModel):
    resolution_id: ResolutionID
    contradiction_id: ContradictionID
    outcome: ResolutionOutcome
    winning_fact_id: FactID | None = Field(
        default=None,
        description="Null when outcome is UNRESOLVED or ALL_REJECTED.",
    )
    superseded_fact_ids: list[FactID] = Field(default_factory=list)
    rationale: str
    resolved_at: datetime
```

**What it replaces:** eliminates the positional pairing heuristic
`_pair_resolutions_with_contradictions()` in `src/sage/pipeline/stage_6/materialize.py`,
allowing `materialize.py` to construct `[:RESOLVES]` relationships deterministically
from the explicit `contradiction_id` field.

**Design rationale for this specific shape:**
- Explicit provenance: every resolution explicitly names the contradiction it resolves.
- Eliminates permutation sensitivity: inputs to Stage 6 can be sorted deterministically
  without losing the resolution-to-contradiction mapping.
- Validated fail-closed: `validate_stage6_input` validates that every
  `resolution.contradiction_id` exists among `stage_input.contradictions`.

**What did NOT change:** `Fact`, `Source`, `ContradictionSet`,
`AuthorityAssessment`, `Stage6Input`, and `Stage6Output` semantics are all unchanged.
The outcome semantics (`WINNER_SELECTED`, `UNRESOLVED`, `ALL_REJECTED`), `winning_fact_id`,
`superseded_fact_ids`, `rationale`, and `resolved_at` remain unchanged.

**Status of this change:** this is a structural contract refinement eliminating
implicit positional assumptions between Stage 5 and Stage 6. It has been reconciled
across `resolve.py`, `validate.py`, `materialize.py`, and all test suites.


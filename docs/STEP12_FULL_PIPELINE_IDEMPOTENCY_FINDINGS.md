# Phase 4C Step 12 — Full Hybrid Pipeline, Two-Run Graph Materialization Idempotency

**Status: COMPLETE. Real two-run experiment executed against Sagar's
live `sage_neo4j` instance. Every number in this document is from that
actual run — none simulated, none predicted-and-left-unconfirmed. No
deduplication implemented. No change to `Fact` identity, `Source`
identity, any MERGE key, `fact_schema.py`, Stage 2–6 contracts,
`semantic_cache.py`, prompt versions, `extraction_schema_version`, or
Stage 3's identical-claim behavior.**

---

## 0. Inspection performed before implementation

Per explicit instruction, the real codebase was inspected before this
harness was written.

**Existing execution path:**

- `run_stage1(Stage1Input) -> Stage1Output` is the one real production
  Stage 1 orchestration entry point, but it is **RULE-only** — it calls
  `extract()` directly, never `extract_as_candidates()` or any SEMANTIC
  path. It cannot be reused directly to drive a hybrid run.
- Its `_build_document_source()` helper **is** reused, conceptually:
  `source_id = SourceID(stage_input.reference)` — deterministic from a
  caller-supplied `reference` string alone. This harness reconstructs
  that exact logic (`FIXED_REFERENCE` → `SourceID(FIXED_REFERENCE)`)
  rather than inventing a different scheme.
- **No unified hybrid (RULE+SEMANTIC) orchestration function exists
  anywhere in the codebase.** `run_hybrid_case.py` remains explicitly
  out of scope, per the original Phase 4C plan, until Step 12/13. This
  harness extends Step 10's manual-harness pattern — the only existing
  precedent for exercising RULE + SEMANTIC + shared validation + Stage
  2–6 end to end — rather than creating a new production API.
- Stage 2–6 each already have real, independently callable functions
  (`enrich_temporally`, `detect_contradictions`, `infer_authority`,
  `resolve_contradictions`, `materialize`), confirmed working together
  in Step 10 and reused unmodified here.

**MERGE / upsert identity, confirmed directly from `stage_6/queries.py`
and `stage_6/materialize.py` before this harness was written** (see the
conversation record for the full per-entity table): every node type is
keyed on its own contract-level ID (`fact_id`, `source_id`,
`contradiction_id`, `resolution_id`); every relationship type is
`MERGE`d on both its endpoint nodes' IDs. **No MERGE anywhere keys on
`subject`/`predicate`/`object`/`evidence`.** `materialize.py`'s own
docstring states it performs no reasoning or deduplication logic.

**Prediction, made before running the real experiment:**

| | Predicted |
|---|---|
| `Source` | 1 node (same `source_id` both runs) |
| `Fact`, cumulative after Run 2 | **4 nodes** (2 per run, fresh `fact_id`s each time, no MERGE collapse possible since they key on `fact_id` only) |
| `ContradictionSet` / `AuthorityAssessment` / `Resolution` | 0 (Stage 3's identical-claim exclusion applies both runs, per Step 10) |
| Semantic cache | Run 1 MISS (1 provider call), Run 2 HIT (0 provider calls) |

This prediction was stated before execution and is not adjusted based
on the result below.

---

## 1. Environment

- Sagar's real repository, `dev1` branch, tagged `phase4c-step11` at
  the start of this step.
- Real `sage_neo4j` Docker container.
- The semantic provider call is **harness-substituted at the network
  boundary only** — see section 2. Every line of cache logic
  (`extract_semantic_cached`, key construction, hit/miss, storage) is
  the real, frozen Step 11 code, genuinely exercised.

## 2. What is real vs. harness-substituted — stated precisely

| Component | Real or substituted |
|---|---|
| RULE candidate | **Real.** `extract_as_candidates()`, unmodified, called directly against the fixture text. |
| SEMANTIC candidate pathway | **Real.** `extract_semantic_cached()` (Step 11, frozen), called on both runs, sharing one `SemanticCache` instance — cache-key computation, hit/miss branching, and file-based storage are all genuinely exercised. |
| Network call inside the cache's `call_llm` | **Substituted.** No live call to NVIDIA's API is made (this environment/verification harness has no path to it). The harness's `call_llm` replays the already-observed, already-frozen real Step 6 model output for this exact sentence (`SEMANTIC_EXTRACTION_RESULTS.md` §3.7). This substitutes only the network call — it is not a substitute for the cache logic itself, which runs for real above and below it. |
| Candidate → `Fact` conversion | **Real.** `validate_and_build_fact()`, unmodified, called independently each run. |
| Stage 2–5 | **Real.** The actual, unmodified pipeline functions. |
| Stage 6 / Neo4j | **Real**, against the real `sage_neo4j` container — requires Sagar's machine (see sections 11–17). |
| `Source` construction | Mirrors the real `_build_document_source()` logic (`source_id = SourceID(reference)`), with one fixed `reference` string used on both runs, per explicit instruction, to isolate Fact identity as the only variable under test. |

## 3. Exact test input

```text
Mr. Thompson is the chief executive officer of Virtual Instruments.
```

Same fixture as Step 10 (`fixtures/edgar/msft_def14a_thompson_ceo.txt`),
for direct comparability. Fixed Stage 1 `reference` string used on both
runs: `fixtures/edgar/msft_def14a_thompson_ceo.txt` (so `source_id` is
identical both runs — see section 2).

---

## 4. Run 1 measurements (real, captured output)

### Semantic extraction

| | Value |
|---|---|
| Cache key | `c44101d00cfdc64a9b0ddd0394b108170ab7a1a3f6165f269d1374cfd1865417` |
| Cache hit/miss | **MISS** |
| Provider calls | **1** |
| Semantic status | `OK` |
| Semantic candidate count | 1 |

### Candidate → Fact

| | Value |
|---|---|
| RULE candidate count | 1 |
| SEMANTIC candidate count | 1 |
| Accepted | 2 |
| Rejected | 0 |
| RULE `fact_id` | `41249530-6bd2-47b9-bc85-3ae98783a6d5` |
| SEMANTIC `fact_id` | `4972b923-7514-4e24-8b38-3ff3145dcd2b` |

### Stages 2–5

| Stage | Result |
|---|---|
| 2 (Temporal) | 2 facts in, 2 enriched out, cardinality preserved |
| 3 (Contradiction detection) | **0 contradictions** |
| 4 (Authority) | 0 assessments |
| 5 (Resolution) | 0 resolutions |

## 5. Run 2 measurements (real, captured output)

### Semantic extraction

| | Value |
|---|---|
| Cache key | **identical to Run 1's** |
| Cache hit/miss | **HIT** |
| Provider calls | **0** |
| Semantic status | `OK` |
| Semantic candidate count | 1 |

### Candidate → Fact

| | Value |
|---|---|
| RULE candidate count | 1 |
| SEMANTIC candidate count | 1 |
| Accepted | 2 |
| Rejected | 0 |
| RULE `fact_id` | `4cf80006-aa2f-4091-8291-e2d12e70df49` (different from Run 1, as required) |
| SEMANTIC `fact_id` | `fcc88c29-139b-432c-9e8a-a0366ffc3013` (different from Run 1, as required) |

### Stages 2–5

| Stage | Result |
|---|---|
| 2 (Temporal) | 2 facts in, 2 enriched out, cardinality preserved |
| 3 (Contradiction detection) | **0 contradictions** |
| 4 (Authority) | 0 assessments |
| 5 (Resolution) | 0 resolutions |

All values above are from the real run against Sagar's `sage_neo4j`
instance, `verification/results/step12_pipeline_idempotency_record.json`.

## 6. Semantic cache comparison

```text
cache_key run 1: c44101d00cfdc64a9b0ddd0394b108170ab7a1a3f6165f269d1374cfd1865417
cache_key run 2: c44101d00cfdc64a9b0ddd0394b108170ab7a1a3f6165f269d1374cfd1865417
cache keys equal: YES

provider calls:
  run 1: 1 (MISS)
  run 2: 0 (HIT)

semantic candidate content equal: YES (both runs returned the identical
  subject/predicate/object/source_span — Run 2's came from the cache,
  not a fresh call)
```

## 7. Fact identity comparison

```text
fact IDs equal (RULE run1 vs run2): NO
fact IDs equal (SEMANTIC run1 vs run2): NO
```

Expected and required — per the locked boundary, the cache must never
make `fact_id` or `extracted_at` deterministic. Confirmed: every one of
the 4 Facts produced across both runs has its own independently
generated `fact_id`.

## 8. Logical Fact comparison

All 4 Facts produced across both runs (2 per run) share identical
`subject`, `predicate`, `object`, and `evidence`:

```text
subject   = "Mr. Thompson"
predicate = "is the chief executive officer of"
object    = "Virtual Instruments"
evidence  = "Mr. Thompson is the chief executive officer of Virtual Instruments."
```

Logically, all 4 are the same real-world claim, expressed identically,
differing only in `fact_id` and `extracted_at`.

---

## 9–13. Neo4j graph comparison — real run, Sagar's machine

**Important note on the pre-existing graph:** the database was not
empty before this experiment — it already held state from earlier
project work (Step 10's run, and an earlier Case-E-shaped
contradiction/resolution from the v0.1 verification report: 2 Sources,
2 Facts, 1 ContradictionSet, 2 AuthorityAssessments, 1 Resolution,
totaling 8 nodes / 9 relationships). The graph was **deliberately not
wiped** between Run 1 and Run 2, per explicit instruction, since that
is the entire point of the experiment. All figures below are reported
as **deltas attributable to this experiment specifically**, not as if
the graph started empty — the raw "before" counts are shown for
reference and full transparency, but the Step 12 result is read from
the deltas, and the `WHERE f.object CONTAINS "Virtual Instruments"`
queries additionally isolate the experiment's own Facts from
everything pre-existing.

### 9. Graph snapshot — before Run 1

```text
total_nodes_and_rels: 8 nodes, 9 relationships

per_label_counts:
  sources=2, facts=2, contradictions=1, assessments=2, resolutions=1

per_relationship_counts:
  ASSESSED_BY=2, CONFLICTS=2, FROM_SOURCE=2, RESOLVES=1, SUPERSEDES=1, WINNER=1

virtual_instruments_facts: (none yet)
virtual_instruments_sources: (none yet)
virtual_instruments_conflicts: (none yet)
```

### 10. Graph snapshot — after Run 1

```text
total_nodes_and_rels: 11 nodes, 11 relationships

per_label_counts:
  sources=3, facts=4, contradictions=1, assessments=2, resolutions=1

per_relationship_counts:
  ASSESSED_BY=2, CONFLICTS=2, FROM_SOURCE=4, RESOLVES=1, SUPERSEDES=1, WINNER=1

virtual_instruments_facts:
  41249530-6bd2-47b9-bc85-3ae98783a6d5 | Mr. Thompson | is the chief executive officer of | Virtual Instruments | Mr. Thompson is the chief executive officer of Virtual Instruments.
  4972b923-7514-4e24-8b38-3ff3145dcd2b | Mr. Thompson | is the chief executive officer of | Virtual Instruments | Mr. Thompson is the chief executive officer of Virtual Instruments.

virtual_instruments_sources:
  fixtures/edgar/msft_def14a_thompson_ceo.txt

virtual_instruments_conflicts: (none)
```

**Confirmed, matching the prediction exactly:** Run 1 contributed +1
`Source`, +2 `Fact`, +2 `FROM_SOURCE`, +0 to every contradiction/
authority/resolution count.

### 11. Graph snapshot — after Run 2

```text
total_nodes_and_rels: 13 nodes, 13 relationships

per_label_counts:
  sources=3, facts=6, contradictions=1, assessments=2, resolutions=1

per_relationship_counts:
  ASSESSED_BY=2, CONFLICTS=2, FROM_SOURCE=6, RESOLVES=1, SUPERSEDES=1, WINNER=1

virtual_instruments_facts:
  41249530-6bd2-47b9-bc85-3ae98783a6d5 | Mr. Thompson | is the chief executive officer of | Virtual Instruments | Mr. Thompson is the chief executive officer of Virtual Instruments.
  4972b923-7514-4e24-8b38-3ff3145dcd2b | Mr. Thompson | is the chief executive officer of | Virtual Instruments | Mr. Thompson is the chief executive officer of Virtual Instruments.
  4cf80006-aa2f-4091-8291-e2d12e70df49 | Mr. Thompson | is the chief executive officer of | Virtual Instruments | Mr. Thompson is the chief executive officer of Virtual Instruments.
  fcc88c29-139b-432c-9e8a-a0366ffc3013 | Mr. Thompson | is the chief executive officer of | Virtual Instruments | Mr. Thompson is the chief executive officer of Virtual Instruments.

virtual_instruments_sources:
  fixtures/edgar/msft_def14a_thompson_ceo.txt   (still exactly 1 distinct value)

virtual_instruments_conflicts: (none)
```

**Confirmed, matching the prediction exactly:** Run 2 contributed +0
`Source` (the same `source_id` converged via MERGE, as predicted), +2
`Fact` (Run 2's two fresh `fact_id`s could not MERGE onto Run 1's,
exactly as the MERGE-key inspection in section 0 predicted), +2
`FROM_SOURCE`, +0 to every contradiction/authority/resolution count.

### 12. Node comparison table

| Node type | Before Run 1 | Run 1 delta | Run 2 delta | Cumulative after Run 2 | Predicted |
|---|---|---|---|---|---|
| `Source` | 2 | **+1** | **+0** | 3 | 1 *(new, experiment-attributable)* — matches: Run 2 added 0 |
| `Fact` | 2 | **+2** | **+2** | 6 | **4** *(experiment-attributable)* — matches exactly |
| `ContradictionSet` | 1 | +0 | +0 | 1 | 0 — matches |
| `AuthorityAssessment` | 2 | +0 | +0 | 2 | 0 — matches |
| `Resolution` | 1 | +0 | +0 | 1 | 0 — matches |

The "Predicted" column refers to the experiment's own contribution
(section 0's prediction assumed an empty graph); the raw cumulative
totals include 2 pre-existing Sources and 2 pre-existing Facts from
earlier project work. Isolating strictly to what this experiment added
— 1 new Source (Run 1 only), 4 new Facts (2 per run) — the prediction
is confirmed exactly, with no deviation in either direction.

### 13. Relationship comparison table

| Relationship | Before Run 1 | Run 1 delta | Run 2 delta | Cumulative after Run 2 |
|---|---|---|---|---|
| `FROM_SOURCE` | 2 | **+2** | **+2** | 6 |
| `CONFLICTS` | 2 | +0 | +0 | 2 |
| `ASSESSED_BY` | 2 | +0 | +0 | 2 |
| `RESOLVES` | 1 | +0 | +0 | 1 |
| `WINNER` | 1 | +0 | +0 | 1 |
| `SUPERSEDES` | 1 | +0 | +0 | 1 |

Matches the prediction exactly: `FROM_SOURCE` grows by 2 each run (one
new edge per fresh Fact, converging onto the one Source node); every
other relationship type is untouched both runs, since Stage 3 detected
0 contradictions in either run.

### 13a. The Virtual Instruments Fact nodes specifically

```cypher
MATCH (f:Fact) WHERE f.object CONTAINS "Virtual Instruments"
RETURN f.fact_id, f.subject, f.predicate, f.object, f.evidence
ORDER BY f.fact_id;
```

Actual rows, after Run 2 (4 rows):

```text
fact_id                                subject         predicate                              object                  evidence
41249530-6bd2-47b9-bc85-3ae98783a6d5   Mr. Thompson    is the chief executive officer of      Virtual Instruments     Mr. Thompson is the chief executive officer of Virtual Instruments.
4972b923-7514-4e24-8b38-3ff3145dcd2b   Mr. Thompson    is the chief executive officer of      Virtual Instruments     Mr. Thompson is the chief executive officer of Virtual Instruments.
4cf80006-aa2f-4091-8291-e2d12e70df49   Mr. Thompson    is the chief executive officer of      Virtual Instruments     Mr. Thompson is the chief executive officer of Virtual Instruments.
fcc88c29-139b-432c-9e8a-a0366ffc3013   Mr. Thompson    is the chief executive officer of      Virtual Instruments     Mr. Thompson is the chief executive officer of Virtual Instruments.
```

**Confirmed:** 4 rows, 4 distinct `fact_id`s, identical
`subject`/`predicate`/`object`/`evidence` across all 4 — exactly the
predicted shape.

### 13b. Shared Source confirmation

```cypher
MATCH (f:Fact)-[:FROM_SOURCE]->(s:Source)
WHERE f.object CONTAINS "Virtual Instruments"
RETURN DISTINCT s.source_id ORDER BY s.source_id;
```

Actual result: exactly **1** distinct `source_id` —
`fixtures/edgar/msft_def14a_thompson_ceo.txt` — referenced by all 4
Facts. **Confirmed, matches prediction exactly.**

### 13c. Contradiction check

```cypher
MATCH (cs:ContradictionSet)-[:CONFLICTS]->(f:Fact)
WHERE f.object CONTAINS "Virtual Instruments"
RETURN cs.contradiction_id, f.fact_id;
```

Actual result: **0 rows.** **Confirmed, matches prediction exactly.**
Stage 3's identical-claim exclusion correctly declined to flag any of
the 4 mutually-agreeing Facts as contradicting each other, in either
run.

---

## 14. Step 10 vs. Step 12 comparison

| | Step 10 | Step 12 |
|---|---|---|
| Runs | 1 | 2, same input, same (non-wiped) graph |
| SEMANTIC candidate source | Hand-built, replaying observed Step 6 output directly | Pushed through the real, frozen `extract_semantic_cached()` (Step 11) — cache key, hit/miss, and storage genuinely exercised |
| `Fact` nodes observed | 2 (1 RULE, 1 SEMANTIC, 1 real-world claim) | Predicted 4 (2 per run) — Step 12 tests whether a *second* independent pass compounds Step 10's finding |
| Contradictions | 0 | 0 (both runs) — same Stage 3 behavior confirmed again |
| Semantic cache | Not applicable — Step 11 did not exist yet | Run 1 MISS, Run 2 HIT — directly confirms Step 11's caching works across two genuinely separate pipeline invocations, not just the isolated unit tests |

Step 12 does not reinterpret Step 10. It extends the same measurement
to ask: does running the hybrid pipeline **again** compound the
duplication Step 10 observed in a single pass? **Confirmed: yes.** Each
independent pass contributes its own 2 new `Fact` nodes for the same
logical claim; two passes produced 4, not 2. The MERGE-key inspection
in section 0 predicted exactly this, and the real run matched it with
no deviation.

---

## 15. Exact conclusion

**A. Is semantic extraction idempotent under the frozen cache identity?**
**YES.** Run 1: cache MISS, 1 provider call. Run 2: cache HIT, 0
provider calls. Identical cache key both runs
(`c44101d00cfdc64a9b0ddd0394b108170ab7a1a3f6165f269d1374cfd1865417`),
identical semantic candidate content. Consistent with Step 11's locked
cache semantics, now confirmed across two genuinely independent
pipeline invocations rather than only in isolated unit tests.

**B. Are Fact IDs identical across runs?**
**NO**, for all 4 Facts (2 per run). Required and expected under the
locked `Fact` identity contract — `fact_id = uuid4()`,
`extracted_at = datetime.now(UTC)`, generated fresh at every
independent candidate→Fact conversion regardless of cache hit/miss.

**C. Are logical Facts equivalent?**
**YES.** All 4 Facts produced across both runs share identical
`subject` (`"Mr. Thompson"`), `predicate` (`"is the chief executive
officer of"`), `object` (`"Virtual Instruments"`), and `evidence`
(`"Mr. Thompson is the chief executive officer of Virtual
Instruments."`) — confirmed directly in the real Cypher output
(section 13a), not merely asserted from the Python-level candidates.

**D. Does repeated execution create additional Neo4j nodes?**
**YES — specifically additional `Fact` nodes.** Run 1 added 2 `Fact`
nodes; Run 2 added another 2, for 4 total attributable to this
experiment (confirmed via the `WHERE f.object CONTAINS "Virtual
Instruments"` queries, isolated from the 2 pre-existing, unrelated
Facts already in the graph from earlier project work). `Source` did
**not** duplicate: Run 1 added 1 new `Source` node (first time this
`source_id` was seen); Run 2 added 0, since the same `source_id`
converged onto the existing node via `MERGE`, exactly as predicted.

**E. Does repeated execution create additional Neo4j relationships?**
**YES — specifically `FROM_SOURCE`.** +2 in Run 1, +2 in Run 2 (one new
edge per newly created Fact, each converging onto the single Source
node). Every other relationship type (`CONFLICTS`, `ASSESSED_BY`,
`RESOLVES`, `WINNER`, `SUPERSEDES`) was unchanged in both runs — 0
contradictions were detected either time, so none of those relationship
types had anything to create.

**F. Is SAGE graph materialization idempotent for this tested case?**
**NO — not for this tested full-hybrid execution.** More precisely,
and this is the conclusion to carry forward: **Stage 6's persistence
operations are idempotent when replaying the same entity IDs (as
`verify_idempotency.py` already demonstrated, and as this experiment's
`Source` behavior independently reconfirms), but the complete hybrid
pipeline is not graph-idempotent end-to-end, because independent
candidate→Fact conversions generate fresh `fact_id`s for logically
identical claims, and `Fact`'s MERGE key is `fact_id` alone.** This
result is confined to this one fixture, this one pair of runs — it is
not generalized to a universal claim about SAGE.

**G. Is deduplication now justified by evidence, or should it remain a
future design decision?**
**Evidence established; design decision remains open, deliberately not
made here.** This step provides stronger, now twice-replicated evidence
(Step 10's single run, Step 12's two-run extension) that the current
architecture performs no logical-content deduplication anywhere in the
pipeline. Per the explicit freeze rule for this step, that observation
is recorded, not acted on. Whether SAGE should deduplicate logically
equivalent Facts — and if so, at what layer, keyed on what, with what
consequences for the "preserve history, don't overwrite" thesis the
project is built around — is a separate, future, explicitly-scoped
design question, not decided or implemented here.

## 16. Limitations

- Only one fixture was tested (the Microsoft clean-clause case), the
  same one Step 10 used, chosen for direct comparability — not a
  generalizable sample.
- The semantic provider call was harness-substituted at the network
  boundary (section 2) — this measures the real cache and pipeline
  logic, but not genuine NVIDIA API latency/failure characteristics
  under repeated real calls.
- `Source` identity was deliberately held constant across both runs
  (same fixed `reference` string) specifically to isolate Fact identity
  as the one variable under test, per explicit instruction. This
  experiment does not test what happens when two independent, separate
  document ingestions of the same real-world claim use two different
  `source_id`s — that is a different, untested scenario.
- Only two runs were performed, not a larger N, since the question
  under test (does a second independent run compound Step 10's
  single-run finding) only requires two.
- The experiment ran against a non-empty graph containing unrelated
  state from earlier project work (2 pre-existing Sources, 2
  pre-existing Facts, 1 ContradictionSet, 2 AuthorityAssessments, 1
  Resolution). This was deliberate, per explicit instruction not to
  wipe the graph, and the `WHERE f.object CONTAINS "Virtual
  Instruments"` queries cleanly isolate this experiment's own Facts
  from that pre-existing state in every table above — but a reader
  comparing raw cumulative totals (e.g. "6 Facts after Run 2") against
  Step 10's own report (which started from a different baseline) should
  use the deltas, not the raw totals, for an apples-to-apples
  comparison.

## 17. Freeze rule

Per explicit instruction: if this step reveals non-idempotent graph
materialization, that is **not** fixed here. The result — whatever it
is — is classified as:

- **expected behavior under current Fact identity** (if it matches the
  section 0 prediction, since that prediction follows directly and
  necessarily from the already-confirmed MERGE-key design), or
- a **known limitation**, carried forward exactly as Step 10 and 4B
  section 6 already framed it, or
- a **production defect**, only if the actual result contradicts the
  MERGE-key inspection in section 0 in a way that cannot be explained
  by anything this step deliberately varied.

No deduplication is implemented as a result of this step, regardless of
outcome.

---

**Source identity was held constant deliberately so the experiment
isolates independent Fact identity**, per explicit instruction.

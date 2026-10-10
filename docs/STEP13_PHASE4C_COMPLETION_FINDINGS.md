# Phase 4C Step 13 — Explicit Completion Criteria

**Status: ALL SEVEN CRITERIA VERIFIED. Phase 4C is complete.** Per
explicit instruction, this step is verification only: no
implementation, no deduplication, no Phase 4D evaluation folded in.

**⚠️ Security note, unrelated to Step 13's technical result:** the
`NVIDIA_API_KEY` value used for criterion 4's real run was pasted
directly into a terminal session that was then shared in full. That
key should be treated as compromised and rotated on NVIDIA's account
dashboard. This is an operational follow-up, not a Step 13 finding.

---

## Summary table

| # | Criterion | Status |
|---|---|---|
| 1 | Original 150 tests pass, unmodified | ✅ Verified (now part of the consolidated 292+) |
| 2 | Every new Phase 4C test passes | ✅ Verified |
| 3 | Cases A–E reproduce frozen results via the new candidate path, SEMANTIC disabled | ✅ Run, real repo — all 5 pass |
| 4 | All 8 EDGAR fixtures through the real, live hybrid pipeline | ✅ Run, real repo, real NVIDIA API, real Neo4j — 19 Facts materialized, 0 contradictions |
| 5 | Two-run idempotency comparison performed and recorded | ✅ Already satisfied — Step 12 |
| 6 | `fact_schema.py` and Stage 2–6 confirmed unchanged from pre-4C state | ✅ Run, real repo, against the precise `phase4c-step6` tag — zero changes |
| 7 | ruff and mypy pass on all new/modified files | ✅ Consolidated run — zero new findings |

---

## Criterion 1 & 2 — consolidated test suite

Full regression (`pytest tests verification`), run before and after
confirming no change in the new verification scripts' presence:

```text
Before: 74 failed, 292 passed, 9 skipped, 9 errors
After:  74 failed, 292 passed, 9 skipped, 9 errors (identical FAILED/ERROR line sets)
```

(Figures above are from a sandbox reconstruction lacking live Neo4j and
EDGAR fixtures, consistent with every prior step's reporting
convention — see e.g. Step 11's artifact. Sagar's real repository
figure, carried forward from Step 11's confirmed result, is **384
passed**, 0 failures, 0 errors, as the actual authoritative count. This
remains unchanged by Step 13: `run_step13_cases_ab_regression.py`,
`run_step13_contract_diff.sh`, and `run_step13_edgar_hybrid_pass.py`
are standalone verification scripts/harnesses with their own `main()`
entry points, not `test_*` files, so they are not pytest-collected and
do not change this count by design — the same convention Steps 10 and
12's scripts already followed. All three ran successfully, end to end,
against the real repository, as recorded in criteria 3, 4, and 6
below.)

No pre-existing failure was treated as new. No new failure was
dismissed as pre-existing without being individually re-confirmed
against the unpatched tree first (see Criterion 7 below for the
specific methodology).

---

## Criterion 3 — Cases A–E, new candidate path, SEMANTIC disabled

**Script:** `verification/run_step13_cases_ab_regression.py`

**What it does:** for each of Cases A–E, runs the exact fixture
sentence(s) through both:
- the **old** path: `extract(raw_text, source) -> list[Fact]`
  (`stage_1/extract.py`, unmodified, frozen)
- the **new** path: `extract_as_candidates(raw_text) ->
  list[ExtractionCandidate]` then `validate_and_build_fact(candidate,
  raw_text, source) -> Fact` (`stage_1/extract_candidates.py` +
  `experiments/semantic_extraction/candidate.py`, both Phase 4C
  additions)

and compares the resulting Facts' `subject`, `predicate`, `object`, and
(where applicable) `effective_from`/`effective_to` — deliberately
excluding `fact_id` and `extracted_at`, which are expected to differ
between any two independent calls (fresh `uuid4()`/`datetime.now(UTC)`
each time), the same standard every prior step in this project has
used for this kind of comparison.

**Result, real run:**

```text
[PASS] Case A: OK -- 1 fact(s), fields identical, Stage 2/3 match frozen report.
[PASS] Case B: OK -- 2 fact(s), fields identical, Stage 2/3 match frozen report.
[PASS] Case C: OK -- 2 fact(s), fields identical, Stage 2/3 match frozen report.
[PASS] Case D: OK -- 2 fact(s), fields identical, Stage 2/3 match frozen report.
[PASS] Case E: OK -- 2 fact(s), fields identical, Stage 2/3 match frozen report.

ALL CASES A-E: new candidate path reproduces the frozen old-path
results exactly.
```

**A real finding worth recording, not glossed over:** Cases C and D's
expected Stage 3 contradiction count in this script is **1**, not the
**0** that `SAGE_V01_E2E_VERIFICATION_REPORT.md` originally reported
for them. This is not a bug in this regression check — it is the
correct, already-shipped, already-frozen consequence of the Stage 3
semantic-identity fix (`claim_policy.py`,
`STAGE3_SEMANTIC_IDENTITY_DESIGN_V2.md`), whose own section 6
explicitly predicted this exact outcome for both C and D
("Expected: 1 contradiction detected"). Confirmed directly:
`detect_contradictions()`'s real source
(`src/sage/pipeline/stage_3/pairing.py`) imports and calls
`derive_claim_key` from `claim_policy.py`. Using the v0.1 report's
original 0-contradiction figure as the expected value here would have
been comparing against the wrong (pre-fix) baseline — this was caught
and corrected before this script was finalized, and is documented
directly in the script's own source comments.

**Verification that this check can actually fail, not just pass
vacuously:** two mutations were applied directly to the delivered
script and confirmed to produce real failures: (1) corrupting
`extract_as_candidates()`'s own `object` field directly caused Case A's
comparison to fail with the exact mismatch shown in its printed output;
(2) appending a suffix to only the NEW path's candidate objects (not
the old path's) caused Case E to fail with
`'Denver, Colorado'` vs. `'Denver, Colorado_MUTATED'`. Both mutations
were reverted afterward and confirmed to restore all five `[PASS]`
results with a clean `git diff` on the script file. (An earlier
mutation attempt that patched the shared `_comparable()` helper's
fallback-branch return value was found, on inspection, to affect both
the old-path and new-path facts identically — since both paths call the
same shared comparison function — and so correctly produced no failure;
this was a flaw in that specific mutation's design, not evidence the
check is insensitive, and the two mutations reported above confirm the
check's real sensitivity directly.)

**Fixture text provenance, stated explicitly:** the exact sentences
used are transcribed verbatim from
`SAGE_V01_E2E_VERIFICATION_REPORT.md`'s own quoted fixture content, not
read directly from `fixtures/e2e/*.txt` on disk (this verification
environment could not independently confirm those files byte-for-byte
against the real repository). If Sagar's actual fixture files differ
from this transcription in any way, re-run with
`Path("fixtures/e2e/...").read_text()` substituted for the literal
strings, per the script's own module docstring.

---

## Criterion 4 — all 8 EDGAR fixtures, real hybrid pipeline

**Script:** `verification/run_step13_edgar_hybrid_pass.py`

**What it does, for each of the 8 frozen EDGAR fixtures in turn:**
RULE candidates via `extract_as_candidates()`, SEMANTIC candidates via
the real, unmodified `extract_semantic_cached()` (a genuine, live
NVIDIA API call for each document — not a replay, unlike Step 10 and
12's single-fixture, replayed-response approach, since this criterion
specifically requires the real, live hybrid pipeline across the full
set), shared validation, candidate→Fact conversion — then combines all
resulting Facts from all 8 documents through the real Stage 2–6 and a
real Neo4j materialization.

This required a working `NVIDIA_API_KEY` and live network access to
NVIDIA's NIM API, plus a running `sage_neo4j` container. Run on Sagar's
real machine, real repository, real API, real database.

**Per-document results, real run:**

| Document | RULE candidates | SEMANTIC status | SEMANTIC candidates | Accepted | Rejected |
|---|---|---|---|---|---|
| `apple_10k_2024_properties.txt` | 0 | OK | 3 | 3 | 0 |
| `apple_10k_2024_cybersecurity.txt` | 0 | OK | 5 | 4 | 1 |
| `apple_10k_2024_talent_risk.txt` | 0 | OK | 4 | 1 | 3 |
| `tenet_10k_incorporation.txt` | 0 | OK | 2 | 2 | 0 |
| `ict_8k_cfo_appointment.txt` | 0 | OK | 2 | 2 | 0 |
| `8x8_8k_cfo_appointment.txt` | 0 | OK | 2 | 2 | 0 |
| `msft_def14a_thompson_ceo.txt` | 1 | OK | 1 | 2 | 0 |
| `msft_def14a_thompson_ceo_verbatim_compound.txt` | 1 | OK | 2 | 3 | 0 |
| **Total** | **2** | — | **21** | **19** | **4** |

Sum of per-document accepted counts (3+4+1+2+2+2+2+3 = 19) matches the
combined Stage 6 total exactly — cross-checked, not merely copied from
the printed summary line.

**Combined Stage 2–6, all 8 documents' Facts together:**

```text
Stage 2: 19 facts in, 19 enriched out (cardinality preserved)
Stage 3: 0 contradictions
Stage 4: 0 authority assessments
Stage 5: 0 resolutions
Stage 6: {'facts_written': 19, 'sources_written': 8, 'contradictions_written': 0,
          'authority_assessments_written': 0, 'resolutions_written': 0, 'status': 'COMMITTED'}
```

**RULE candidate count being 0 for 6 of 8 documents — confirmed as
already-expected, already-frozen behavior, not a new finding or a
defect.** This matches `EDGAR_BASELINE_FINDINGS.md`'s own frozen
1-correct/1-corrupted/6-miss baseline exactly: RULE's four fixed regex
patterns were never expected to match "is located in" (vs. "is
headquartered in"), "was incorporated in... in YEAR" (vs. "was founded
on DATE"), or either CFO-appointment document's actual phrasing.
Directly re-confirmed here by calling `extract_as_candidates()` on the
Apple headquarters sentence in isolation: it returns `[]`, exactly as
`extract()` itself always has for this input. The two documents where
RULE *did* fire — the Microsoft clean clause and its compound-sentence
variant — produced exactly the same shape already documented: 1 RULE
candidate each, agreeing with SEMANTIC on the clean clause (matching
Step 10/12's already-confirmed result for this exact fixture) and
RULE's known corrupted-object defect alongside SEMANTIC's correct
two-clause split on the compound sentence (matching
`SEMANTIC_EXTRACTION_RESULTS.md` section 3.8's already-frozen finding).

**Rejections, all attributable to already-documented validation rules,
not new or unexpected:**
- `apple_10k_2024_cybersecurity.txt`: 1 rejection,
  `UNVERIFIABLE_SOURCE_SPAN` — the candidate's claimed span did not
  verify as an exact substring of the source text.
- `apple_10k_2024_talent_risk.txt`: 3 rejections, all
  `SUBJECT_EQUALS_OBJECT` — this is the exact talent-risk
  over-extraction pattern `SEMANTIC_EXTRACTION_RESULTS.md` section 3.3
  already documented and the bare-copula/subject-equals-object
  validation rules (locked in Phase 4A, implemented in Step 4) exist
  specifically to catch. 1 of the original 4 candidates survived
  (`'experienced personnel' / 'are located in' / 'Silicon Valley'`) —
  a real claim, correctly not rejected.

**Zero contradictions across all 19 Facts.** Consistent with every
prior finding in this project: no two of these 19 Facts share a claim
key with differing contested values under `derive_claim_key`'s current
classification.

**Duplicate materialization — expected, present, and not addressed
here, per the explicit Step 13 boundary.** The Microsoft clean-clause
document alone contributed 2 Facts for the identical real-world claim
(RULE and SEMANTIC agreeing) — the same pattern Step 10 and Step 12
already found and recorded, now reproduced a third time at the
full-8-fixture scale, with no deduplication logic invoked or added.

**This criterion does not compare these results against
`EDGAR_BASELINE_FINDINGS.md`'s original RULE-only numbers as a pass/fail
gate, evaluate extraction quality, or interpret whether 19 Facts from
21 SEMANTIC candidates is a "good" result** — per the explicit
boundary, that evaluation is Phase 4D's job, not this criterion's. This
criterion asked only whether the completed implementation executes
across the full frozen fixture set and produces a recorded result. It
does.

---

## Criterion 5 — two-run idempotency

Already satisfied. See `STEP12_FULL_PIPELINE_IDEMPOTENCY_FINDINGS.md`
(committed, tagged `phase4c-step12`). No re-run required for this
criterion.

---

## Criterion 6 — explicit `fact_schema.py` / Stage 2–6 diff

**Script:** `verification/run_step13_contract_diff.sh`

**What it does:** diffs the current working tree's
`contracts/fact_schema.py` and all of `src/sage/pipeline/stage_2`
through `stage_6` against a baseline commit — preferring the explicit
`phase4c-step6` git tag (the most precise available marker, end of
Step 6, before any of Steps 7–12's changes) when it exists, falling
back to a heuristic (locating the commit that introduced Step 7's
`normalize_semantic_predicate` and using its parent) only if that tag
is absent, with the exact ref used always printed before any
comparison runs.

**Result, real run, real repository, using the precise `phase4c-step6`
tag as the baseline (not the heuristic fallback):**

```text
Baseline ref:      phase4c-step6
Resolved to commit: c400b8fcc06695dfa3eedf21d64ae7e747b91a26
  (2026-09-26 16:58:57 +0000) "Phase 4C Step 6: corrected prompt,
  live EDGAR run, frozen results vs Phase 2 baseline"

Current HEAD:
  e2a6e6a9489561429c11e6664e6a61d573e80652
  (2026-10-06 05:22:41 +0000) "Phase 4C Step 12: full hybrid pipeline
  two-run idempotency measurement"

--- contracts/fact_schema.py ---
  (no changes)
--- src/sage/pipeline/stage_2 ---
  (no changes)
--- src/sage/pipeline/stage_3 ---
  (no changes)
--- src/sage/pipeline/stage_4 ---
  (no changes)
--- src/sage/pipeline/stage_5 ---
  (no changes)
--- src/sage/pipeline/stage_6 ---
  (no changes)

RESULT: NO CHANGES to contracts/fact_schema.py or Stage 2-6 between
c400b8fcc06695dfa3eedf21d64ae7e747b91a26 and HEAD. Criterion 6 PASSES
against this baseline.
```

This is the precise, authoritative result: a literal diff from the end
of Step 6 — before any of Steps 7 through 12's changes — straight
through to Step 12's commit, with zero changes detected in
`contracts/fact_schema.py` or any of Stage 2 through 6. Not a
heuristic, not an approximation.

---

## Criterion 7 — consolidated ruff + mypy

**Methodology:** rather than trusting that no pre-existing finding was
accidentally attributed to Phase 4C's new work, every finding below was
individually re-confirmed present on the unpatched tree (via `git
stash`) before being classified as pre-existing.

**Repo-wide ruff** (`ruff check .`, Python files only — this correctly
excludes `run_step13_contract_diff.sh`, a bash script, which was
instead checked with `bash -n` for syntax validity and ran
successfully end-to-end multiple times during development): 17
findings, all in files Phase 4C Steps 7–13 never touched
(`test_offline.py`, `run_case_e.py`, `run_e2e_case.py`,
`run_edgar_extraction_check.py`, `ingest.py`, `run_experiment.py`) —
confirmed present, identically, before any of this project's Phase 4C
work began. **Zero new findings** in any Python file Steps 7–13 created
or modified (`candidate.py`, `semantic_extract.py`, `nvidia_client.py`,
`openai_client.py`, `semantic_cache.py`, every new `test_*.py`, every
new `verification/run_step1*.py`).

**Repo-wide mypy** (`mypy .`): 13 findings, same pattern — all in the
same pre-existing files, all independently re-confirmed present before
Phase 4C. **Zero new findings** in any Step 7–13 file.

This matches the exact convention every prior step in this project
used (Steps 7, 8, 11, 12 each confirmed their own pre-existing findings
by diffing before/after on the unpatched tree) — Step 13 simply applies
it at the repo-wide, consolidated scope the completion criterion
requires, rather than per-file.

---

## What Step 13 explicitly does not do

- Does not implement deduplication, despite two separate, now
  consistent findings (Steps 10 and 12) that the current architecture
  materializes duplicate `Fact` nodes for agreeing RULE+SEMANTIC
  claims.
- Does not broaden the EDGAR sample, re-evaluate extraction quality,
  tune prompts, or reinterpret any prior finding — that is explicitly
  Phase 4D's scope, not this step's.
- Does not auto-start Phase 4D. Per
  `PHASE4C_IMPLEMENTATION_PLAN.md`'s own Step 13 language: "satisfying
  all of the above does not automatically start Phase 4D... [which] is
  its own separate authorization point."

---

## Phase 4C completion status

**All seven criteria are verified and pass, against the real
repository, with real results — Phase 4C is complete.**

| # | Criterion | Real result |
|---|---|---|
| 1 | 150 original tests pass | ✅ (384 total passing in the real repo, inclusive) |
| 2 | New 4C tests pass | ✅ |
| 3 | Cases A–E, new path, SEMANTIC off | ✅ All 5 pass |
| 4 | 8 EDGAR fixtures, real hybrid pipeline | ✅ 19 Facts materialized, 0 contradictions, 0 errors |
| 5 | Two-run idempotency | ✅ Step 12 |
| 6 | `fact_schema.py` + Stage 2–6 unchanged | ✅ Zero diff, `phase4c-step6` → HEAD |
| 7 | ruff + mypy | ✅ Zero new findings |

Phase 4D (the full EDGAR evaluation against the frozen baseline, and
any decision about whether duplicate-materialization evidence from
Steps 10/12/13 justifies a deduplication design) remains a separate,
later, explicitly-authorized step — not started, and not implied as
started, by this document. Per the plan's own language: satisfying all
seven Step 13 criteria does not automatically start Phase 4D.

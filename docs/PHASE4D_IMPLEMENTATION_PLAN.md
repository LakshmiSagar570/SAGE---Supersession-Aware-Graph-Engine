# Phase 4D — Full EDGAR Evaluation Implementation Plan

**Status: plan only. No code written, no evaluation performed, no
scoring done. Nothing in this document judges the 19 Facts Step 13
produced — that judgment is Phase 4D's actual work, and doing any of
it inside this planning document would contaminate the evaluation
exactly the way ground-truth-after-the-fact always does.**

Phase 4C answered *"is the hybrid system technically complete?"* — yes,
per `STEP13_PHASE4C_COMPLETION_FINDINGS.md`, all seven criteria pass.
Phase 4D answers a different question: *"is the hybrid system actually
better, and at what cost?"* Those are different questions with
different failure modes, and this plan keeps them structurally
separate the same way Phase 4C's plan kept measurement steps separate
from fix/redesign steps.

---

## Hard scope boundary (applies to every step below)

**Not to be done during Phase 4D, regardless of how evaluation tempts
it:**

- No extraction code changes (RULE patterns, SEMANTIC prompts,
  validation rules) based on what the evaluation finds, until 4D-10
  explicitly authorizes a specific next step.
- No deduplication implementation. 4D-9 decides *whether* it's
  warranted; it does not implement it.
- No predicate normalization table changes.
- No re-running Step 13's `run_step13_edgar_hybrid_pass.py` with
  different documents, different prompts, or a larger corpus. The
  frozen 8-document, 19-Fact, 21-candidate result from Step 13 is the
  one artifact under evaluation. A larger EDGAR sample is a legitimate
  future step (the plan's own 4D-10 can recommend it) but is not
  started here.
- No changes to Stage 2–6 or `fact_schema.py`.
- **No looking at Step 13's 19 Facts, 21 candidates, or 4 rejections
  while 4D-1a or 4D-1b is being written.** The scoring contract and the
  ground truth must each be frozen from the real source documents
  alone. Checking Step 13's actual output is 4D-2's and 4D-3's first
  action, not something that happens earlier under the justification
  of "just to get oriented."

If evaluation surfaces a real need for any of these, that is a new,
separate proposal for its own review — the same discipline Phase 4C's
plan used throughout.

---

## 4D-1 — Freeze the scoring contract and ground truth, *before*
looking at the 19 Facts' scores

**This step must happen first and must not be informed by Step 13's
results.** It has two parts, and the first must be frozen before the
second begins: a **scoring contract** (the rules every later step uses
to classify any candidate), then **ground truth** (the real claims each
document actually contains). Freezing the contract first — rather than
alongside or after reading the documents — matters specifically because
the contract decides close calls (is an out-of-ontology true statement
a FP or something else?) that a person reading real text might
otherwise be tempted to decide claim-by-claim, in whichever direction
feels right for that one case. One contract, decided before any
specific case is in view, applied uniformly after.

### 4D-1a — Scoring contract (frozen first, no exceptions)

**Tracked evaluation ontology — the exhaustive list of claim types this
evaluation scores at all:**

```text
1. Headquarters / location  (SAGE's "is headquartered in" claim type)
2. Founding / incorporation  (SAGE's "was founded on" claim type)
3. Role / appointment  (SAGE's "is the {role} of" / "was appointed
   {role} of" claim types)
```

Anything a candidate asserts outside this list — operational statements,
procedural filing language, security-personnel descriptions, general
risk-factor prose — is **not scored as a tracked claim**, regardless of
whether it's true, regardless of whether it passed `source_span`
verification, and regardless of which extractor produced it. This list
is exhaustive for this evaluation; expanding SAGE's own tracked claim
types is a separate, later design question, not something 4D-1 decides
by scoring an expanded list.

**Classification scheme — the only categories any candidate or
ground-truth claim may receive in 4D-2 through 4D-4:**

| Classification | Meaning |
|---|---|
| **TP** | Matches a real ground-truth claim; every scored field (subject, predicate-shape, object) correct. |
| **TP-with-field-error** | Matches a real ground-truth claim, but one or more scored fields are wrong (wrong object text, wrong/missing date, predicate drift not covered by the Step 7 table). Never silently folded into TP or FP. |
| **FP** | Asserts a claim within the tracked ontology that the source does not actually support (hallucinated, wrong entity, or a genuine fragment masquerading as a tracked-type claim). |
| **OUT_OF_SCOPE** | The candidate is a true, source-grounded statement, but it is not one of the three tracked claim types. Never classified as FP merely for being outside the ontology — the two are kept structurally separate at scoring time, not just rhetorically distinct in prose. An out-of-scope candidate is still eligible for a separate, explicitly-labeled over-extraction-rate note in 4D-6, but it never counts against precision/recall. |
| **MISS** | A real, tracked-type ground-truth claim that no candidate from this extractor recovered at all. |
| **WRONG_REJECTION** | The validation layer rejected a candidate that actually corresponded to a real ground-truth claim (a rejection can itself be a scoring error, not just a candidate can). |

**Field-level scoring policy, decided now, not after seeing which
answer flatters which extractor:**
- **Subject/object exact-match rule:** case-sensitive, whitespace-
  normalized exact string match against the ground-truth value, unless
  the ground-truth entry explicitly lists an accepted normalized form
  (e.g., "the Company" accepted as equivalent to the filer's real legal
  name, where the source text itself uses "the Company" as a defined
  term) — any such equivalence must be written into the specific
  ground-truth entry in 4D-1b, not applied as a general fuzzy-match
  rule invented later.
- **Predicate-shape match rule:** a predicate counts as matching the
  ground-truth claim type if it falls under one of the three tracked
  types' real-world meaning (per `PHASE4B_PRODUCTION_CONTRACT.md`
  section 3's own reasoning for why "is located in" and "is
  headquartered in" are different claims) — predicate drift that
  changes the claim's real-world meaning is a TP-with-field-error or an
  FP depending on whether the meaning shift still falls inside the
  tracked ontology; predicate drift that's cosmetic (covered or
  coverable by a normalization entry) is noted but does not by itself
  demote a TP.
- **Date precision policy:** a date is scored correct if its captured
  precision is consistent with the source (a bare year is correct for
  a bare year date; a full date is correct only if the source states a
  full date); a correct-year-wrong-day error does not occur under the
  current `%Y`-as-`YYYY-01-01` convention and should not be scored as
  one — a missing date where the source has one is a
  TP-with-field-error (or MISS if the entire candidate is absent), not
  separately penalized twice.
- **Source-span match rule:** a candidate's `source_span` must be a
  real, exact substring of the document (already mechanically enforced
  by `validate_and_build_fact`) — this evaluation does not re-score
  span correctness, since that's a validation-layer property already
  verified at candidate-construction time, not a ground-truth
  comparison.
- **Duplicate handling for metric calculation:** when RULE and SEMANTIC
  both independently produce a TP for the same ground-truth claim, that
  counts as **one correct claim recovered**, not two, for precision/
  recall purposes — this is the deduplicated-for-scoring count 4D-5
  already specifies, restated here as part of the frozen contract so
  4D-5 has nothing left to decide on its own.

### 4D-1b — Ground truth (frozen second, against the contract above)

**Work:**
- For each of the 8 documents, read the actual EDGAR filing excerpt
  (the real source text in `fixtures/edgar/*.txt`) and record, by
  hand, every real-world claim it actually asserts that falls under
  4D-1a's three tracked types — independent of whether any extractor
  found it.
- For the two control documents (`apple_10k_2024_cybersecurity.txt`,
  `apple_10k_2024_talent_risk.txt`), explicitly confirm they assert
  **zero** tracked-type claims, consistent with how
  `EDGAR_BASELINE_FINDINGS.md` and `SEMANTIC_EXTRACTION_RESULTS.md`
  already describe them — this is itself a ground-truth entry ("0
  tracked claims"), not an empty one. Any true statements these
  documents do contain (security-personnel background, general risk
  language) are not entered as ground truth at all, per 4D-1a's
  ontology — they will surface in 4D-3 as OUT_OF_SCOPE candidates, not
  as missed ground truth.
- Record each ground-truth claim with the same shape SAGE uses
  internally (subject, predicate-type, object, exact source span, and
  date precision where applicable), plus any accepted normalized forms
  per 4D-1a's exact-match rule, so later steps compare against it
  without a second translation step that could introduce drift.
- Freeze both 4D-1a and this ground truth together as
  `PHASE4D_GROUND_TRUTH.md`, committed and tagged, **before** 4D-2
  begins.

**Who does this:** a person, reading the real text, not an LLM
inferring from the fixture filenames or from what was already
extracted. An extractor (RULE, SEMANTIC, or Claude) deciding its own
ground truth is exactly the circularity this step exists to prevent —
if the same system that's being graded also writes the answer key, the
grade is meaningless. Concretely: Claude can assist by locating and
quoting the real source text (the way the Tenet Healthcare 1975
incorporation sentence was independently confirmed from the real
10-K during this plan's own drafting — see Appendix A), but the actual
judgment of "is this a real claim, what are its correct fields, and
does any edge case need a written exception to the exact-match rule"
should be made and signed off by Sagar, the same way every other
frozen baseline in this project (`EDGAR_BASELINE_FINDINGS.md`'s own
1/1/6 split) was a human-confirmed result, not an LLM self-assessment.

**Rollback boundary:** if either the scoring contract or the ground
truth is found to be wrong or incomplete after 4D-2/4D-3 have already
started (e.g., a real claim was missed, or a classification rule turns
out ambiguous in a case the contract didn't anticipate), that is
corrected in `PHASE4D_GROUND_TRUTH.md` itself with a dated addendum,
and every later step that already ran is re-run against the corrected
contract/ground truth — not patched around, and not resolved by
quietly reinterpreting the ambiguous case in whichever direction the
already-seen results make more convenient.

---

## 4D-2 — Evaluate every RULE candidate

**Work:** for each of the 2 real RULE candidates Step 13 produced
(both from the Microsoft documents — RULE produced 0 for the other 6,
per `EDGAR_BASELINE_FINDINGS.md`'s already-frozen baseline), classify
against 4D-1's frozen contract and ground truth using only the six
categories 4D-1a defines (TP, TP-with-field-error, FP, OUT_OF_SCOPE,
MISS, WRONG_REJECTION — RULE has no validation-rejection path of its
own the way SEMANTIC does, so WRONG_REJECTION is not expected to apply
here, but is not ruled out by assumption either).

Also explicitly record, per document, which ground-truth claims RULE
**missed** (6 of 8 documents, per the existing frozen baseline) and
*why*, categorized by the already-documented reason
(`EDGAR_BASELINE_FINDINGS.md`'s own table: "is located in" ≠ "is
headquartered in"; "was incorporated in... in YEAR" ≠ "was founded on
DATE"; passive appointment constructions; no ISO date in the claim
sentence). This step does not re-derive these reasons from scratch —
it re-confirms them against 4D-1's ground truth and carries them
forward.

**Verification:** a table, one row per RULE candidate plus one row per
MISS, using exactly the six frozen categories (no ad hoc classification
invented at this step), with the specific reason for any MISS or
TP-with-field-error.

---

## 4D-3 — Evaluate every SEMANTIC candidate

**Work:** for each of the 21 real SEMANTIC candidates Step 13 produced
(the ones that survived to become a `Fact`, and — separately — the 4
that were rejected), classify against 4D-1's frozen contract using
exactly the six categories (TP, TP-with-field-error, FP, OUT_OF_SCOPE,
MISS, WRONG_REJECTION). The OUT_OF_SCOPE category exists specifically
for this step: a true, source-grounded statement outside the three
tracked claim types is OUT_OF_SCOPE, not FP, decided by the ontology
4D-1a already froze — not re-litigated per candidate here.

**Specifically, using Step 13's actual recorded output as the raw
material** (not re-running the extraction):
- Apple headquarters: 1 accepted candidate (`"is located in"`) — TP
  with predicate drift (per `SEMANTIC_EXTRACTION_RESULTS.md` §4.4's
  already-documented finding), plus 2 more accepted candidates
  (operational/facilities statements) — classified as OUT_OF_SCOPE
  per 4D-1a's frozen ontology, not FP, since they are true statements
  about a company's facilities, just not one of the three tracked
  claim types.
- Apple cybersecurity (control): 4 accepted candidates, all about "The
  Company's Head of Corporate Information Security" — per 4D-1a's
  ontology, these are OUT_OF_SCOPE (a person's professional background
  is not headquarters/founding/role-appointment), not FP. This is the
  exact case the ontology refinement exists to handle correctly: this
  document asserting 0 ground-truth claims does not mean these 4
  candidates are false — they are true, simply untracked.
- Apple talent risk (control): 1 accepted candidate
  (`'experienced personnel' / 'are located in' / 'Silicon Valley'`)
  plus 3 rejected (`SUBJECT_EQUALS_OBJECT`) — the surviving candidate
  is OUT_OF_SCOPE under 4D-1a (a general-workforce location statement,
  not a company-headquarters claim), not FP.
- Tenet incorporation: the accepted candidate's `effective_from_text`
  — per Step 13's raw output, no date was captured. 4D-1's ground
  truth (now independently confirmed from the real 10-K text: "was
  incorporated in the State of Nevada **in 1975**") means this is
  TP-with-field-error under 4D-1a's date precision policy — a
  **repeat of the exact Step 6 dropped-date finding**, not a new
  failure mode — record it as such, not as newly discovered.
- ICT, 8x8 CFO appointments: both already-known clean recoveries, per
  `SEMANTIC_EXTRACTION_RESULTS.md` — re-confirm as TP against 4D-1's
  ground truth rather than assuming the prior finding still holds
  verbatim.
- Microsoft clean clause / compound: already-known agreement and
  correct-split results — re-confirm, don't re-derive.

**Verification:** same table shape as 4D-2, covering all 21 SEMANTIC
candidates plus the 4 rejections (each rejection classified
specifically as WRONG_REJECTION if it discarded a real ground-truth
claim, or correctly-rejected otherwise — a rejection is only scored
WRONG_REJECTION, never folded into MISS, so 4D-5's metrics can
distinguish "the extractor never found this claim" from "the extractor
found it and the validation layer wrongly discarded it," which are
different problems requiring different fixes).

---

## 4D-4 — Evaluate validation rejections specifically

**Work:** a focused pass over just the 4 rejections from Step 13's run
(1 `UNVERIFIABLE_SOURCE_SPAN` on the cybersecurity document, 3
`SUBJECT_EQUALS_OBJECT` on the talent-risk document), using 4D-1a's
frozen contract to answer precisely: is each one correctly-rejected
(it was never a tracked-ontology ground-truth claim at all — including
the case where it would have been OUT_OF_SCOPE even if accepted, which
is a stronger and more precise finding than just "correctly rejected")
or `WRONG_REJECTION` (it corresponded to a real, tracked-type
ground-truth claim the validation layer discarded)? This is a
narrower, more careful pass than 4D-3's broader table, specifically
because a validation layer that's "accidentally right" for the wrong
reason is a real risk worth checking explicitly rather than assuming
correctness from the rejection reason alone — a rejection reason
firing correctly (the span really was unverifiable, the subject really
did equal the object) is not automatically the same thing as the
rejection being the right outcome for this evaluation's purposes if,
despite that, the underlying text happened to also support a real,
differently-phrased ground-truth claim nearby that this rejection
doesn't actually touch.

**Verification:** for each of the 4, the real source span, the real
candidate fields, and an explicit classification
(correctly-rejected-not-ground-truth /
correctly-rejected-would-be-out-of-scope / `WRONG_REJECTION`) with
reasoning, feeding directly into 4D-3's `WRONG_REJECTION` rows rather
than existing as a separate, disconnected judgment.

---

## 4D-5 — Precision / recall / F1 (or equivalent), computed per extractor

**Work:** using 4D-2's and 4D-3's completed tables, compute, separately
for RULE, SEMANTIC, and the combined HYBRID output (everything that
survived to become a `Fact`, from either origin), **two versions of
each metric, per the frozen policy below — never one arbitrary blend
decided after seeing which version flatters which extractor:**

```text
STRICT (TP-with-field-error counts as a miss on the recall side and
is excluded from the precision numerator — a field error is not a
successful recovery):
  Precision_strict = TP / (TP + FP)
  Recall_strict    = TP / (TP + MISS + TP-with-field-error)

LENIENT (TP-with-field-error counts as recovered for recall, and as
correct for precision — crediting the extractor with finding the
right claim even though a field needs correction):
  Precision_lenient = (TP + TP-with-field-error) / (TP + TP-with-field-error + FP)
  Recall_lenient    = (TP + TP-with-field-error) / (TP + TP-with-field-error + MISS)

F1 = 2 * (Precision * Recall) / (Precision + Recall), computed for
     both STRICT and LENIENT.
```

`OUT_OF_SCOPE` and `WRONG_REJECTION` never enter either formula as
written above — per 4D-1a's frozen contract, `OUT_OF_SCOPE` is not
scored against precision/recall at all (it is reported as a separate
over-extraction-rate figure in 4D-6, not blended into these numbers),
and `WRONG_REJECTION` is reported as its own count (how many real
claims the validation layer discarded) rather than silently merged
into either MISS or FP, since it is a different failure (found, then
wrongly discarded) from either.

**Verification:** the exact comparison table your message specified,
extended with the frozen categories:

```text
                    RULE       SEMANTIC       HYBRID (raw)   HYBRID (dedup'd)
TP
TP-with-field-error
FP
OUT_OF_SCOPE
MISS
WRONG_REJECTION
Precision (strict / lenient)
Recall (strict / lenient)
F1 (strict / lenient)
```

filled in with real counts from 4D-2/4D-3/4D-4. "HYBRID (raw)" is the
union of RULE's and SEMANTIC's surviving Facts exactly as Step 13
produced them, including duplicate-materialization — a real-world
claim both extractors correctly recovered appears as 2 TPs in this raw
count. "HYBRID (dedup'd)" collapses any such pair to 1 TP for scoring
purposes, per 4D-1a's duplicate-handling rule — the two columns are
reported side by side, explicitly labeled, specifically so a reader
can see the raw-count inflation directly rather than it being hidden
inside a single HYBRID number.

---

## 4D-6 — Analyze failure modes, each kept separate

**Work:** revisit each already-named failure mode from across this
project's history, using 4D-2–4D-5's real, fresh evaluation evidence
rather than re-asserting the prior finding unchanged:

1. **Microsoft compound sentence** — RULE's known object-capture
   defect vs. SEMANTIC's correct split. Still present? Still the same
   shape?
2. **Talent-risk over-extraction** — the `SUBJECT_EQUALS_OBJECT` and
   bare-copula rejections exist specifically to catch this. Did they
   catch all of it this time, per 4D-4's finding?
3. **Self-reference / fragmentary claims** — same question, distinct
   from over-extraction in general (a fragment can be real-sounding
   without being self-referential).
4. **Predicate normalization** — of the predicate-drift cases found in
   4D-3, how many are covered by the Step 7 table (1 entry) vs. still
   drifting? Is the single-entry table's scope still justified by this
   fresh evidence, or does the evidence now support a second entry
   (which would be a new, separate, explicitly-reviewed proposal, not
   decided here)?
5. **Dropped dates** — Tenet's 1975 is the known case; are there
   others in this 8-document, post-Step-8-bare-year-parser run? (Note:
   Step 8 added `%Y` parsing to the deterministic parser, but that
   only helps if `effective_from_text` is populated at all — Tenet's
   case shows it still isn't, meaning Step 8's parser extension cannot
   fix a case where the date never reaches the candidate in the first
   place. This is a real, precise distinction to draw out here.)
6. **Source-span verification** — did it do its job (catch real
   provenance problems) without also being mistaken for a correctness
   check, per its own documented limitation?
7. **RULE's narrow pattern coverage** — quantified now: of 4D-1's total
   ground-truth claim count across all 8 documents, what fraction did
   RULE's 4 fixed patterns structurally have no path to matching at
   all (as opposed to matching incorrectly)?

**Verification:** one subsection per failure mode, each with its own
fresh count from this evaluation, explicitly marked as "consistent
with prior finding" or "diverges from prior finding, here's how."

---

## 4D-7 — RULE vs. SEMANTIC vs. HYBRID, the actual comparison

**Work:** synthesize 4D-5's table and 4D-6's analysis into a direct,
stated comparison: for this 8-document sample, does HYBRID's recall
improvement over RULE alone justify SEMANTIC's precision cost (false
positives, fragmentary extractions, predicate drift)? This is not a
yes/no verdict handed down by this plan — it's the output 4D-7
produces from real numbers, written once those numbers exist.

**Verification:** a short written comparison, grounded in 4D-5's table
cell-by-cell, not a restatement of Phase 3's original (correct, but
now-supersedable) analysis.

---

## 4D-8 — Analyze duplicate Facts

**Work:** using Step 13's real 19-Fact, 8-document result, identify
every case where RULE and SEMANTIC's surviving Facts describe the same
real-world claim (the Microsoft clean clause is the one confirmed case
in this sample; check the other 7 documents too, even though RULE
produced 0 candidates for 6 of them — the question is specifically
about *materialized Fact* overlap, not just candidate-count overlap).
For each confirmed duplicate pair, record: do they agree exactly
(field-identical, as Steps 10/12 already found for the Microsoft case),
or do they differ in some field (which would be a *disagreement*, not
a duplicate, and a legitimate Stage 3 contradiction candidate instead)?

**Three distinct things this step keeps structurally separate, not
collapsed into one "duplicate" label:**

```text
Same real-world claim        -- a fact about the world (e.g. "Mr.
                                 Thompson is Virtual Instruments' CEO")
        ≠
Same extraction event        -- RULE and SEMANTIC are two different
                                 processes that each independently
                                 noticed that same real-world claim
        ≠
Same Fact identity            -- fact_id is always distinct per
                                 origin (uuid4(), per the locked
                                 contract) -- this is never shared,
                                 by design, and this step does not
                                 treat that as a defect to flag
```

This step's job is to confirm and count instances of the first
category (same real-world claim, surfaced through two different
extraction events) — that is already an established, repeatedly
confirmed fact of the current architecture (Steps 10, 12, and now this
8-document pass all agree on it), not something 4D-8 is newly
discovering or needs to re-litigate. What 4D-8 adds beyond Steps 10/12
is coverage: a full count across all 8 documents, not just the one
previously-tested fixture.

**Verification:** an explicit list of every duplicate pair found in
this 8-document sample, each confirmed field-identical or flagged as
actually-a-disagreement, with the three-layer distinction above stated
once at the top of the findings so 4D-9 can refer back to it rather
than re-deriving it.

---

## 4D-9 — Decide whether deduplication is warranted

**The question this step answers is narrower than it might sound, and
the narrowing matters:** 4D-8 (and Steps 10/12 before it) have already,
repeatedly, established *that* RULE and SEMANTIC can produce
field-identical Facts for the same real-world claim, with distinct
`fact_id`s and distinct extraction-event provenance, materializing as
separate graph nodes. That is settled, not open. What remains genuinely
open, and what 4D-9 actually decides, is the *should*:

> Given that this happens, **should** SAGE collapse these logically
> equivalent Facts into one graph representation — trading away the
> "two independent sources agree" provenance signal 4B section 6 named
> as a possibly legitimate thing to preserve — or does the current
> behavior (both origins visibly present in the graph) have real value
> worth keeping as-is?

**Work:** using 4D-8's real findings (not Steps 10/12/13's prior,
narrower single-fixture or single-pass observations alone, though
those remain valid supporting evidence), make the actual architectural
recommendation addressing the *should*, not re-arguing the *does*. If
the recommendation is "yes, deduplicate," name the likely shape (a
post-validation, pre-Stage-6 dedup step, keyed on matching claim key +
contested value across origins, already named as the likely shape in
4B section 6) only as a direction for a future, separate
implementation phase to evaluate — not as something this step designs
in detail.

**This step produces a recommendation, not an implementation.** Per
your explicit instruction, Phase 4D does not implement deduplication
even if 4D-9 concludes it's warranted — that becomes a new, separate,
explicitly-authorized implementation phase (Phase 4E, or similar),
decided on its own.

**Verification:** a written recommendation with its reasoning drawn
directly from 4D-8's table, stating explicitly what 4D-9 is **not**
deciding (the exact mechanism, if any future step builds it) as well as
what it is (whether the problem is real and worth solving).

---

## 4D-10 — Freeze Phase 4D findings, decide the next architectural step

**Work:** a single frozen document, `PHASE4D_EVALUATION_FINDINGS.md`,
consolidating 4D-1 through 4D-9's real results, closing with an
explicit statement of what the evidence supports doing next —
extraction improvements, validation improvements, predicate/date
normalization expansion, deduplication (per 4D-9's recommendation), a
larger EDGAR sample, or some stated combination — **as a proposal for
the next phase, not an automatic trigger of it.** Per the same
discipline Phase 4C's own plan used: freezing Phase 4D's findings does
not itself authorize starting whatever comes next.

**Verification:** the completed `PHASE4D_EVALUATION_FINDINGS.md`
document itself, committed and tagged (`phase4d-complete` or
equivalent), is the deliverable.

---

## Appendix A — a note on how this plan was drafted

While drafting 4D-1 above, the Tenet Healthcare 10-K's real company-
information sentence was looked up directly (SEC EDGAR filings, FY2017
through FY2019, consistent across years): **"Tenet Healthcare
Corporation was incorporated in the State of Nevada in 1975."** This
independently confirms two things this plan relies on: first, that the
fixture's underlying real claim genuinely does include an explicit
1975 date, which 4D-1 should record as ground truth; second, that Step
13's real run — in which SEMANTIC's Tenet candidate carried no
`effective_from_text` at all — is a real, continuing instance of the
dropped-date finding, not a fixture artifact or a new failure. This one
lookup is not a substitute for 4D-1's full, deliberate ground-truth
pass across all 8 documents — it's offered here only as a concrete
demonstration of the kind of independent source-text confirmation 4D-1
calls for, and as a starting data point Sagar can use or re-verify
directly.

---

## What this plan deliberately does not do

- Does not score Step 13's 19 Facts. That is 4D-2 through 4D-5's job,
  not this document's.
- Does not decide deduplication. That is 4D-9's job.
- Does not expand the EDGAR sample beyond the frozen 8 documents — a
  larger sample is a legitimate possible *output* of 4D-10's
  recommendation, not something this plan starts.
- Does not change any extraction, validation, or Stage 2–6 code.
- Does not auto-authorize whatever 4D-10 recommends as the next step.

This document is a plan for review, not an implementation, and not an
evaluation. No scoring has been performed to produce it.

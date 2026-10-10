# Phase 4C Step 6 — Corrected Semantic Extraction Run: Results

**Status: frozen results record. No extractor code, validation rule, or
prompt was modified in response to these results. This document records
what actually happened in one real run, against the same 8 real EDGAR
excerpts Phase 2 used — nothing here is a prediction, and nothing here
is treated as grounds to change Phase 4A or 4B's locked decisions.**

**Sequencing note:** per explicit instruction, this document is written
and frozen *before* Step 7 begins, so that Step 6's evidence is not
mixed with whatever Step 7 (predicate normalization) subsequently does.
Anyone reading this later should be able to tell exactly what Step 6
observed, independent of anything built on top of it afterward.

---

## 1. Baseline reference

**Compared against:** `SEMANTIC_EXTRACTION_RESULTS.md` (Phase 2's frozen
SEMANTIC run), same 8 real EDGAR excerpts, same order:

1. Apple — Properties (headquarters)
2. Apple — Cybersecurity (control)
3. Apple — Talent Risk (control)
4. Tenet — Incorporation
5. International Commercial Television — CFO Appointment
6. 8x8, Inc. — CFO Appointment
7. Microsoft — Clean Clause
8. Microsoft — Verbatim Compound (the known RULE corruption)

**What changed between Phase 2 and this run, and nothing else:**

- The system prompt's `effective_from_text` instruction was narrowed per
  `PHASE4B_PRODUCTION_CONTRACT.md` section 4, Fix 1 — the model is now
  told a date must belong to the same clause/sentence as the specific
  claim, with the cross-clause example (`"founded in 1980, ... appointed
  ... in 2024"`) given verbatim, and told explicitly that `null` is the
  expected, correct answer when no such date exists.
- The shared deterministic validation layer now also rejects an empty or
  whitespace-only `source_span` (Phase 4C Step 4b), closing a gap in
  `EMPTY_REQUIRED_FIELD` enforcement that existed throughout Phase 2 and
  Steps 1–5. This was a correction to the already-specified 4B contract,
  not a new rule, and was reviewed and approved before Step 6 began.
- The `SUBJECT_EQUALS_OBJECT` and `BARE_COPULA_PREDICATE` rejection rules
  (Phase 4C Step 4) were active for this run, exactly as locked in 4A/4B
  — unchanged from how they were specified and tested in Steps 4–5.

**No other change.** RULE, `candidate.py`'s core validation order,
`claim_policy.py`, and every Stage 2–6 module are exactly as frozen.
Nothing in this document's findings has been used to modify any of them.

**Model and call conditions:** `meta/llama-3.2-11b-vision-instruct` via
NVIDIA NIM, one real API call per document, `temperature=0`, no
`response_format` enforcement (per `nvidia_client.py`'s existing,
unmodified caveat that NIM models inconsistently honor it). Identical
call conditions to what Phase 2 used, apart from the one prompt edit
above.

---

## 2. Per-item results

### 2.1 Compound-sentence recovery — still successful

**Result: unchanged from Phase 2.** Both facts recovered correctly:

```text
"Mr. Thompson" -- "is the chief executive officer of" -- "Virtual Instruments"
"Mr. Thompson" -- "has a less-than-10% beneficial interest in" -- "Virtual Instruments"
```

`object == "Virtual Instruments"` on the first fact — the exact
correction RULE's frozen compound-sentence defect fails to make on this
sentence. This is the same genuine success Phase 2 recorded in section
3.8, reproduced here under the corrected prompt. Expected: Fix 1 targets
date attribution, not clause-splitting, so no change here is either a
surprise or a validation of anything new.

### 2.2 Talent-risk fragments — same rejection count, different rule fired

**Phase 2:** 6 fragments produced; 3 had a bare-copula predicate
(`"is" -- "a key personnel"`, three times) that would trip
`BARE_COPULA_PREDICATE` under Steps 4–5's rules (Phase 2 predates those
rules, so nothing was actually rejected at the time — this is the
Step 4/5 characterization test's finding, not a Phase 2 result).

**This run:** 4 candidates produced from this document, not 6.

```text
ACCEPTED: "experienced personnel" -- "are located in" -- "Silicon Valley"
REJECTED (SUBJECT_EQUALS_OBJECT): "Chief Executive Officer" -- "is a key personnel" -- "Chief Executive Officer"
REJECTED (SUBJECT_EQUALS_OBJECT): "executive team" -- "is a key personnel" -- "executive team"
REJECTED (SUBJECT_EQUALS_OBJECT): "other highly skilled employees" -- "is a key personnel" -- "other highly skilled employees"
```

**The finding:** the model phrased the predicate as `"is a key
personnel"` rather than the bare `"is"` Phase 2 saw. `"is a key
personnel"` is not in `_BARE_COPULA_PREDICATES` (`{"is", "are", "was",
"were"}`), so `BARE_COPULA_PREDICATE` did not fire — **0 rejections
via that rule this run.** All three fragments were instead rejected by
`SUBJECT_EQUALS_OBJECT`, because the model repeated the subject text
verbatim as the object (e.g. `"Chief Executive Officer"` as both
subject and object). Net effect: **the same 3 fragments were still
caught, but by a different rule than the one written for this exact
shape.** This is recorded as a real, load-bearing observation, not
smoothed into "the rejection count matched so nothing changed."

One fragment Phase 2 recorded as noise —
`"the Company's team members" -- "depends on the talents and efforts of"
-- "its future success"` — did not appear as a candidate at all in
this run. No explanation is available from this run's data; recorded as
absent, not investigated further here.

`"experienced personnel" -- "are located in" -- "Silicon Valley"` was
accepted, the same way Phase 2's near-identical
`"key personnel" -- "are located in" -- "Silicon Valley"` was accepted
and remains accepted under the Step 4 characterization test (which
already documents that the bare-copula rule catches 4 of 6 real
talent-risk fragments, not 6 of 6). This run's acceptance of the same
kind of fragment is consistent with that already-documented limit, not
a new gap.

### 2.3 David Stoll self-reference — not reproduced

**Phase 2:** `"David Stoll" -- "replacing" -- "David Stoll"` — subject
and object identical, the exact case `SUBJECT_EQUALS_OBJECT` was written
to catch.

**This run:** the equivalent candidate was
`"David Stoll" -- "replacing" -- "chief financial officer of 8x8, Inc."`
— **accepted.**

```text
ACCEPTED: "James Sullivan" -- "has been appointed chief financial officer of" -- "8x8, Inc."
ACCEPTED: "David Stoll" -- "replacing" -- "chief financial officer of 8x8, Inc."
```

**The finding, stated precisely:** Phase 2's specific self-reference
failure did not recur in this run. Subject and object are no longer
identical strings, so `SUBJECT_EQUALS_OBJECT` had nothing to catch, and
correctly did not fire.

**This is recorded as a non-event for that rule, not as evidence the
rule works or doesn't.** See section 3 below — this distinction is
important enough that it is called out separately rather than folded
into this item's narrative.

**The new candidate itself is recorded as accepted but open,
not as a failure**, per instruction, since no rule in the locked design
targets this shape. Observations, without a proposed fix:
- The predicate `"replacing"` is a single bare word, but not one of the
  four locked bare copulas, so `BARE_COPULA_PREDICATE` does not apply to
  it by design.
- The object, `"chief financial officer of 8x8, Inc."`, reads as a role
  description rather than a person, place, or date — structurally odd
  for a `replacing` claim, but nothing in the locked validation layer
  has a rule against an object shaped like a role description.
- Whether this candidate is factually useful, misleading, or harmless is
  not decided here. It is recorded as a new, distinct observation from
  Phase 2's David Stoll finding, not a recurrence of it.

### 2.4 Date recovery — Tenet improved, ICT unchanged

**ICT:** unchanged from Phase 2 — the explicit date is captured and used.

```text
"Ryan LeBon" -- "was appointed Chief Financial Officer of" -- "the Company"
  effective_from_text='January 1, 2014'  (fell back to extracted_at: False)
```

**Tenet:** improved at the prompt level, unchanged at the parser level.

```text
"Tenet Healthcare Corporation" -- "was incorporated in" -- "the State of Nevada"
  effective_from_text='1975'  (fell back to extracted_at: True)
```

Phase 2 recorded `effective_from_text` as `null` for this fact — a
prompting gap, per 4B section 4's own diagnosis. This run, the model
correctly populated `effective_from_text='1975'`, tied to the correct
claim. **Fix 1 (the prompt correction) is confirmed working for this
case.** `effective_from` still falls back to `extracted_at`, because the
deterministic parser does not yet accept a bare 4-digit year — that is
Fix 2, explicitly scoped to Step 8, not this step. This is the expected,
already-planned intermediate state: the text now carries the
information; the parser to consume it does not exist yet.

A second Tenet candidate was also produced this run
(`"Tenet Healthcare Corporation" -- "file" -- "annual, quarterly and
current reports..."`) — boilerplate/procedural language, the same kind
Phase 2 recorded as present but not a claim type SAGE's reasoning stages
are built around (Phase 2 section 3.4's second fact, same character).

### 2.5 Predicate behavior — drift increased, including on a control document

Phase 2 recorded predicate drift on 4 of 8 documents (headquarters,
Tenet, ICT, 8x8). This run shows drift more broadly:

```text
apple_10k_2024_properties.txt        'is located in'
apple_10k_2024_properties.txt        'owned or leased facilities and land'
apple_10k_2024_properties.txt        'are in good operating condition'
apple_10k_2024_cybersecurity.txt     'has extensive knowledge and skills gained from'
apple_10k_2024_cybersecurity.txt     'has served in leadership positions at'
apple_10k_2024_cybersecurity.txt     "has led the Company's Information Security team"
apple_10k_2024_talent_risk.txt       'are located in'
tenet_10k_incorporation.txt          'was incorporated in'
tenet_10k_incorporation.txt          'file'
ict_8k_cfo_appointment.txt           'was appointed Chief Financial Officer of'   [matches RULE]
ict_8k_cfo_appointment.txt           'continues as President of'
8x8_8k_cfo_appointment.txt           'has been appointed chief financial officer of'
8x8_8k_cfo_appointment.txt           'replacing'
msft_def14a_thompson_ceo.txt         'is the chief executive officer of'         [matches RULE]
msft_def14a_thompson_ceo_verbatim_compound.txt  'is the chief executive officer of'   [matches RULE]
msft_def14a_thompson_ceo_verbatim_compound.txt  'has a less-than-10% beneficial interest in'
```

**13 of 16 accepted predicates are SEMANTIC's own phrasing; 3 match a
RULE canonical shape.** The notable new observation, not present in
Phase 2's findings: the Apple cybersecurity document — a **control**
document, one RULE correctly extracts nothing from, and one Phase 2
recorded as a `MALFORMED_RESPONSE` (not a set of accepted facts) — this
run produced 3 accepted facts from it (plus 1 rejection). None of these
predicates match any RULE shape, so per the locked 4B section 3 table
they fall through to `SUBJECT_ANCHORED` with their own literal
predicate as claim type, unnormalized — the correct behavior per the
locked design, but a new instance of a previously-quiet control
document now producing accepted output.

### 2.6 Source-span validity — 16/16

Every one of the 16 accepted facts has a `source_span` that is a real,
verified substring of its document's raw text — checked twice: once by
`validate_and_build_fact` itself (which would have rejected any failure
here before construction), and once again independently by this
script's own mechanical re-check against the raw text it read. Zero
anomalies. Consistent with Phase 2 (which also recorded 0 span-related
rejections) and with Step 4b's fix now closing the empty-span gap that
existed throughout Phase 2's run.

### 2.7 Candidate acceptance/rejection counts

| Document | Accepted | Rejected | Status |
|---|---|---|---|
| Apple properties | 3 | 0 | OK |
| Apple cybersecurity (control) | 3 | 1 | OK |
| Apple talent risk (control) | 1 | 3 | OK |
| Tenet incorporation | 2 | 0 | OK |
| ICT CFO appointment | 2 | 0 | OK |
| 8x8 CFO appointment | 2 | 0 | OK |
| MS clean clause | 1 | 0 | OK |
| MS compound | 2 | 0 | OK |
| **Total** | **16** | **4** | — |

**20 total candidates this run**, versus Phase 2's smaller per-document
counts (e.g. Apple properties: 2 candidates in Phase 2 vs. 3 here;
Apple cybersecurity: 0 candidates plus 1 `MALFORMED_RESPONSE` in Phase 2
vs. 4 candidates here). **Zero `MALFORMED_RESPONSE` results this run**,
versus 1 in Phase 2 (the Apple cybersecurity document). Both counts are
recorded as real differences between the two runs; no explanation for
the volume or malformed-rate change is asserted here beyond what the
data shows.

---

## 3. Explicit distinction between observations and conclusions

This section exists because it is easy to misread section 2.3 as either
"the fix works" or "the fix doesn't work," and neither reading is
supported by this run.

**Observation:** in Phase 2, one specific candidate had `subject ==
object` (`"David Stoll"` / `"David Stoll"`), and it passed every check
that existed at the time, since `SUBJECT_EQUALS_OBJECT` did not exist
yet. In this run, under the same document and the corrected prompt, the
model produced a structurally different candidate for the same
real-world sentence — one where subject and object are not equal.

**What this does NOT establish:**
- It does not show that `SUBJECT_EQUALS_OBJECT` is unnecessary. The rule
  exists to catch subject==object candidates; none occurred in this run
  to test it against.
- It does not show that `SUBJECT_EQUALS_OBJECT` is insufficient. The
  rule was not exercised by this specific failure mode this time, which
  is different from the rule failing to catch something it saw.
- It does not show the underlying model behavior "improved." A model
  producing a different wrong answer is not the same as a model
  producing a right answer, and the new candidate (section 2.2's item)
  is itself of open, undetermined quality.

**What this DOES establish:** this run generated zero data points on
whether `SUBJECT_EQUALS_OBJECT` correctly handles a live, real
self-reference case, because no live self-reference case occurred. The
rule remains validated against Phase 2's frozen historical case (via the
Step 4/5 test suite, which uses that exact triple verbatim) but not
against any new live occurrence. This is a gap in this run's evidence,
not a property of the rule.

The same discipline applies to section 2.2's finding:
`BARE_COPULA_PREDICATE` catching 0 fragments this run is not evidence
the rule is broken — the fragments simply weren't shaped the way the
rule checks for, this time. `SUBJECT_EQUALS_OBJECT` catching all 3
instead is not evidence that rule is now "the important one" going
forward — it is what happened to fire, given what the model happened to
produce, in this one run.

---

## 4. No architecture changes

**Nothing in this document has been used to modify:**
- Phase 4A's locked architecture decision (hybrid, independent
  RULE+SEMANTIC execution, shared deterministic validation).
- Phase 4B's locked production contract (candidate shape, validation
  order, predicate normalization table, date handling split between
  prompt and parser, duplicate-handling policy, reproducibility scope).
- `contracts/fact_schema.py` or any Stage 2–6 module — none were opened
  for this step.
- `candidate.py`'s validation rules or their order (Steps 4 and 4b's
  code is exactly as committed before this run; this run only exercised
  it against new live data).
- `claim_policy.py` or any Stage 3 shape-matching logic.

The single code change that produced this run's different behavior from
Phase 2 is the one locked, already-approved prompt edit (section 1
above) — a Phase 4C-scoped change 4B itself specifies, not a new
decision made in response to this run's findings.

Per the standing instruction that governed this step: the purpose of
Step 6 was measurement against the already-locked design, not
architecture revision. Nothing below is treated as license to revise
Phase 4A or 4B; it is a record for whoever later reviews Phase 4D or any
future scope decision.

---

## 5. Open findings

Carried forward, unresolved by this document, not to be treated as
implicitly assigned to any specific future step unless separately
authorized:

1. **General semantic over-extraction remains unresolved.** Phase 4A
   item 3 already named this as explicitly open, informed by future
   evidence rather than solved now. This run adds one more data point
   (the cybersecurity control document producing 3 accepted facts) but
   does not close the question.
2. **Predicate normalization coverage remains limited.** The locked 4B
   table has exactly one entry. This run shows 13 of 16 accepted
   predicates as SEMANTIC's own phrasing, most with no RULE counterpart
   to normalize toward even if the table were extended. Whether this
   is a problem worth solving, and how, remains open per 4B section 3's
   own scoping.
3. **Bare-year date parsing remains pending Step 8.** Confirmed directly
   by this run's Tenet result: the prompt-side fix (Fix 1) works: the
   text is now captured. The parser-side fix (Fix 2, `%Y` format) is
   still needed to make full use of it, exactly as 4B already planned.
4. **The `"David Stoll" -- "replacing" -- "chief financial officer of
   8x8, Inc."` candidate is recorded, not resolved.** Per instruction,
   this requires investigation only if later evidence (e.g. a Phase 4D
   re-run producing more instances of this or a similar shape) warrants
   it — not investigated further in this document.

---

## 6. What this document does NOT do

- Does not modify RULE, SEMANTIC, `candidate.py`, `claim_policy.py`, or
  any contract in response to these findings.
- Does not propose or begin any fix for the open findings in section 5.
- Does not treat 8 documents, or this one run, as a statistically
  meaningful sample — this is what happened on this one real run against
  these 8 real excerpts, compared to what happened on Phase 2's one
  earlier real run against the same excerpts. Model output is not
  deterministic across calls; a third run could differ from both.
- Does not begin Step 7. Step 7 (predicate normalization handling) is a
  separate, later step, deliberately not started until this document is
  frozen, so Step 6's evidence is not mixed with Step 7's changes.

**Full raw data:** every candidate, accepted or rejected, with every
field, is in `verification/results/step6_semantic_edgar_report.json`,
generated by this same run. This document summarizes that file; the
file is the primary artifact.

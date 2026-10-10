# Phase 4D — Scoring Contract and Ground Truth

**Status: FROZEN. Per `PHASE4D_IMPLEMENTATION_PLAN.md` 4D-1's explicit
requirement, this document was written from the real, uploaded fixture
text alone (`fixtures/edgar/*.txt`, confirmed byte-for-byte from the
dump provided), without looking at Step 13's 19 Facts, 21 candidates,
or 4 rejections. Three genuine ambiguities surfaced while reading the
real text that the contract did not anticipate in the abstract; all
three have been resolved by Sagar's explicit decision, recorded below
in the Decision Record. No candidate scoring, extraction changes, or
4D-2 work has occurred as part of producing this document.**

---

## Part A — Scoring contract (4D-1a)

Restated here, verbatim in substance, from `PHASE4D_IMPLEMENTATION_PLAN.md`'s
already-frozen 4D-1a, so this single document is self-contained once
finalized.

### Tracked evaluation ontology

```text
1. Headquarters / location  ("is headquartered in" claim type)
2. Founding / incorporation  ("was founded on" claim type)
3. Role / appointment  ("is the {role} of" / "was appointed {role} of")
```

### Classification scheme

| Classification | Meaning |
|---|---|
| **TP** | Matches ground truth; every scored field correct. |
| **TP-with-field-error** | Matches ground truth; one or more fields wrong. |
| **FP** | Asserts a tracked-type claim the source doesn't support. |
| **OUT_OF_SCOPE** | True, source-grounded, but not one of the 3 tracked types. Never scored as FP. |
| **MISS** | Real tracked-type claim no candidate recovered. |
| **WRONG_REJECTION** | Validation layer rejected a candidate that corresponded to a real ground-truth claim. |

### Field-level policy

- **Exact-match rule:** case-sensitive, whitespace-normalized exact
  string match, unless a specific ground-truth entry below explicitly
  lists an accepted normalized form.
- **Predicate-shape rule:** a predicate matches the claim type if it
  preserves the real-world meaning of one of the 3 tracked types.
  Meaning-preserving surface variation scores **TP**, not
  TP-with-field-error, when the source itself establishes the relevant
  meaning (e.g. "is located in" when the source sentence explicitly
  says "headquarters" — the candidate is not inferring or guessing the
  headquarters meaning, the source states it directly). A
  meaning-changing variation is scored per the specific ground-truth
  entry. A predicate field error is reserved for cases where the
  candidate does not preserve the ground-truth meaning or otherwise
  misstates the tracked claim.
- **Date precision policy:** a date is correct if its captured
  precision matches the source's stated precision (bare year for a
  bare year, full date for a full date). A missing date where the
  source has one is TP-with-field-error.
- **Source-span rule:** not re-scored here — already mechanically
  enforced by `validate_and_build_fact`.
- **Duplicate handling:** RULE and SEMANTIC both producing a TP for the
  same ground-truth claim counts as 1 recovered claim for
  precision/recall, not 2.

---

## Part B — Ground truth, document by document (4D-1b)

### 1. `apple_10k_2024_properties.txt`

**Real text (verbatim, confirmed from the uploaded fixture):**
> The Company's headquarters is located in Cupertino, California. As
> of September 28, 2024, the Company owned or leased facilities and
> land for corporate functions, R&D, data centers, retail and other
> purposes at locations throughout the U.S. and in various places
> outside the U.S. The Company believes its existing facilities and
> equipment, which are used by all reportable segments, are in good
> operating condition and are suitable for the conduct of its
> business.

**Note on phrasing:** the earlier draft of this plan (and
`EDGAR_BASELINE_FINDINGS.md`'s own summary table) characterized this
document's miss as "'is located in' ≠ 'is headquartered in'" — framing
it as if the source text merely states a generic location. The real
sentence is more specific: **"The Company's headquarters is located
in Cupertino, California."** The word "headquarters" is explicitly in
the source. This is a genuine headquarters claim, not a generic
location claim that happens to resemble one.

**Ground-truth entry:**
```text
Claim type: Headquarters / location
Subject:    The Company  (i.e., Apple Inc., the filer)
Predicate:  is headquartered in
Object:     Cupertino, California
Source span: "The Company's headquarters is located in Cupertino, California."
```

**Decision 1 (resolved by Sagar):** because the source text itself
names "headquarters" explicitly, any candidate that captures subject=
"The Company" (or the explicitly accepted equivalent, "Apple Inc."),
object="Cupertino, California", with a predicate that preserves the
headquarters-location meaning (regardless of exact wording — "is
located in," "is headquartered in," "has its headquarters in") scores
**TP**, not TP-with-field-error. The predicate-shape rule's
meaning-preserving-surface-variation clause applies here precisely
because the source itself supplies the "headquarters" meaning —
SEMANTIC is not inferring or guessing that "is located in" means
headquarters; the sentence says so directly. Requiring the canonical
`"is headquartered in"` wording despite equivalent, source-confirmed
meaning would conflict with the predicate-shape rule as already
written, so this decision applies the existing rule rather than
creating an exception to it.

**RULE's miss, reconfirmed against the real text:** `extract_as_
candidates()` returns `[]` for this exact sentence (independently
re-run and confirmed). The reason is specifically that RULE's pattern
requires the literal string `"is headquartered in"`, and the real
sentence's structure — "[subject]'s headquarters is located in
[object]" — doesn't match that regex, regardless of the word
"headquarters" being present in the text. This is a regex-rigidity
miss, not a claim-type mismatch — worth stating precisely, since it's
a different, narrower characterization than "RULE doesn't track
generic locations."

**The second and third sentences** (facilities/equipment, operating
condition) are true statements but assert no headquarters, founding,
or role claim — not entered as ground truth, consistent with the
ontology.

---

### 2. `apple_10k_2024_cybersecurity.txt` (control)

**Real text (verbatim):**
> The Company's management, led by its Head of Corporate Information
> Security, has overall responsibility for identifying, assessing and
> managing any material risks from cybersecurity threats. The
> Company's Head of Corporate Information Security has extensive
> knowledge and skills gained from over 25 years of experience in the
> cybersecurity industry, including serving in leadership positions at
> other large technology companies and leading the Company's
> Information Security team since 2016.

**Ground truth: 0 tracked-type claims.** Confirmed by direct reading,
not inferred from the filename or from any extractor's prior output.
Precisely why each candidate sentence shape does *not* qualify:
- "Head of Corporate Information Security" is a title/role mentioned,
  but the role is never attached to a named person — there is no
  subject to anchor a role-appointment claim to (the role-holder is
  referred to only by title, never by name, anywhere in this excerpt).
  This is a different reason than "wrong claim type" — it's "no
  assertable triple exists at all" for the role-appointment type,
  even though a role is discussed.
- No company location or incorporation/founding claim appears anywhere
  in this excerpt.

**Any candidate asserting something about "the Head of Corporate
Information Security" having experience, skills, or responsibilities**
is, if source-grounded, **OUT_OF_SCOPE** (a true biographical/
operational statement, not a tracked claim type) — not FP, per the
frozen contract, and not a MISS on SAGE's side (there is no
role-appointment ground truth to miss, since no name is ever given).

---

### 3. `apple_10k_2024_talent_risk.txt` (control)

**Real text (verbatim):**
> Much of the Company's future success depends on the talents and
> efforts of its team members and the continued availability and
> service of key personnel, including its Chief Executive Officer,
> executive team and other highly skilled employees. Experienced
> personnel in the technology industry are in high demand and
> competition for their talents is intense, especially in Silicon
> Valley, where most of the Company's key personnel are located.

**Ground truth: 0 tracked-type claims.** The phrase "its Chief
Executive Officer" names a role but — exactly as in the cybersecurity
document — never names who holds it. No role-appointment triple is
assertable. "Silicon Valley" is mentioned as where "most of the
Company's key personnel are located" — this is a workforce-location
statement, not a company-headquarters claim (it doesn't say the
Company itself, as an entity, is headquartered there — it says where
employees are), so it is not entered as a headquarters ground-truth
claim either, even though it superficially resembles one.

**A candidate asserting "key personnel are located in Silicon Valley"**
is, if source-grounded, **OUT_OF_SCOPE** — true, but a workforce
statement, not a company-headquarters claim under the ontology.

---

### 4. `tenet_10k_incorporation.txt`

**Real text (verbatim):**
> Tenet Healthcare Corporation was incorporated in the State of Nevada
> in 1975. We file annual, quarterly and current reports, proxy
> statements and other documents with the SEC under the Securities
> Exchange Act of 1934, as amended.

**Ground-truth entry:**
```text
Claim type: Founding / incorporation
Subject:    Tenet Healthcare Corporation
Predicate:  was founded on  (real-world meaning: incorporated)
Object:     (legal jurisdiction: State of Nevada)
Date:       1975  (bare year — source states only the year, no month/day)
Source span: "Tenet Healthcare Corporation was incorporated in the State of Nevada in 1975."
```

Independently confirmed as the real, current SEC filing language during
this plan's own drafting (web search of Tenet Healthcare's 10-K
company-information section) — now additionally confirmed directly
from the uploaded fixture file itself, which matches exactly.

The second sentence (SEC filing/reporting boilerplate) is not a
tracked claim.

**Note carried forward, not re-decided:** per
`PHASE4B_PRODUCTION_CONTRACT.md` section 3's own reasoning, "was
incorporated in [STATE]" and "was founded on [DATE]" are treated as
different real-world events in general (incorporation is a legal
jurisdiction event; founding is when a company began existing) — this
ground-truth entry nonetheless uses the tracked "founding" claim type
for scoring purposes, consistent with how `EDGAR_BASELINE_FINDINGS.md`
originally framed this document's test (RULE's "was founded on"
pattern was the one being tested against it). A candidate that
captures the jurisdiction (Nevada) and the date (1975) accurately
should score TP for this ground-truth entry; the jurisdiction-vs-
founding-event distinction is noted here for 4D-6's failure-mode
analysis, not as a reason to exclude this claim from scoring.

---

### 5. `ict_8k_cfo_appointment.txt`

**Real text (verbatim):**
> Our Board of Directors has appointed Ryan LeBon as Chief Financial
> Officer of the Company, effective January 1, 2014, to serve in that
> capacity at the will of our Board of Directors. Richard Ransom, our
> previous Chief Financial Officer, continues as President of the
> Company.

**Ground-truth entry 1:**
```text
Claim type: Role / appointment
Subject:    Ryan LeBon
Predicate:  was appointed Chief Financial Officer of
Object:     the Company  (ICT -- International Commercial Television Inc.)
Date:       2014-01-01  (explicit, full date given: "effective January 1, 2014")
Source span: "Our Board of Directors has appointed Ryan LeBon as Chief Financial Officer of the Company, effective January 1, 2014..."
```

**Decision 2 (resolved by Sagar): include Richard Ransom's current
role as ground truth.** The second sentence states Richard Ransom
"continues as President of the Company" — a named person and a named
role, asserting current role-holding. SAGE's tracked role-appointment
claim type (per Stage 1's own two real patterns, `"is the {role} of"`
and `"was appointed {role} of"`) is agnostic to whether the role is
newly assumed or ongoing — the `"is the {role} of"` pattern itself
asserts present-tense role-holding, which "continues as President of"
is a real instance of. This decision applies consistently: the ontology
covers current role-holding as well as new appointments, not only one
or the other, for every document in this evaluation, not just this
one.

**Ground-truth entry 2:**
```text
Claim type: Role / appointment
Subject:    Richard Ransom
Predicate:  is the President of  (present-tense role-holding, matching
            the "is the {role} of" tracked shape -- "continues as" is
            a real-world synonym for this shape, not a different claim)
Object:     the Company
Date:       none stated
Source span: "Richard Ransom, our previous Chief Financial Officer, continues as President of the Company."
```

The historical phrase "our previous Chief Financial Officer" does not
create a separate current-role ground-truth claim for the CFO
position — it is explicitly past-tense and is not entered.

---

### 6. `8x8_8k_cfo_appointment.txt`

**Real text (verbatim):**
> On July 24, 2002, 8x8, Inc. issued a press release announcing that
> James Sullivan has been appointed chief financial officer of 8x8,
> Inc., replacing David Stoll.

**Decision 3 (resolved by Sagar): no expected effective date.** "On
July 24, 2002" is the date 8x8, Inc. *issued the press release* — the
document's own dateline — not a stated "effective [date]" for the
appointment itself, the way the ICT document explicitly says "effective
January 1, 2014." The source does not establish that the appointment
took effect on the announcement date; inferring it would introduce
unsupported temporal information, the same category of risk
`PHASE4B_PRODUCTION_CONTRACT.md`'s date-handling section already warns
about ("populating a wrong date is arguably worse than leaving it
null").

**Ground-truth entry:**
```text
Claim type: Role / appointment
Subject:    James Sullivan
Predicate:  was appointed Chief Financial Officer of
Object:     8x8, Inc.
Date:       no explicit effective date stated
Source span: "...James Sullivan has been appointed chief financial officer of 8x8, Inc., replacing David Stoll."
```

A candidate with `effective_from_text=None` (correctly falling back to
`extracted_at`) scores correctly (no field error) on the date
dimension for this claim. A candidate that asserts July 24, 2002 as the
appointment's effective date has added a temporal assertion the source
does not support and must not receive exact-date credit — classify it
under the field-error policy if the rest of the candidate otherwise
matches this claim. This is consistent with how
`EDGAR_BASELINE_FINDINGS.md`'s original characterization of this
document's miss ("passive construction, no ISO date in claim
sentence") already reads: this decision confirms, rather than
reinterprets, that prior finding.

**David Stoll, re-confirmed from the real text:** the sentence reads
"...James Sullivan has been appointed chief financial officer of 8x8,
Inc., **replacing David Stoll**." This supports exactly one
role-appointment ground-truth claim (James Sullivan → CFO → 8x8,
Inc.) — "replacing David Stoll" is background context for that one
claim (who the new CFO replaces), not an independently assertable
second claim with its own correct subject/object. This directly
explains, with the real source text in hand, why the already-known
SEMANTIC hallucination (`'David Stoll' / 'replacing' / 'David
Stoll'`, per `SEMANTIC_EXTRACTION_RESULTS.md` §3.6) is unambiguously
an FP: there is no real-world claim "David Stoll replaced David
Stoll" or any variant of it in the source — not even an adjacent true
claim it misattributed, the way a predicate-drift error would. This
one is a clean, confirmed FP, not a borderline case.

---

### 7. `msft_def14a_thompson_ceo.txt`

**Real text (verbatim):**
> Mr. Thompson is the chief executive officer of Virtual Instruments.

**Ground-truth entry:**
```text
Claim type: Role / appointment
Subject:    Mr. Thompson
Predicate:  is the chief executive officer of
Object:     Virtual Instruments
Date:       (none stated)
Source span: "Mr. Thompson is the chief executive officer of Virtual Instruments."
```

No ambiguity. Matches every prior finding in this project exactly
(Steps 10, 12, 13).

---

### 8. `msft_def14a_thompson_ceo_verbatim_compound.txt`

**Real text (verbatim):**
> Mr. Thompson is the chief executive officer of and has a
> less-than-10% beneficial interest in Virtual Instruments.

**Ground-truth entry 1 (the same CEO claim as document 7):**
```text
Claim type: Role / appointment
Subject:    Mr. Thompson
Predicate:  is the chief executive officer of
Object:     Virtual Instruments
Source span: "Mr. Thompson is the chief executive officer of and has a less-than-10% beneficial interest in Virtual Instruments."
```

**A second real-world fact is present in this sentence** ("has a
less-than-10% beneficial interest in Virtual Instruments") — but a
beneficial-interest/ownership-percentage claim is **not one of the 3
tracked claim types** (not headquarters, not founding, not role-
appointment). This is entered as context, not as a second
ground-truth entry: any candidate correctly capturing this fact (as
SEMANTIC's real output did:
`'Mr. Thompson' / 'has a less-than-10% beneficial interest in' /
'Virtual Instruments'`) is **OUT_OF_SCOPE**, not a second TP and not
a MISS if absent.

**RULE's known defect, re-confirmed against the real text:** the
compound sentence structure ("X is the {role} of **and** has a
beneficial interest in Y") is exactly what causes RULE's non-greedy
`object` capture to span past the first clause boundary, producing
`object = "and has a less-than-10% beneficial interest in Virtual
Instruments"` instead of `object = "Virtual Instruments"` — this
candidate, if produced, is **TP-with-field-error** against
ground-truth entry 1 (correct subject/predicate, wrong object text),
exactly matching `EDGAR_BASELINE_FINDINGS.md`'s already-frozen
corrupted-extraction finding.

---

## Summary — ground-truth claim count

| Document | Tracked claims (ground truth) | Notes |
|---|---|---|
| `apple_10k_2024_properties.txt` | 1 | Headquarters; equivalent phrasing ("is located in") scores TP per Decision 1 |
| `apple_10k_2024_cybersecurity.txt` | 0 | Control — confirmed |
| `apple_10k_2024_talent_risk.txt` | 0 | Control — confirmed |
| `tenet_10k_incorporation.txt` | 1 | Founding/incorporation, bare year 1975 |
| `ict_8k_cfo_appointment.txt` | 2 | Ryan LeBon appointed CFO; Richard Ransom continues as President (Decision 2) |
| `8x8_8k_cfo_appointment.txt` | 1 | James Sullivan appointed CFO; no explicit effective date (Decision 3) |
| `msft_def14a_thompson_ceo.txt` | 1 | Mr. Thompson is CEO of Virtual Instruments |
| `msft_def14a_thompson_ceo_verbatim_compound.txt` | 1 | Same CEO claim; beneficial-interest fact is OUT_OF_SCOPE |
| **Total** | **7** | Document-level ground-truth claim instances; the same real-world CEO claim appears in two separate source documents (7 and 8). |

---

## Decision record

1. **Apple headquarters phrasing — resolved:** a meaning-preserving
   predicate such as "is located in" scores **TP** when the source
   explicitly identifies the subject's headquarters and the other
   scored fields match. Applying the existing predicate-shape rule,
   not an exception to it.
2. **Richard Ransom "continues as President" — resolved:** included
   as a tracked current-role ground-truth claim. The role/appointment
   ontology covers current role-holding, not only new-appointment
   events, applied consistently across the evaluation.
3. **8x8 appointment date — resolved:** no expected effective date.
   July 24, 2002 is the press-release announcement date only and must
   not be inferred as the appointment's effective date.

All three decisions were made by Sagar, confirmed against the
recommendations in the prior review draft, and are incorporated above.
This document is committed and tagged as `PHASE4D_GROUND_TRUTH.md`.
4D-2 may now begin.

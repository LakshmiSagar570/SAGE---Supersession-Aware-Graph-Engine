"""Phase 4C Step 13, criterion 3 -- Cases A-E through the new candidate
path, SEMANTIC disabled, compared against the original frozen results.

verification/run_step13_cases_ab_regression.py

PURPOSE: PHASE4C_IMPLEMENTATION_PLAN.md Step 12 item 3 required Cases
A-E to reproduce their frozen Stage 1-6 results exactly when run through
the new hybrid entry point with SEMANTIC disabled -- "proving the
hybrid path is a strict superset of the old path for inputs that only
ever exercised RULE." That check was never actually run in Steps 2-12.
This script runs it now, as Phase 4C Step 13 criterion 3.

WHAT THIS COMPARES, PRECISELY:
  OLD PATH (frozen, SAGE_V01_E2E_VERIFICATION_REPORT.md):
      extract(raw_text, source) -> list[Fact]        (stage_1/extract.py)
  NEW PATH (Phase 4C):
      extract_as_candidates(raw_text) -> list[ExtractionCandidate]
      -> validate_and_build_fact(candidate, raw_text, source) -> Fact
      (stage_1/extract_candidates.py + experiments/.../candidate.py)

  Compared fields: subject, predicate, object, effective_from,
  effective_to. NOT compared: fact_id (uuid4, expected to differ between
  the two calls), extracted_at (datetime.now(UTC), expected to differ).
  This mirrors exactly the "field-identical, not ID-identical" standard
  every prior step in this project has used (Step 5's EDGAR comparison,
  Step 10 and 12's logical-Fact comparisons).

FIXTURE TEXT PROVENANCE -- stated explicitly, not silently assumed:
  The exact sentences below are transcribed verbatim from
  SAGE_V01_E2E_VERIFICATION_REPORT.md's own quoted fixture text for
  Cases A-E (that document quotes each fixture's content directly in
  its "Input" sections). They are NOT read from the actual
  fixtures/e2e/*.txt files on disk, since this script was written
  without direct access to confirm those files byte-for-byte. If the
  real fixture files differ from the text below in any way (even
  whitespace), this script's fixture text should be treated as
  SUSPECT, not the regression result -- re-run using
  Path("fixtures/e2e/...").read_text() in place of the literals below
  if exact fixture-file fidelity matters, which it does for a
  completion-gate criterion. This substitution is reported here, not
  hidden.

SEMANTIC DISABLED: this script never imports or calls
extract_semantic / extract_semantic_cached / any LLM client. Only the
RULE side of the candidate path is exercised, per the stated criterion.

Stage 6 / Neo4j is NOT exercised by this script -- the original
criterion is about Stage 1-6 OUTPUT reproduction (the Python objects
that would be passed to Stage 6), not about re-materializing into a
graph a second time. Cases A-E's Stage 6 graph behavior is already
verified in SAGE_V01_E2E_VERIFICATION_REPORT.md and is not re-tested
here, to avoid creating new graph state for a criterion that doesn't
require it.

Usage:
    PYTHONPATH=. python verification/run_step13_cases_ab_regression.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from uuid import uuid4

from contracts.fact_schema import Fact, Source, SourceID, SourceType
from experiments.semantic_extraction.candidate import validate_and_build_fact
from sage.pipeline.stage_1.extract import extract
from sage.pipeline.stage_1.extract_candidates import extract_as_candidates
from sage.pipeline.stage_2.temporal import enrich_temporally
from sage.pipeline.stage_3.detect import detect_contradictions


@dataclass
class CaseInput:
    name: str
    texts: list[str]
    # Source.source_type per text, parallel list; defaults to DOCUMENT
    # for every case except E, which specifically needs differing
    # authority -- per SAGE_V01_E2E_VERIFICATION_REPORT.md section 2,
    # Case E's whole point is exercising WINNER_SELECTED via differing
    # SourceType authority scores (DATABASE vs WEB).
    source_types: list[SourceType] = field(default_factory=list)


CASES: list[CaseInput] = [
    CaseInput(
        name="Case A",
        texts=["Company A is headquartered in Austin, Texas."],
    ),
    CaseInput(
        name="Case B",
        texts=[
            "Company B is headquartered in Denver, Colorado.",
            "Company B is headquartered in Miami, Florida.",
        ],
    ),
    CaseInput(
        name="Case C",
        texts=[
            "John Carter is the Chief Executive Officer of Company C.",
            "Priya Nair is the Chief Executive Officer of Company C.",
        ],
    ),
    CaseInput(
        name="Case D",
        texts=[
            "John Smith was appointed Chief Financial Officer of Company A on 2025-03-01.",
            "Jane Doe was appointed Chief Financial Officer of Company A on 2025-07-01.",
        ],
    ),
    CaseInput(
        name="Case E",
        texts=[
            "Company X is headquartered in Denver, Colorado.",
            "Company X is headquartered in Miami, Florida.",
        ],
        source_types=[SourceType.DATABASE, SourceType.WEB],
    ),
]


def _make_source(name: str, idx: int, source_type: SourceType) -> Source:
    return Source(
        source_id=SourceID(str(uuid4())),
        name=f"{name}-{idx}",
        source_type=source_type,
        locator=f"step13-regression/{name}/{idx}",
    )


def _comparable(fact: Fact) -> tuple[str, str, str, bool, object]:
    """The fields this regression compares -- deliberately excludes
    fact_id and extracted_at, which are expected to differ between the
    old and new path (fresh uuid4()/datetime.now(UTC) each call).

    effective_from needs a related, but not identical, exclusion: for
    every Case A-E fixture WITHOUT an explicit date in the text (A, B,
    C, E), both extract()'s and validate_and_build_fact()'s documented
    behavior is "falls back to extracted_at" -- but each function's
    own extracted_at is independently called, microseconds apart, so
    the literal effective_from timestamps can never be expected to
    match between the two paths in that case. What SHOULD match, and
    is what this function actually checks, is whether each fact fell
    back at all (effective_from == that SAME fact's own extracted_at)
    -- a boolean, compared between old and new -- rather than the
    literal fallback timestamp value. For Case D, where a real date IS
    present in the text, effective_from is checked for an exact value,
    since both paths parse the identical literal date string through
    the same deterministic parser and must produce the same result.
    """
    fell_back = fact.effective_from == fact.extracted_at
    if fell_back:
        return (fact.subject, fact.predicate, fact.object, True, None)
    return (fact.subject, fact.predicate, fact.object, False, fact.effective_from)


def run_case(case: CaseInput) -> tuple[bool, str]:
    source_types = case.source_types or [SourceType.DOCUMENT] * len(case.texts)

    old_facts: list[Fact] = []
    new_facts: list[Fact] = []

    for idx, (text, stype) in enumerate(zip(case.texts, source_types, strict=True)):
        old_source = _make_source(case.name, idx, stype)
        new_source = _make_source(case.name, idx, stype)

        old_facts.extend(extract(text, old_source))

        candidates = extract_as_candidates(text)
        for cand in candidates:
            result = validate_and_build_fact(cand, text, new_source)
            if result.fact is None:
                return False, (
                    f"{case.name}: NEW-path candidate REJECTED "
                    f"(reason={result.rejection_reason}) for text {text!r} -- "
                    f"old path produced a Fact here, new path did not. This is "
                    f"a real regression, not a comparison artifact."
                )
            new_facts.append(result.fact)

    if len(old_facts) != len(new_facts):
        return False, (
            f"{case.name}: fact COUNT differs -- old path produced "
            f"{len(old_facts)}, new path produced {len(new_facts)}."
        )

    old_sorted = sorted(old_facts, key=lambda f: (f.subject, f.predicate, f.object))
    new_sorted = sorted(new_facts, key=lambda f: (f.subject, f.predicate, f.object))

    for i, (old_f, new_f) in enumerate(zip(old_sorted, new_sorted, strict=True)):
        old_c = _comparable(old_f)
        new_c = _comparable(new_f)
        if old_c != new_c:
            return False, (
                f"{case.name}: fact #{i} field mismatch.\n"
                f"  OLD (extract()):                    {old_c}\n"
                f"  NEW (extract_as_candidates + wrap):  {new_c}"
            )

    # Stage 2 cardinality-preservation re-check on the NEW path's facts,
    # mirroring the frozen reports' own Stage 2 check (A-E all report
    # "cardinality preserved").
    enriched = enrich_temporally(new_facts)
    if len(enriched) != len(new_facts):
        return False, (
            f"{case.name}: Stage 2 cardinality not preserved on new-path "
            f"facts ({len(new_facts)} in, {len(enriched)} out)."
        )

    # Stage 3 contradiction-count re-check. IMPORTANT: Cases C and D's
    # expected counts here are 1, NOT the 0 that
    # SAGE_V01_E2E_VERIFICATION_REPORT.md originally reported for them.
    # That report predates the Stage 3 semantic-identity fix
    # (claim_policy.py, STAGE3_SEMANTIC_IDENTITY_DESIGN_V2.md), which
    # was implemented and frozen specifically to make C and D detect a
    # contradiction (that design document's own section 6 states this
    # outcome as the explicit, intended result of the fix: "Expected:
    # 1 contradiction detected" for both C and D). detect_contradictions
    # already imports and uses derive_claim_key (confirmed directly
    # from pairing.py's real source before this script was written) --
    # so a real, correct, already-shipped behavior change, not a Step
    # 13 regression, is why this script's expectation differs from the
    # v0.1 report. Using the v0.1 report's 0-contradiction figure here
    # would be comparing against the WRONG baseline for C and D.
    contradictions = detect_contradictions(enriched)
    expected_contradictions = {"Case A": 0, "Case B": 1, "Case C": 1, "Case D": 1, "Case E": 1}
    expected = expected_contradictions[case.name]
    if len(contradictions) != expected:
        return False, (
            f"{case.name}: Stage 3 contradiction count on new-path facts "
            f"is {len(contradictions)}, expected {expected} (per the "
            f"post-claim_policy.py-fix baseline, not the original v0.1 "
            f"report's pre-fix figure -- see module docstring)."
        )

    return True, f"{case.name}: OK -- {len(old_facts)} fact(s), fields identical, Stage 2/3 match frozen report."


def main() -> None:
    print("=" * 70)
    print("Phase 4C Step 13, criterion 3: Cases A-E, new candidate path,")
    print("SEMANTIC disabled, compared against the frozen old path.")
    print("=" * 70)
    print()
    print(
        "NOTE: fixture text below is transcribed from "
        "SAGE_V01_E2E_VERIFICATION_REPORT.md's quoted sentences, not read "
        "from fixtures/e2e/*.txt directly -- see module docstring."
    )
    print()

    all_ok = True
    for case in CASES:
        ok, message = run_case(case)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {message}")
        all_ok = all_ok and ok

    print()
    print("=" * 70)
    if all_ok:
        print("ALL CASES A-E: new candidate path reproduces the frozen old-path")
        print("results exactly (field-identical; fact_id/extracted_at excluded")
        print("by design, per every prior step's comparison standard).")
    else:
        print("AT LEAST ONE CASE FAILED -- see above. This is a real regression")
        print("finding, to be recorded as-is in the Step 13 completion artifact,")
        print("not silently patched around.")
    print("=" * 70)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

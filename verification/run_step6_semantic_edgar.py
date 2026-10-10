# verification/run_step6_semantic_edgar.py
"""
Phase 4C Step 6 -- corrected semantic extraction run.

Runs the SAME 8 real EDGAR excerpts (fixtures/edgar/, the frozen set from
EDGAR_BASELINE_FINDINGS.md) through the SEMANTIC path only, using the
corrected prompt (PHASE4B_PRODUCTION_CONTRACT.md section 4, Fix 1 --
narrowed clause-level date-association instruction), and reports exactly
the seven items specified for this step:

    1. compound-sentence recovery (the MSFT verbatim-compound document)
    2. talent-risk fragment rejection (the Apple talent-risk document)
    3. David Stoll self-reference rejection (the 8x8 document)
    4. date recovery for Tenet / ICT
    5. predicate behavior (SEMANTIC's own phrasing vs RULE's canonical shape)
    6. source-span validity (every ACCEPTED fact's span really is a
       substring of raw_text -- a mechanical re-check, not a re-trust of
       the SEMANTIC_UNAVAILABLE/MALFORMED_RESPONSE path)
    7. candidate acceptance/rejection counts, per document and in total

STRICT SCOPE, per explicit instruction:
    - This script makes REAL calls to NVIDIA NIM (build_nvidia_call_llm).
      It requires NVIDIA_API_KEY to be set. It is NOT a mocked or offline
      test -- see experiments/semantic_extraction/test_offline.py for that.
    - This script does NOT modify contracts/, Stage 1-6, extract.py,
      candidate.py, semantic_extract.py, or any fixture. It only reads
      fixtures/edgar/ and calls the (already prompt-corrected)
      nvidia_client.build_nvidia_call_llm().
    - This script does NOT decide whether the architecture should change
      based on what it finds. It records results. Per standing
      instruction: "the purpose of Step 6 is measurement against the
      locked design. If something fails, record the failure first."
    - RULE is not re-run here -- EDGAR_BASELINE_FINDINGS.md already
      froze RULE's result on these 8 documents (1 correct / 1 corrupted /
      6 missed), and Step 5 already proved the candidate-path reproduces
      it exactly. This step is SEMANTIC-only, to avoid conflating two
      already-answered questions with the one open question here.

Output: writes a full JSON report (every candidate, accepted or
rejected, every field) to
verification/results/step6_semantic_edgar_report.json, and prints a
human-readable summary of the seven measured items to stdout. The
JSON is the artifact; the stdout summary is for a quick read, not a
substitute for it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from contracts.fact_schema import Source, SourceID, SourceType
from experiments.semantic_extraction.candidate import validate_and_build_fact
from experiments.semantic_extraction.nvidia_client import build_nvidia_call_llm
from experiments.semantic_extraction.semantic_extract import (
    LLMCallFn,
    SemanticStatus,
    extract_semantic,
)

# Identical set, same order, as EDGAR_BASELINE_FINDINGS.md and
# run_experiment.py's _EDGAR_SET. Not imported from there, so that a
# change to the Phase 2 script's set can never silently change what
# this Step 6 report measures without someone noticing the duplication.
_EDGAR_SET: list[str] = [
    "fixtures/edgar/apple_10k_2024_properties.txt",
    "fixtures/edgar/apple_10k_2024_cybersecurity.txt",
    "fixtures/edgar/apple_10k_2024_talent_risk.txt",
    "fixtures/edgar/tenet_10k_incorporation.txt",
    "fixtures/edgar/ict_8k_cfo_appointment.txt",
    "fixtures/edgar/8x8_8k_cfo_appointment.txt",
    "fixtures/edgar/msft_def14a_thompson_ceo.txt",
    "fixtures/edgar/msft_def14a_thompson_ceo_verbatim_compound.txt",
]

_OUTPUT_PATH = Path("verification/results/step6_semantic_edgar_report.json")


class CandidateRecord(TypedDict, total=False):
    subject: str
    predicate: str
    object: str
    effective_from_text: str | None
    llm_confidence: float | None
    source_span: str
    source_span_is_real_substring: bool
    fact_id: str
    effective_from: str
    effective_from_is_extracted_at_fallback: bool
    rejection_reason: str


class DocumentReport(TypedDict):
    file: str
    status: str
    error_detail: str | None
    accepted: list[CandidateRecord]
    rejected: list[CandidateRecord]



def _run_one_document(path_str: str, call_llm: LLMCallFn) -> DocumentReport:
    path = Path(path_str)
    raw_text = path.read_text()
    source = Source(
        source_id=SourceID(str(uuid4())),
        name=path.stem,
        source_type=SourceType.DOCUMENT,
        locator=str(path),
    )

    result = extract_semantic(raw_text, call_llm)

    if result.status != SemanticStatus.OK:
        return {
            "file": path.name,
            "status": result.status.value,
            "error_detail": result.error_detail,
            "accepted": [],
            "rejected": [],
        }

    accepted: list[CandidateRecord] = []
    rejected: list[CandidateRecord] = []
    for candidate in result.candidates:
        # Item 6: source-span validity, checked directly here as well as
        # inside validate_and_build_fact -- a mechanical re-check against
        # the raw text this script itself read, not trust in the library
        # function alone.
        span_is_real_substring = candidate.source_span in raw_text

        outcome = validate_and_build_fact(candidate, raw_text, source)

        record: CandidateRecord = {
            "subject": candidate.subject,
            "predicate": candidate.predicate,
            "object": candidate.object,
            "effective_from_text": candidate.effective_from_text,
            "llm_confidence": candidate.llm_confidence,
            "source_span": candidate.source_span,
            "source_span_is_real_substring": span_is_real_substring,
        }

        if outcome.fact is not None:
            record["fact_id"] = str(outcome.fact.fact_id)
            record["effective_from"] = outcome.fact.effective_from.isoformat()
            record["effective_from_is_extracted_at_fallback"] = (
                outcome.fact.effective_from == outcome.fact.extracted_at
            )
            accepted.append(record)
        else:
            record["rejection_reason"] = (
                outcome.rejection_reason.value if outcome.rejection_reason else "unknown"
            )
            rejected.append(record)

    return {
        "file": path.name,
        "status": result.status.value,
        "error_detail": result.error_detail,
        "accepted": accepted,
        "rejected": rejected,
    }


def _print_summary(report: list[DocumentReport]) -> None:
    print("=" * 78)
    print("PHASE 4C STEP 6 -- SEMANTIC extraction, corrected prompt, real API calls")
    print("=" * 78)

    total_accepted = sum(len(r["accepted"]) for r in report)
    total_rejected = sum(len(r["rejected"]) for r in report)
    print(f"\nDocuments processed: {len(report)}")
    print(f"Total candidates: {total_accepted + total_rejected}  "
          f"(accepted={total_accepted}, rejected={total_rejected})")

    print("\n--- Item 7: acceptance/rejection counts, per document ---")
    for r in report:
        print(f"  {r['file']:<55} status={r['status']:<10} "
              f"accepted={len(r['accepted'])} rejected={len(r['rejected'])}")

    print("\n--- Item 6: source-span validity, all accepted facts ---")
    bad_spans = [
        (r["file"], a) for r in report for a in r["accepted"]
        if not a["source_span_is_real_substring"]
    ]
    if bad_spans:
        print(f"  ANOMALY: {len(bad_spans)} accepted fact(s) with a span not found in "
              f"raw_text -- this should be impossible, since validate_and_build_fact "
              f"itself checks this before construction. Investigate before trusting "
              f"anything else in this report.")
        for fname, a in bad_spans:
            print(f"    {fname}: {a['subject']!r} / {a['predicate']!r} / {a['object']!r}")
    else:
        print(f"  All {total_accepted} accepted fact(s) have a real, verified span. "
              f"(Expected -- this is enforced by Step 4b, not just observed here.)")

    def _find(name: str) -> DocumentReport | None:
        return next((r for r in report if r["file"] == name), None)

    print("\n--- Item 1: compound-sentence recovery ---")
    compound = _find("msft_def14a_thompson_ceo_verbatim_compound.txt")
    if compound is None:
        print("  Document not found in report.")
    else:
        true_object_facts = [a for a in compound["accepted"] if a["object"] == "Virtual Instruments"]
        print(f"  status={compound['status']}, accepted={len(compound['accepted'])}, "
              f"rejected={len(compound['rejected'])}")
        print(f"  Fact(s) with object=='Virtual Instruments' (the correction RULE fails "
              f"to make): {len(true_object_facts)}")
        for a in compound["accepted"]:
            print(f"    ACCEPTED: {a['subject']!r} -- {a['predicate']!r} -- {a['object']!r}")
        for rej in compound["rejected"]:
            print(f"    REJECTED ({rej['rejection_reason']}): "
                  f"{rej['subject']!r} -- {rej['predicate']!r} -- {rej['object']!r}")

    print("\n--- Item 2: talent-risk fragment rejection ---")
    talent = _find("apple_10k_2024_talent_risk.txt")
    if talent is None:
        print("  Document not found in report.")
    else:
        copula_rejections = [
            rej for rej in talent["rejected"]
            if rej["rejection_reason"] == "BARE_COPULA_PREDICATE"
        ]
        print(f"  status={talent['status']}, accepted={len(talent['accepted'])}, "
              f"rejected={len(talent['rejected'])}")
        print(f"  Rejected for BARE_COPULA_PREDICATE: {len(copula_rejections)}")
        for a in talent["accepted"]:
            print(f"    ACCEPTED: {a['subject']!r} -- {a['predicate']!r} -- {a['object']!r}")
        for rej in talent["rejected"]:
            print(f"    REJECTED ({rej['rejection_reason']}): "
                  f"{rej['subject']!r} -- {rej['predicate']!r} -- {rej['object']!r}")

    print("\n--- Item 3: David Stoll self-reference rejection ---")
    eightx8 = _find("8x8_8k_cfo_appointment.txt")
    if eightx8 is None:
        print("  Document not found in report.")
    else:
        self_ref = [
            rej for rej in eightx8["rejected"]
            if rej["subject"].strip() == rej["object"].strip()
        ]
        print(f"  status={eightx8['status']}, accepted={len(eightx8['accepted'])}, "
              f"rejected={len(eightx8['rejected'])}")
        print(f"  Rejected self-reference candidate(s) (subject==object): {len(self_ref)}")
        for a in eightx8["accepted"]:
            print(f"    ACCEPTED: {a['subject']!r} -- {a['predicate']!r} -- {a['object']!r}")
        for rej in eightx8["rejected"]:
            print(f"    REJECTED ({rej['rejection_reason']}): "
                  f"{rej['subject']!r} -- {rej['predicate']!r} -- {rej['object']!r}")

    print("\n--- Item 4: date recovery, Tenet / ICT ---")
    for fname, label in [
        ("tenet_10k_incorporation.txt", "Tenet (source states '1975')"),
        ("ict_8k_cfo_appointment.txt", "ICT (source states 'effective January 1, 2014')"),
    ]:
        doc = _find(fname)
        print(f"  {label}:")
        if doc is None:
            print("    Document not found in report.")
            continue
        for a in doc["accepted"]:
            captured = a["effective_from_text"]
            fell_back = a["effective_from_is_extracted_at_fallback"]
            print(f"    {a['subject']!r} -- {a['predicate']!r} -- {a['object']!r}")
            print(f"      effective_from_text={captured!r}  "
                  f"(fell back to extracted_at: {fell_back})")

    print("\n--- Item 5: predicate behavior (SEMANTIC phrasing vs RULE canonical shape) ---")
    rule_canonical = {
        "is headquartered in",
        "was founded on",
        "is the chief executive officer of",
        "was appointed Chief Financial Officer of",
    }
    for r in report:
        for a in r["accepted"]:
            marker = "matches a RULE canonical shape" if a["predicate"] in rule_canonical \
                else "SEMANTIC's own phrasing (not RULE canonical)"
            print(f"  {r['file']:<50} predicate={a['predicate']!r:<50} {marker}")

    print("\n" + "=" * 78)
    print(f"Full report written to: {_OUTPUT_PATH}")
    print("No architecture or code changes have been made based on this run.")
    print("=" * 78)


def main() -> None:
    call_llm = build_nvidia_call_llm()

    report: list[DocumentReport] = []
    for path_str in _EDGAR_SET:
        print(f"Calling NVIDIA NIM for: {path_str} ...", flush=True)
        report.append(_run_one_document(path_str, call_llm))

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(json.dumps(
        {"run_at_utc": datetime.now(UTC).isoformat(), "documents": report},
        indent=2,
    ))

    _print_summary(report)


if __name__ == "__main__":
    main()
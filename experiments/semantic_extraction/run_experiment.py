# experiments/semantic_extraction/run_experiment.py
"""
Phase 2 semantic-extraction experiment runner.

Runs the SAME 8 real EDGAR excerpts already frozen in
EDGAR_BASELINE_FINDINGS.md through both:
    - RULE: the real, unmodified src/sage/pipeline/stage_1/extract.py
    - SEMANTIC: this experiment's candidate -> Fact pipeline

RULE's result on each document is NOT a gate on whether SEMANTIC runs --
per the accepted design, both run independently on every document,
including the one RULE already got right and the one it corrupted.

This script requires a real LLM API call to be wired in via
`build_call_llm()` below -- see the TODO there. Everything else
(candidate validation, Fact construction, comparison report) works
today with no API required, and is exercised by
experiments/semantic_extraction/test_offline.py using a fake LLM
response so the scaffolding itself is verified before any real API
key is involved.

Per standing instruction: this script does not modify contracts/,
Stage 1-6, or the frozen fixtures/edgar/ files. It only reads them.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from contracts.fact_schema import Source, SourceID, SourceType
from sage.pipeline.stage_1.extract import extract as rule_extract

from experiments.semantic_extraction.candidate import validate_and_build_fact
from experiments.semantic_extraction.semantic_extract import (
    LLMCallFn,
    SemanticStatus,
    extract_semantic,
)

# The exact 8 documents from the frozen EDGAR baseline. Order and
# filenames match EDGAR_BASELINE_FINDINGS.md exactly -- do not add,
# remove, or reorder without updating that document's own "8 excerpts"
# claim, since this IS the set that document describes.
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



from experiments.semantic_extraction.nvidia_client import build_nvidia_call_llm

def build_call_llm() -> LLMCallFn:
    return build_nvidia_call_llm()


def run_rule(raw_text: str, source: Source) -> list[dict]:
    """Run the real, unmodified RULE extractor. Returns a list of
    plain dicts (not Fact objects) purely for comparison-report
    convenience -- the real Facts still exist via rule_extract's
    normal return value if needed elsewhere."""
    facts = rule_extract(raw_text, source)
    return [
        {"subject": f.subject, "predicate": f.predicate, "object": f.object}
        for f in facts
    ]


def run_semantic(raw_text: str, source: Source, call_llm: LLMCallFn) -> dict:
    """Run the SEMANTIC path: API call -> candidates -> validation ->
    Facts. Returns a summary dict for the comparison report."""
    result = extract_semantic(raw_text, call_llm)

    if result.status != SemanticStatus.OK:
        return {
            "status": result.status.value,
            "error_detail": result.error_detail,
            "facts": [],
            "rejected": [],
        }

    facts = []
    rejected = []
    for candidate in result.candidates:
        outcome = validate_and_build_fact(candidate, raw_text, source)
        if outcome.fact is not None:
            facts.append(
                {
                    "subject": outcome.fact.subject,
                    "predicate": outcome.fact.predicate,
                    "object": outcome.fact.object,
                    "llm_confidence": candidate.llm_confidence,
                    "fact_id": str(outcome.fact.fact_id),
                }
            )
        else:
            rejected.append(
                {
                    "reason": outcome.rejection_reason.value if outcome.rejection_reason else "unknown",
                    "subject": candidate.subject,
                    "predicate": candidate.predicate,
                    "object": candidate.object,
                    "llm_confidence": candidate.llm_confidence,
                }
            )

    return {
        "status": result.status.value,
        "error_detail": result.error_detail,
        "facts": facts,
        "rejected": rejected,
    }


def main() -> None:
    call_llm = build_call_llm()  # raises until wired in -- see docstring

    report: list[dict] = []

    for path_str in _EDGAR_SET:
        path = Path(path_str)
        raw_text = path.read_text()
        source = Source(
            source_id=SourceID(str(uuid4())),
            name=path.stem,
            source_type=SourceType.DOCUMENT,
            locator=str(path),
        )

        rule_result = run_rule(raw_text, source)
        semantic_result = run_semantic(raw_text, source, call_llm)

        report.append(
            {
                "file": path.name,
                "rule": rule_result,
                "semantic": semantic_result,
            }
        )

    output_path = Path("experiments/semantic_extraction/results/comparison_report.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2))

    print(f"Wrote comparison report: {output_path}")
    print(f"Documents processed: {len(report)}")
    for row in report:
        print(f"\n{row['file']}")
        print(f"  RULE:     {len(row['rule'])} fact(s)")
        print(f"  SEMANTIC: status={row['semantic']['status']}, "
              f"{len(row['semantic']['facts'])} fact(s), "
              f"{len(row['semantic']['rejected'])} rejected")


if __name__ == "__main__":
    main()
# experiments/semantic_extraction/test_offline.py
"""
Proves the Phase 2 experiment scaffolding works end-to-end WITHOUT a
real LLM API call. Uses a fake call_llm that returns a hand-written,
plausible response for each of the 8 real EDGAR documents -- standing
in for what a real model might say, so the pipeline (candidate parsing,
source_span verification, Fact construction, RULE-vs-SEMANTIC report)
can be verified before any API key is wired in.

This is NOT the real experiment result. It does not answer the
design's central question. It only proves the harness is correct.
Run this first; only after it passes does wiring in a real
build_call_llm() in run_experiment.py become worth doing.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from contracts.fact_schema import Source, SourceID, SourceType

from experiments.semantic_extraction.run_experiment import _EDGAR_SET, run_rule, run_semantic


def _fake_call_llm(raw_text: str):
    """Stands in for a real API call. Returns hand-written candidates
    that deliberately exercise different paths:
      - a correct candidate with a verifiable source_span
      - a hallucinated-span candidate (should be rejected)
      - empty response for documents with nothing to extract
    This is illustrative test data, not a claim about what a real model
    would actually return.
    """
    # Apple headquarters excerpt -- real near-miss for RULE; give
    # SEMANTIC a chance to recover it correctly, with a real span.
    if "Cupertino" in raw_text:
        span = "The Company's headquarters is located in Cupertino, California."
        return json.dumps([
            {
                "subject": "The Company",
                "predicate": "is headquartered in",
                "object": "Cupertino, California",
                "effective_from_text": None,
                "llm_confidence": 0.93,
                "source_span": span,
            }
        ])

    # Microsoft compound sentence -- the RULE-corrupted case. Give
    # SEMANTIC a chance to get the object right where RULE didn't.
    if "less-than-10%" in raw_text:
        span = ("Mr. Thompson is the chief executive officer of and has a "
                "less-than-10% beneficial interest in Virtual Instruments.")
        return json.dumps([
            {
                "subject": "Mr. Thompson",
                "predicate": "is the chief executive officer of",
                "object": "Virtual Instruments",
                "effective_from_text": None,
                "llm_confidence": 0.85,
                "source_span": span,
            }
        ])

    # One deliberately hallucinated example, to prove rejection works
    # even in an offline test -- attached to the Tenet document.
    if "Nevada" in raw_text:
        return json.dumps([
            {
                "subject": "Tenet Healthcare Corporation",
                "predicate": "was founded on",
                "object": "1975-01-01",
                "effective_from_text": "1975",
                "llm_confidence": 0.6,
                # Deliberately wrong span, not present in raw_text, to
                # prove validate_and_build_fact rejects it.
                "source_span": "This exact sentence is not in the document.",
            }
        ])

    # Everything else: legitimate empty response.
    return json.dumps([])


def main() -> None:
    print("=" * 70)
    print("OFFLINE SCAFFOLDING TEST -- fake LLM, proves the harness works")
    print("NOT the real experiment result.")
    print("=" * 70)

    for path_str in _EDGAR_SET:
        path = Path(path_str)
        if not path.exists():
            print(f"\n[MISSING] {path_str}")
            continue

        raw_text = path.read_text()
        source = Source(
            source_id=SourceID(str(uuid4())),
            name=path.stem,
            source_type=SourceType.DOCUMENT,
            locator=str(path),
        )

        rule_result = run_rule(raw_text, source)
        semantic_result = run_semantic(raw_text, source, _fake_call_llm)

        print(f"\n{path.name}")
        print(f"  RULE:     {len(rule_result)} fact(s) -- {rule_result}")
        print(f"  SEMANTIC: status={semantic_result['status']}, "
              f"{len(semantic_result['facts'])} fact(s), "
              f"{len(semantic_result['rejected'])} rejected")
        for f in semantic_result["facts"]:
            print(f"    ACCEPTED: {f['subject']!r} -- {f['predicate']!r} -- {f['object']!r} "
                  f"(llm_confidence={f['llm_confidence']})")
        for r in semantic_result["rejected"]:
            print(f"    REJECTED ({r['reason']}): {r['subject']!r} -- {r['object']!r}")


if __name__ == "__main__":
    main()
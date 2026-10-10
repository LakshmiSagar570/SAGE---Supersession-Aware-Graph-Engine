"""Phase 4C Step 13, criterion 4 -- all 8 EDGAR fixtures through the
real, live hybrid pipeline, results recorded.

verification/run_step13_edgar_hybrid_pass.py

SCOPE, exactly as instructed: run the existing, frozen 8-document EDGAR
set through the actual hybrid pathway and record results. This is NOT
Phase 4D -- it does not broaden the corpus, re-evaluate extraction
quality, tune prompts, reinterpret failures, or start a new semantic
study. The only question this script answers is: does the completed
4C implementation execute across the complete frozen fixture set and
produce a recorded result?

UNLIKE Step 10 and Step 12, which each used ONE fixture and replayed an
already-observed SEMANTIC response for it (explicitly flagged in both
of those steps' own artifacts as a network-call substitution), this
script makes REAL, LIVE calls to the NVIDIA NIM API via the real,
unmodified build_nvidia_call_llm() for every one of the 8 documents.
This is necessary and cannot be substituted here: criterion 4 requires
"the real, live hybrid pipeline," and a replay of 7 already-observed
responses plus 1 new fixture would not be that. This script therefore
REQUIRES a working NVIDIA_API_KEY in the environment and real network
access -- it cannot be run in an offline/sandboxed verification
environment, and was not run end-to-end in one before delivery. See
the accompanying Step 13 completion artifact for what was and was not
independently verified before this script reached Sagar.

What this script does NOT do, per the explicit Step 13 boundary:
  - Does not compare results against EDGAR_BASELINE_FINDINGS.md's
    numbers as a pass/fail gate -- that comparison IS Phase 4D's job.
    This script only confirms the hybrid path runs to completion on
    all 8 documents and records what happened.
  - Does not retry, tune, or adjust anything based on what SEMANTIC
    returns for any document.
  - Does not implement deduplication, even though -- per Step 10 and
    12's now-twice-confirmed finding -- every document where RULE and
    SEMANTIC agree is expected to again materialize as duplicate Fact
    nodes. That is expected, recorded, and left alone.

Each document's Source uses a distinct, deterministic source_id
derived from its own filename (not a shared one -- these are 8
genuinely separate document ingestions, unlike Step 12's
single-document, same-source_id design).

Usage:
    NVIDIA_API_KEY=... PYTHONPATH=. python verification/run_step13_edgar_hybrid_pass.py
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

from contracts.fact_schema import Fact, Source, SourceID, SourceType
from contracts.stage_io import Stage6Input
from experiments.semantic_extraction.candidate import validate_and_build_fact
from experiments.semantic_extraction.nvidia_client import (
    CACHE_IDENTITY,
    build_nvidia_call_llm,
)
from experiments.semantic_extraction.semantic_cache import (
    SemanticCache,
    extract_semantic_cached,
)
from sage.pipeline.stage_1.extract_candidates import extract_as_candidates
from sage.pipeline.stage_2.temporal import enrich_temporally
from sage.pipeline.stage_3.detect import detect_contradictions
from sage.pipeline.stage_4.authority import infer_authority
from sage.pipeline.stage_5.resolve import resolve_contradictions
from sage.pipeline.stage_6.materialize import materialize
from sage.pipeline.stage_6.neo4j_client import Neo4jClient
from sage.pipeline.stage_6.queries import CREATE_CONSTRAINTS

FIXTURE_DIR = Path("fixtures/edgar")
FIXTURE_FILES = [
    "apple_10k_2024_properties.txt",
    "apple_10k_2024_cybersecurity.txt",
    "apple_10k_2024_talent_risk.txt",
    "tenet_10k_incorporation.txt",
    "ict_8k_cfo_appointment.txt",
    "8x8_8k_cfo_appointment.txt",
    "msft_def14a_thompson_ceo.txt",
    "msft_def14a_thompson_ceo_verbatim_compound.txt",
]


def _log(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def process_one_document(
    filename: str, call_llm: Callable[[str], str], cache: SemanticCache
) -> dict[str, object]:
    path = FIXTURE_DIR / filename
    if not path.exists():
        return {"filename": filename, "error": f"fixture file not found: {path}"}

    raw_text = path.read_text()
    source = Source(
        source_id=SourceID(filename),  # deterministic, distinct per document
        name=filename,
        source_type=SourceType.DOCUMENT,
        locator=str(path),
    )

    record: dict[str, object] = {"filename": filename}

    # --- RULE side ---
    rule_candidates = extract_as_candidates(raw_text)
    record["rule_candidate_count"] = len(rule_candidates)

    # --- SEMANTIC side: real, live extract_semantic_cached() call ---
    semantic_result = extract_semantic_cached(raw_text, call_llm, CACHE_IDENTITY, cache=cache)
    record["semantic_status"] = semantic_result.status.value
    record["semantic_candidate_count"] = len(semantic_result.candidates)
    record["semantic_error_detail"] = semantic_result.error_detail

    # --- shared validation + candidate -> Fact, both origins ---
    all_candidates = list(rule_candidates) + list(semantic_result.candidates)
    facts: list[Fact] = []
    rejections: list[dict[str, str]] = []
    for cand in all_candidates:
        result = validate_and_build_fact(cand, raw_text, source)
        if result.fact is not None:
            facts.append(result.fact)
        else:
            rejections.append(
                {
                    "origin": cand.origin.value,
                    "subject": cand.subject,
                    "predicate": cand.predicate,
                    "object": cand.object,
                    "reason": str(result.rejection_reason),
                }
            )

    record["accepted_count"] = len(facts)
    record["rejected_count"] = len(rejections)
    record["rejections"] = rejections
    record["facts"] = [
        {"subject": f.subject, "predicate": f.predicate, "object": f.object, "fact_id": str(f.fact_id)}
        for f in facts
    ]

    print(f"\n--- {filename} ---")
    print(f"  RULE candidates:      {len(rule_candidates)}")
    print(f"  SEMANTIC status:      {semantic_result.status.value}")
    print(f"  SEMANTIC candidates:  {len(semantic_result.candidates)}")
    print(f"  Accepted -> Facts:    {len(facts)}")
    print(f"  Rejected:             {len(rejections)}")
    for fact in facts:
        print(f"    [{fact.subject!r} / {fact.predicate!r} / {fact.object!r}]")
    for rej in rejections:
        print(f"    REJECTED ({rej['origin']}, {rej['reason']}): {rej['subject']!r}/{rej['predicate']!r}/{rej['object']!r}")

    record["_facts_for_stage2"] = facts
    return record


def main() -> None:
    if not os.environ.get("NVIDIA_API_KEY"):
        raise SystemExit(
            "NVIDIA_API_KEY not set. This script makes real, live API calls "
            "for all 8 fixtures (per Step 13 criterion 4's requirement for "
            "the real hybrid pipeline, not a replay) and cannot proceed "
            "without it. Stopping -- not falling back to a fake/offline mode."
        )

    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    call_llm = build_nvidia_call_llm()
    cache = SemanticCache()  # real, persistent default cache dir

    _log("STEP 13 criterion 4: 8-fixture EDGAR hybrid pass")

    all_records: list[dict[str, object]] = []
    all_facts: list[Fact] = []
    for filename in FIXTURE_FILES:
        record = process_one_document(filename, call_llm, cache)
        if "error" in record:
            print(f"\n[STOP] {record['error']}")
            print("A missing fixture file is a real problem to report, not patch around.")
            raise SystemExit(1)
        doc_facts = cast("list[Fact]", record.pop("_facts_for_stage2"))
        all_facts.extend(doc_facts)
        all_records.append(record)

    _log("Stage 2 -- Temporal (all facts from all 8 documents, combined)")
    enriched = enrich_temporally(all_facts)
    print(f"  {len(all_facts)} facts in, {len(enriched)} enriched out")

    _log("Stage 3 -- Contradiction Detection")
    contradictions = detect_contradictions(enriched)
    print(f"  {len(contradictions)} contradiction(s)")
    for c in contradictions:
        print(f"    {c.contradiction_id}: {c.conflict_type.value}, facts={[str(i) for i in c.conflicting_fact_ids]}")

    _log("Stage 4 -- Authority")
    assessments = infer_authority(enriched, contradictions)
    print(f"  {len(assessments)} assessment(s)")

    _log("Stage 5 -- Resolution")
    resolutions = resolve_contradictions(enriched, contradictions, assessments)
    print(f"  {len(resolutions)} resolution(s)")
    for r in resolutions:
        print(f"    {r.resolution_id}: {r.outcome.value}")

    _log("Stage 6 -- Validation + Materialization")
    stage_input = Stage6Input(
        facts=enriched, contradictions=contradictions,
        authority_assessments=assessments, resolutions=resolutions,
    )
    client = Neo4jClient(password=password)
    client.verify_connectivity()
    client.create_constraints(CREATE_CONSTRAINTS)
    output = materialize(stage_input, client)
    print(f"  Stage6Output: {output.model_dump()}")
    client.close()

    full_record = {
        "per_document": all_records,
        "total_facts_accepted": len(all_facts),
        "stage3_contradiction_count": len(contradictions),
        "stage5_resolution_count": len(resolutions),
        "stage6_output": output.model_dump(mode="json"),
    }
    out_path = Path("verification/results/step13_edgar_hybrid_pass_record.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(full_record, indent=2, default=str))

    _log("STEP 13 criterion 4: COMPLETE")
    print("All 8 fixtures processed through the real, live hybrid pipeline.")
    print(f"Total Facts accepted across all 8 documents: {len(all_facts)}")
    print(f"Wrote {out_path}")
    print(
        "\nThis script records results; it does not judge extraction "
        "quality against EDGAR_BASELINE_FINDINGS.md's numbers -- that "
        "comparison is Phase 4D's job, not this criterion's."
    )


if __name__ == "__main__":
    main()

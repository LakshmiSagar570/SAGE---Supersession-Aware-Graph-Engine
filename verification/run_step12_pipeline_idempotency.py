"""Phase 4C Step 12 -- full hybrid pipeline, two-run graph-materialization
idempotency measurement.

verification/run_step12_pipeline_idempotency.py

PHASE4C_IMPLEMENTATION_PLAN.md Step 12, narrowed per explicit instruction
to the two-run idempotency question specifically (item 6 of that step),
using the same "verification harness, not a new production API" approach
Step 10 used -- because no unified hybrid orchestration function
(run_hybrid_case.py) exists in the codebase yet, and this script does not
create one. This is stated here, not silently worked around.

EXISTING EXECUTION PATH, confirmed by inspection before this script was
written (see STEP12_FULL_PIPELINE_IDEMPOTENCY_FINDINGS.md section 0 for
the full report):
  - run_stage1(Stage1Input) -> Stage1Output is the one real production
    Stage 1 entry point, but it is RULE-only (calls extract(), not the
    hybrid candidate path) -- it cannot be reused directly for a hybrid
    run.
  - Its _build_document_source() helper IS reused here, conceptually:
    source_id = SourceID(reference), deterministic from a fixed
    reference string. This script reconstructs that exact same logic
    rather than re-implementing a different one, so the experiment's
    Source identity mechanism matches real production behavior, not an
    invented harness-only scheme.
  - No hybrid (RULE+SEMANTIC) orchestration entry point exists anywhere
    in the codebase. This script extends Step 10's manual-harness
    pattern (hand-driven RULE + SEMANTIC candidate construction, shared
    validation, then the real Stage 2-6 functions called directly) --
    the only existing precedent for exercising the hybrid path.

WHAT IS REAL vs. HARNESS-SUBSTITUTED, stated precisely:
  - RULE candidate: produced by the real, unmodified
    extract_as_candidates() against the fixture text. Not hand-built.
  - SEMANTIC candidate: per explicit instruction, pushed through the
    REAL, unmodified extract_semantic_cached() (Step 11, frozen) on
    BOTH runs -- cache key computation, hit/miss logic, and storage are
    all exercised for real, not bypassed. The one substitution is at
    the network boundary: call_llm itself is a harness function that
    replays the already-observed real Step 6 model output for this
    exact sentence (SEMANTIC_EXTRACTION_RESULTS.md section 3.7) rather
    than making a live NVIDIA API call, since this environment has no
    network path to that API. This substitutes the NETWORK CALL only --
    every line of cache logic above and below it is the real, frozen
    Step 11 code, actually exercised, actually hit/missed for real.
  - Stages 2-6: the real, unmodified functions
    (enrich_temporally, detect_contradictions, infer_authority,
    resolve_contradictions, materialize), called directly, the same
    pattern Step 10 used.
  - Source: constructed with the SAME deterministic source_id on both
    runs, derived from one fixed reference string -- per explicit
    instruction, to isolate Fact identity as the only variable under
    test. This mirrors (not reimplements) the real
    _build_document_source() logic: source_id = SourceID(reference).

NOT DONE, per explicit, locked boundary:
  - No deduplication implemented.
  - No change to Fact identity, Source identity, any MERGE key,
    fact_schema.py, Stage 2-6 contracts, semantic_cache.py,
    prompt versions, extraction_schema_version, or Stage 3's
    identical-claim behavior.
  - No new production hybrid orchestration API -- this stays
    verification-only code.
  - The Neo4j graph is NOT wiped between Run 1 and Run 2 -- this is the
    entire point of the experiment (per explicit instruction: "Do NOT
    clear the graph unless the experiment design explicitly requires
    an isolated second database/snapshot" -- it does not here).

Usage:
    PYTHONPATH=. python verification/run_step12_pipeline_idempotency.py
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from contracts.fact_schema import Fact, Source, SourceID, SourceType
from contracts.stage_io import Stage6Input
from experiments.semantic_extraction.candidate import (
    ExtractionCandidate,
    validate_and_build_fact,
)
from experiments.semantic_extraction.nvidia_client import CACHE_IDENTITY
from experiments.semantic_extraction.semantic_cache import (
    SemanticCache,
    build_cache_key,
    document_content_hash,
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

# The real Microsoft clean-clause fixture, same as Step 10, for direct
# comparability to that step's prior finding.
RAW_TEXT = "Mr. Thompson is the chief executive officer of Virtual Instruments."

# Fixed Stage 1 "reference" string, used both runs, so source_id is
# identical both times -- the one deliberately-held-constant variable,
# per explicit instruction, so Fact identity is isolated as the only
# thing that varies between runs.
FIXED_REFERENCE = "fixtures/edgar/msft_def14a_thompson_ceo.txt"

# Replay of the already-observed, already-frozen real SEMANTIC output
# for this exact sentence (SEMANTIC_EXTRACTION_RESULTS.md section 3.7:
# "status=OK, 1 fact, identical to RULE's output field-for-field").
# This is what the harness's fake call_llm returns -- substituting only
# the network call, never the cache logic that wraps it.
_OBSERVED_SEMANTIC_RESPONSE = json.dumps(
    [
        {
            "subject": "Mr. Thompson",
            "predicate": "is the chief executive officer of",
            "object": "Virtual Instruments",
            "source_span": RAW_TEXT,
            "effective_from_text": None,
            "llm_confidence": 1.0,
        }
    ]
)


def _replay_call_llm(provider_calls: list[str]) -> Callable[[str], str]:
    """Returns a call_llm function that records every call it receives
    (so this script can report real provider-call counts) and replays
    the real, already-observed Step 6 response. A genuine network call
    would use nvidia_client.build_nvidia_call_llm() instead; this
    harness substitutes only that one boundary -- see module docstring.
    """

    def call_llm(raw_text: str) -> str:
        provider_calls.append(raw_text)
        return _OBSERVED_SEMANTIC_RESPONSE

    return call_llm


def _build_fixed_source() -> Source:
    """Mirrors stage_1/stage.py::_build_document_source's real logic
    (source_id = SourceID(reference)) rather than reimplementing a
    different scheme -- deterministic from FIXED_REFERENCE alone, so
    calling this twice with the same reference always returns the same
    source_id.
    """
    return Source(
        source_id=SourceID(FIXED_REFERENCE),
        name=FIXED_REFERENCE,
        source_type=SourceType.DOCUMENT,
        locator=FIXED_REFERENCE,
    )


def run_cypher(password: str, query: str) -> str:
    res = subprocess.run(
        ["docker", "exec", "sage_neo4j", "cypher-shell", "-u", "neo4j", "-p", password, query],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _graph_snapshot(password: str) -> dict[str, str]:
    """A single, consistent set of Cypher reads, run identically before
    Run 1, after Run 1, and after Run 2, so the three snapshots are
    directly comparable line-for-line."""
    return {
        "total_nodes_and_rels": run_cypher(
            password, "MATCH (n) RETURN count(n) AS nodes, count { MATCH ()-->() } AS rels;"
        ),
        "per_label_counts": run_cypher(
            password,
            "MATCH (s:Source) WITH count(s) as sources "
            "MATCH (f:Fact) WITH sources, count(f) as facts "
            "OPTIONAL MATCH (c:ContradictionSet) WITH sources, facts, count(c) as contradictions "
            "OPTIONAL MATCH (a:AuthorityAssessment) WITH sources, facts, contradictions, count(a) as assessments "
            "OPTIONAL MATCH (r:Resolution) RETURN sources, facts, contradictions, assessments, count(r) as resolutions;",
        ),
        "per_relationship_counts": run_cypher(
            password, "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY rel_type;"
        ),
        "virtual_instruments_facts": run_cypher(
            password,
            'MATCH (f:Fact) WHERE f.object CONTAINS "Virtual Instruments" '
            "RETURN f.fact_id, f.subject, f.predicate, f.object, f.evidence ORDER BY f.fact_id;",
        ),
        "virtual_instruments_sources": run_cypher(
            password,
            'MATCH (f:Fact)-[:FROM_SOURCE]->(s:Source) WHERE f.object CONTAINS "Virtual Instruments" '
            "RETURN DISTINCT s.source_id ORDER BY s.source_id;",
        ),
        "virtual_instruments_conflicts": run_cypher(
            password,
            'MATCH (cs:ContradictionSet)-[:CONFLICTS]->(f:Fact) WHERE f.object CONTAINS "Virtual Instruments" '
            "RETURN cs.contradiction_id, f.fact_id;",
        ),
    }


def _log(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def _run_one_pass(run_label: str, cache: SemanticCache, source: Source) -> dict[str, object]:
    """One full, independent pass: RULE candidate -> cached SEMANTIC
    candidate -> shared validation -> Fact -> Stage 2 -> 3 -> 4 -> 5.
    Does NOT call Stage 6 -- the caller does that, so both runs'
    pre-Stage-6 state can be reported before either write happens.
    """
    record: dict[str, object] = {"run": run_label}

    _log(f"{run_label}: RULE candidate (real extract_as_candidates())")
    rule_candidates = extract_as_candidates(RAW_TEXT)
    if len(rule_candidates) != 1:
        raise SystemExit(
            f"{run_label}: expected exactly 1 RULE candidate, got "
            f"{len(rule_candidates)}. Stopping -- do not patch around this."
        )
    rule_candidate = rule_candidates[0]
    print(f"  {rule_candidate.subject!r} / {rule_candidate.predicate!r} / {rule_candidate.object!r}")
    record["rule_candidate_count"] = len(rule_candidates)

    _log(f"{run_label}: SEMANTIC candidate (real extract_semantic_cached())")
    provider_calls: list[str] = []
    cache_key = build_cache_key(document_content_hash(RAW_TEXT), CACHE_IDENTITY)
    semantic_result = extract_semantic_cached(
        RAW_TEXT, _replay_call_llm(provider_calls), CACHE_IDENTITY, cache=cache
    )
    cache_hit = len(provider_calls) == 0
    print(f"  cache_key        = {cache_key}")
    print(f"  cache hit/miss   = {'HIT' if cache_hit else 'MISS'}")
    print(f"  provider calls   = {len(provider_calls)}")
    print(f"  semantic status  = {semantic_result.status.value}")
    print(f"  semantic count   = {len(semantic_result.candidates)}")
    if len(semantic_result.candidates) != 1:
        raise SystemExit(
            f"{run_label}: expected exactly 1 SEMANTIC candidate, got "
            f"{len(semantic_result.candidates)}. Stopping -- do not patch around this."
        )
    semantic_candidate: ExtractionCandidate = semantic_result.candidates[0]
    print(f"  {semantic_candidate.subject!r} / {semantic_candidate.predicate!r} / {semantic_candidate.object!r}")

    record["cache_key"] = cache_key
    record["cache_hit"] = cache_hit
    record["provider_calls"] = len(provider_calls)
    record["semantic_status"] = semantic_result.status.value
    record["semantic_candidate_count"] = len(semantic_result.candidates)
    record["rule_candidate_json"] = rule_candidate.model_dump(mode="json")
    record["semantic_candidate_json"] = semantic_candidate.model_dump(mode="json")

    _log(f"{run_label}: Candidate -> Fact conversion")
    rule_result = validate_and_build_fact(rule_candidate, RAW_TEXT, source)
    semantic_result_conv = validate_and_build_fact(semantic_candidate, RAW_TEXT, source)
    for label, result in [("RULE", rule_result), ("SEMANTIC", semantic_result_conv)]:
        if result.fact is None:
            raise SystemExit(
                f"{run_label}: {label} candidate REJECTED "
                f"(reason={result.rejection_reason}). Stopping -- record the real "
                f"finding, do not substitute a different fixture."
            )
    rule_fact: Fact = rule_result.fact  # type: ignore[assignment]
    semantic_fact: Fact = semantic_result_conv.fact  # type: ignore[assignment]
    print(f"  RULE fact_id     = {rule_fact.fact_id}")
    print(f"  SEMANTIC fact_id = {semantic_fact.fact_id}")
    record["rule_fact_id"] = str(rule_fact.fact_id)
    record["semantic_fact_id"] = str(semantic_fact.fact_id)
    record["accepted_count"] = 2
    record["rejected_count"] = 0

    all_facts = [rule_fact, semantic_fact]

    _log(f"{run_label}: Stage 2 -- Temporal")
    enriched = enrich_temporally(all_facts)
    print(f"  enriched {len(enriched)} fact(s), cardinality preserved: {len(enriched) == len(all_facts)}")
    record["stage2_fact_count"] = len(enriched)

    _log(f"{run_label}: Stage 3 -- Contradiction Detection")
    contradictions = detect_contradictions(enriched)
    print(f"  {len(contradictions)} contradiction(s)")
    record["stage3_contradiction_count"] = len(contradictions)

    _log(f"{run_label}: Stage 4 -- Authority")
    assessments = infer_authority(enriched, contradictions)
    print(f"  {len(assessments)} assessment(s)")
    record["stage4_assessment_count"] = len(assessments)

    _log(f"{run_label}: Stage 5 -- Resolution")
    resolutions = resolve_contradictions(enriched, contradictions, assessments)
    print(f"  {len(resolutions)} resolution(s)")
    record["stage5_resolution_count"] = len(resolutions)

    record["_stage_input"] = Stage6Input(
        facts=enriched,
        contradictions=contradictions,
        authority_assessments=assessments,
        resolutions=resolutions,
    )
    return record


def main() -> None:
    password = os.environ.get("NEO4J_PASSWORD", "changeme")

    source = _build_fixed_source()
    print(f"Fixed source_id (both runs): {source.source_id}")

    # Shared SemanticCache instance -- this IS the point: Run 2 must see
    # Run 1's cache entry, exactly as a real second invocation would if
    # it used the same on-disk cache directory.
    cache_dir = Path("experiments/semantic_extraction/.cache_step12_demo")
    cache = SemanticCache(cache_dir=cache_dir)

    # Both runs' candidate -> Fact -> Stage 2-5 work is done BEFORE any
    # Neo4j connection is opened, so a Neo4j outage is reported clearly
    # (fail fast) rather than after already doing extraction work, and
    # so this logic is independently inspectable even without a live
    # database available.
    run1 = _run_one_pass("RUN 1", cache, source)
    run2 = _run_one_pass("RUN 2", cache, source)

    client = Neo4jClient(password=password)
    client.verify_connectivity()
    client.create_constraints(CREATE_CONSTRAINTS)

    _log("GRAPH SNAPSHOT: before Run 1")
    before = _graph_snapshot(password)
    for k, v in before.items():
        print(f"\n--- {k} ---\n{v}")

    _log("RUN 1: Stage 6 materialization")
    out1 = materialize(run1.pop("_stage_input"), client)  # type: ignore[arg-type]
    print(f"  Stage6Output: {out1.model_dump()}")
    run1["stage6_output"] = out1.model_dump(mode="json")

    _log("GRAPH SNAPSHOT: after Run 1")
    after_run1 = _graph_snapshot(password)
    for k, v in after_run1.items():
        print(f"\n--- {k} ---\n{v}")

    _log("RUN 2: Stage 6 materialization")
    out2 = materialize(run2.pop("_stage_input"), client)  # type: ignore[arg-type]
    print(f"  Stage6Output: {out2.model_dump()}")
    run2["stage6_output"] = out2.model_dump(mode="json")

    _log("GRAPH SNAPSHOT: after Run 2")
    after_run2 = _graph_snapshot(password)
    for k, v in after_run2.items():
        print(f"\n--- {k} ---\n{v}")

    client.close()

    full_record = {
        "fixed_reference": FIXED_REFERENCE,
        "fixed_source_id": str(source.source_id),
        "run1": run1,
        "run2": run2,
        "graph_before": before,
        "graph_after_run1": after_run1,
        "graph_after_run2": after_run2,
    }
    out_path = Path("verification/results/step12_pipeline_idempotency_record.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(full_record, indent=2, default=str))

    _log("STEP 12: Summary (for the artifact -- interpret manually, A-G)")
    print(f"Run 1: cache={'HIT' if run1['cache_hit'] else 'MISS'}, provider_calls={run1['provider_calls']}, "
          f"rule_fact_id={run1['rule_fact_id']}, semantic_fact_id={run1['semantic_fact_id']}")
    print(f"Run 2: cache={'HIT' if run2['cache_hit'] else 'MISS'}, provider_calls={run2['provider_calls']}, "
          f"rule_fact_id={run2['rule_fact_id']}, semantic_fact_id={run2['semantic_fact_id']}")
    print(f"\nWrote {out_path}")
    print(
        "\nRUN COMPLETE. This script does not itself assert pass/fail -- the "
        "person running it compares the three graph snapshots above (before, "
        "after Run 1, after Run 2) directly and records the real result in "
        "STEP12_FULL_PIPELINE_IDEMPOTENCY_FINDINGS.md, per findings A-G. "
        "Nothing here should be read as a verdict until that comparison is "
        "done against the actual printed Cypher output."
    )


if __name__ == "__main__":
    main()

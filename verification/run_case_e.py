# verification/run_case_e.py
"""
Case E — mixed-source authority verification.

Deliberately separate from run_e2e_case.py so Cases A-D remain exactly
reproducible with that script untouched. This script exercises the one
branch none of A-D can reach: Stage 5's WINNER_SELECTED path and Stage
6's WINNER/SUPERSEDES edges.

Fixed to exactly two files by design, each hardcoded to a specific
SourceType so their authority scores differ under the existing,
unmodified v0.1 policy (stage_4/authority.py, _POLICY_SCORES):

    fixtures/e2e/case_e_winner_supersession_v1.txt  -> SourceType.DATABASE (1.00)
    fixtures/e2e/case_e_winner_supersession_v2.txt  -> SourceType.WEB      (0.40)

No frozen Stage 1-6 code or contract is modified. The only difference
from run_e2e_case.py is that each file's Source is built with a
specific, different source_type instead of both defaulting to
DOCUMENT -- extract() already accepts any SourceType via the
document_source parameter, so this requires no change to extract.py,
authority.py, or any other frozen module.

Usage: python verification/run_case_e.py
(no arguments -- the two fixture files and their source types are
fixed by this script's design, not passed on the command line)
"""
import os
from pathlib import Path
from uuid import uuid4

from contracts.fact_schema import Source, SourceID, SourceType
from contracts.stage_io import Stage6Input
from sage.pipeline.stage_1.extract import extract
from sage.pipeline.stage_2.temporal import enrich_temporally
from sage.pipeline.stage_3.detect import detect_contradictions
from sage.pipeline.stage_4.authority import infer_authority
from sage.pipeline.stage_5.resolve import resolve_contradictions
from sage.pipeline.stage_6.validate import validate_stage6_input
from sage.pipeline.stage_6.materialize import materialize
from sage.pipeline.stage_6.neo4j_client import Neo4jClient
from sage.pipeline.stage_6.queries import CREATE_CONSTRAINTS

# Fixed input set for Case E: (file path, source_type). Not
# parameterized via argv -- this script has exactly one job.
_CASE_E_INPUTS: list[tuple[str, SourceType]] = [
    ("fixtures/e2e/case_e_winner_supersession_v1.txt", SourceType.DATABASE),
    ("fixtures/e2e/case_e_winner_supersession_v2.txt", SourceType.WEB),
]


def main() -> None:
    # ---------------------------------------------------------------
    # STAGE 1 -- Ingestion / Extraction
    # ---------------------------------------------------------------
    print("=" * 70)
    print("STAGE 1: Ingestion / Extraction")
    print("=" * 70)

    all_facts = []
    for path_str, source_type in _CASE_E_INPUTS:
        path = Path(path_str)
        raw_text = path.read_text()
        source = Source(
            source_id=SourceID(str(uuid4())),
            name=path.stem,
            source_type=source_type,
            locator=str(path),
        )
        facts = extract(raw_text, source)
        print(f"{path.name} [source_type={source_type.value}]: extracted {len(facts)} fact(s)")
        for f in facts:
            print(
                f"  fact_id={f.fact_id}"
                f"\n    {f.subject!r} -- {f.predicate!r} -- {f.object!r}"
                f"\n    effective_from={f.effective_from}, effective_to={f.effective_to}"
                f"\n    source_id={f.source.source_id}, source_type={f.source.source_type.value}"
            )
        all_facts.extend(facts)

    if len(all_facts) != 2:
        print(f"\nExpected exactly 2 facts for Case E, got {len(all_facts)}. Stopping.")
        raise SystemExit(1)

    # ---------------------------------------------------------------
    # STAGE 2 -- Temporal Reasoning
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STAGE 2: Temporal Reasoning")
    print("=" * 70)

    enriched_facts = enrich_temporally(all_facts)
    print(f"Enriched {len(enriched_facts)} fact(s) (cardinality preserved: "
          f"{len(enriched_facts) == len(all_facts)})")
    for f in enriched_facts:
        print(f"  {f.fact_id}: effective_from={f.effective_from}, effective_to={f.effective_to}")

    # ---------------------------------------------------------------
    # STAGE 3 -- Contradiction Detection
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STAGE 3: Contradiction Detection")
    print("=" * 70)

    contradictions = detect_contradictions(enriched_facts)
    print(f"Detected {len(contradictions)} contradiction(s)")
    for c in contradictions:
        print(f"  {c.contradiction_id}: conflict_type={c.conflict_type.value}, "
              f"facts={[str(fid) for fid in c.conflicting_fact_ids]}")

    # ---------------------------------------------------------------
    # STAGE 4 -- Authority Inference
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STAGE 4: Authority Inference")
    print("=" * 70)

    assessments = infer_authority(enriched_facts, contradictions)
    print(f"Produced {len(assessments)} authority assessment(s)")
    for a in assessments:
        print(f"  source_id={a.source_id}: authority_score={a.authority_score}")

    # ---------------------------------------------------------------
    # STAGE 5 -- Resolution
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STAGE 5: Resolution")
    print("=" * 70)

    resolutions = resolve_contradictions(enriched_facts, contradictions, assessments)
    print(f"Produced {len(resolutions)} resolution(s)")
    for r in resolutions:
        print(f"  resolution_id={r.resolution_id}")
        print(f"    contradiction_id={r.contradiction_id}")
        print(f"    outcome={r.outcome.value}")
        print(f"    winning_fact_id={r.winning_fact_id}")
        print(f"    superseded_fact_ids={[str(fid) for fid in r.superseded_fact_ids]}")
        print(f"    rationale: {r.rationale}")

    # ---------------------------------------------------------------
    # STAGE 6 -- Validation, Materialization
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STAGE 6: Validation + Materialization")
    print("=" * 70)

    stage_input = Stage6Input(
        facts=enriched_facts,
        contradictions=contradictions,
        authority_assessments=assessments,
        resolutions=resolutions,
    )

    validate_stage6_input(stage_input)
    print("Stage6Input validated OK.")

    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    client = Neo4jClient(password=password)
    client.verify_connectivity()
    client.create_constraints(CREATE_CONSTRAINTS)

    output = materialize(stage_input, client)
    print(f"Stage6Output: {output.model_dump()}")

    client.close()

    print("\n" + "=" * 70)
    print("CASE E RUN COMPLETE")
    print("=" * 70)
    print("\nRecord these IDs for graph verification:")
    for f in enriched_facts:
        print(f"  Fact  {f.fact_id}: {f.object} (source_type={f.source.source_type.value})")
    for c in contradictions:
        print(f"  ContradictionSet {c.contradiction_id}")
    for r in resolutions:
        print(f"  Resolution {r.resolution_id}: winner={r.winning_fact_id}, "
              f"superseded={r.superseded_fact_ids}")


if __name__ == "__main__":
    main()

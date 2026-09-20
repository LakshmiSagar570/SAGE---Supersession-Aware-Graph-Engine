# verification/run_e2e_case.py
"""
Usage: python verification/run_e2e_case.py fixtures/e2e/case_a_new_fact.txt [more_files...]

Runs one or more raw text files through the full frozen SAGE pipeline
(Stage 1-6) against a real Neo4j instance, using the existing stage
functions exactly as they are -- no modification.

Every import below was confirmed against the real source files before
being written here (not assumed from naming convention):

    stage_2/temporal.py   -> enrich_temporally(facts) -> list[Fact]
    stage_3/detect.py     -> detect_contradictions(facts) -> list[ContradictionSet]
    stage_4/authority.py  -> infer_authority(facts, contradictions) -> list[AuthorityAssessment]
    stage_5/resolve.py    -> resolve_contradictions(facts, contradictions, assessments) -> list[Resolution]
    stage_6/validate.py   -> validate_stage6_input(stage_input) -> None (raises on failure)
    stage_6/materialize.py-> materialize(stage_input, client) -> Stage6Output
    stage_6/neo4j_client.py -> Neo4jClient(password=...), .verify_connectivity(), .create_constraints(), .close()
"""
import sys
from pathlib import Path
from datetime import UTC, datetime
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

import os


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python verification/run_e2e_case.py <fixture.txt> [more_files...]")
        sys.exit(1)

    # ---------------------------------------------------------------
    # STAGE 1 -- Ingestion / Extraction
    # ---------------------------------------------------------------
    print("=" * 70)
    print("STAGE 1: Ingestion / Extraction")
    print("=" * 70)

    all_facts = []
    for path_str in sys.argv[1:]:
        path = Path(path_str)
        raw_text = path.read_text()
        source = Source(
            source_id=SourceID(str(uuid4())),
            name=path.stem,
            source_type=SourceType.DOCUMENT,
            locator=str(path),
        )
        facts = extract(raw_text, source)
        print(f"{path.name}: extracted {len(facts)} fact(s)")
        for f in facts:
            print(
                f"  {f.subject!r} -- {f.predicate!r} -- {f.object!r} "
                f"(effective_from={f.effective_from}, effective_to={f.effective_to})"
            )
        all_facts.extend(facts)

    if not all_facts:
        print("\nNo facts extracted from any input file. Stopping -- nothing to pipe forward.")
        sys.exit(1)

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
        print(f"  {r.resolution_id}: contradiction_id={r.contradiction_id}, "
              f"outcome={r.outcome.value}, winning_fact_id={r.winning_fact_id}, "
              f"superseded_fact_ids={[str(fid) for fid in r.superseded_fact_ids]}")
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
    print("E2E RUN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
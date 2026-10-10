import os
import subprocess
from datetime import UTC, datetime

from contracts.fact_schema import (
    AuthorityAssessment,
    ConflictType,
    ContradictionID,
    ContradictionSet,
    Fact,
    FactID,
    FactStatus,
    Resolution,
    ResolutionID,
    ResolutionOutcome,
    Source,
    SourceID,
    SourceType,
)
from contracts.stage_io import Stage6Input
from sage.pipeline.stage_6.materialize import materialize
from sage.pipeline.stage_6.neo4j_client import Neo4jClient
from sage.pipeline.stage_6.queries import CREATE_CONSTRAINTS

password = os.environ.get("NEO4J_PASSWORD", "changeme")

def run_cypher_shell(query: str) -> str:
    res = subprocess.run(
        ["docker", "exec", "sage_neo4j", "cypher-shell", "-u", "neo4j", "-p", password, query],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()

print("--- STEP 1: Wipe database ---")
run_cypher_shell("MATCH (n) DETACH DELETE n;")
print("Database wiped.")

initial_counts = run_cypher_shell("MATCH (n) RETURN count(n) AS nodes, count { MATCH ()-->() } AS rels;")
print(f"Initial counts:\n{initial_counts}\n")

client = Neo4jClient(password=password)
client.verify_connectivity()
client.create_constraints(CREATE_CONSTRAINTS)

now = datetime.now(UTC)
s1 = Source(source_id=SourceID("src-db"), name="DB Source", source_type=SourceType.DATABASE, locator="db://1")
s2 = Source(source_id=SourceID("src-web"), name="Web Source", source_type=SourceType.WEB, locator="https://web.org")

f1 = Fact(
    fact_id=FactID("fact-100"), subject="Acme", predicate="status", object="Active", source=s1,
    evidence="Acme is active.", extracted_at=now, effective_from=now, effective_to=None,
    confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
)
f2 = Fact(
    fact_id=FactID("fact-200"), subject="Acme", predicate="status", object="Closed", source=s2,
    evidence="Acme is closed.", extracted_at=now, effective_from=now, effective_to=None,
    confidence=1.0, status=FactStatus.DISCOVERED, metadata={},
)

c1 = ContradictionSet(
    contradiction_id=ContradictionID("contra-100"),
    conflicting_fact_ids=[f1.fact_id, f2.fact_id],
    conflict_type=ConflictType.DIRECT,
    detected_at=now,
)

a1 = AuthorityAssessment(source_id=s1.source_id, authority_score=1.0, rationale="Database", assessed_at=now)
a2 = AuthorityAssessment(source_id=s2.source_id, authority_score=0.4, rationale="Web", assessed_at=now)

r1 = Resolution(
    resolution_id=ResolutionID("res-100"),
    contradiction_id=c1.contradiction_id,
    outcome=ResolutionOutcome.WINNER_SELECTED,
    winning_fact_id=f1.fact_id,
    superseded_fact_ids=[f2.fact_id],
    rationale="DB outranks Web",
    resolved_at=now,
)

stage_input = Stage6Input(
    facts=[f1, f2],
    contradictions=[c1],
    authority_assessments=[a1, a2],
    resolutions=[r1],
)

print("--- STEP 2: First Materialize Execution ---")
out1 = materialize(stage_input, client)
print(f"Stage6Output 1: {out1.model_dump()}")

counts_after_first = run_cypher_shell(
    "MATCH (n) RETURN count(n) AS nodes, count { MATCH ()-->() } AS rels;"
)
print(f"Direct Neo4j counts via cypher-shell after 1st run:\n{counts_after_first}\n")

labels_after_first = run_cypher_shell(
    "CALL db.labels() YIELD label CALL apoc.cypher.run('MATCH (n:`' + label + '`) RETURN count(n) as count', {}) YIELD value RETURN label, value.count AS count;"
    if False else
    "MATCH (s:Source) WITH count(s) as sources "
    "MATCH (f:Fact) WITH sources, count(f) as facts "
    "MATCH (c:ContradictionSet) WITH sources, facts, count(c) as contradictions "
    "MATCH (a:AuthorityAssessment) WITH sources, facts, contradictions, count(a) as assessments "
    "MATCH (r:Resolution) RETURN sources, facts, contradictions, assessments, count(r) as resolutions;"
)
print(f"Per-node counts after 1st run:\n{labels_after_first}\n")

relationships_after_first = run_cypher_shell(
    "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY rel_type;"
)
print(f"Per-relationship counts after 1st run:\n{relationships_after_first}\n")

print("--- STEP 3: Second Materialize Execution (Same Input) ---")
out2 = materialize(stage_input, client)
print(f"Stage6Output 2: {out2.model_dump()}")

counts_after_second = run_cypher_shell(
    "MATCH (n) RETURN count(n) AS nodes, count { MATCH ()-->() } AS rels;"
)
print(f"Direct Neo4j counts via cypher-shell after 2nd run:\n{counts_after_second}\n")

labels_after_second = run_cypher_shell(
    "MATCH (s:Source) WITH count(s) as sources "
    "MATCH (f:Fact) WITH sources, count(f) as facts "
    "MATCH (c:ContradictionSet) WITH sources, facts, count(c) as contradictions "
    "MATCH (a:AuthorityAssessment) WITH sources, facts, contradictions, count(a) as assessments "
    "MATCH (r:Resolution) RETURN sources, facts, contradictions, assessments, count(r) as resolutions;"
)
print(f"Per-node counts after 2nd run:\n{labels_after_second}\n")

relationships_after_second = run_cypher_shell(
    "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY rel_type;"
)
print(f"Per-relationship counts after 2nd run:\n{relationships_after_second}\n")

assert counts_after_first == counts_after_second, "IDEMPOTENCY FAILED: Node/relationship counts differed!"
assert labels_after_first == labels_after_second, "IDEMPOTENCY FAILED: Per-label counts differed!"
assert relationships_after_first == relationships_after_second, "IDEMPOTENCY FAILED: Per-relationship counts differed!"

print("--- IDEMPOTENCY CONFIRMED CLEANLY: EXACT MATCH ON ALL COUNTS ---")
client.close()

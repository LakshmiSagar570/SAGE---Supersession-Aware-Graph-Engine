"""Verification for Open Item 1: Neo4jClient read-path gap.

Confirms:
1. Neo4jClient.run_in_transaction() returns None (write-only).
2. Implementing run_read_query() allows full verification of graph structure.
3. Tests all skipped/incomplete assertions from tests/integration/test_stage6_neo4j.py.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from contracts.fact_schema import (
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
from sage.pipeline.stage_6.neo4j_client import Neo4jClient, Neo4jTransactionError
from sage.pipeline.stage_6.queries import CREATE_CONSTRAINTS


class ReadableNeo4jClient(Neo4jClient):
    """Extended client providing read access to verify graph state."""

    def run_read_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        with self._driver.session(database=self._database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]


@pytest.fixture(scope="module")
def client() -> Generator[ReadableNeo4jClient, None, None]:
    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    c = ReadableNeo4jClient(password=password)
    c.verify_connectivity()
    c.create_constraints(CREATE_CONSTRAINTS)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def clean_db(client: ReadableNeo4jClient) -> None:
    client.run_in_transaction([
        ("MATCH (n) WHERE n:Source OR n:Fact OR n:ContradictionSet OR n:AuthorityAssessment OR n:Resolution DETACH DELETE n", {})
    ])


def _make_source(source_id: str, source_type: SourceType = SourceType.DOCUMENT) -> Source:
    return Source(
        source_id=SourceID(source_id),
        name=source_id,
        source_type=source_type,
        locator=source_id,
    )


def _make_fact(*, subject: str, predicate: str, obj: str, source: Source) -> Fact:
    now = datetime.now(UTC)
    return Fact(
        fact_id=FactID(str(uuid4())),
        subject=subject,
        predicate=predicate,
        object=obj,
        source=source,
        evidence=f"{subject} {predicate} {obj}.",
        extracted_at=now,
        effective_from=now,
        effective_to=None,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )


def test_verify_run_in_transaction_returns_none(client: ReadableNeo4jClient) -> None:
    # ITEM 1 VERIFICATION: run_in_transaction() returns None
    res = client.run_in_transaction([("RETURN 1", {})])  # type: ignore[func-returns-value]
    assert res is None, "run_in_transaction MUST return None per current implementation"


def test_provenance_relationship_verified_via_read(client: ReadableNeo4jClient) -> None:
    # Completes skipped assertion in TestProvenance.test_from_source_relationship_exists
    source = _make_source("src-1", SourceType.DATABASE)
    fact = _make_fact(subject="A", predicate="rel", obj="B", source=source)
    stage_input = Stage6Input(facts=[fact], contradictions=[], authority_assessments=[], resolutions=[])
    materialize(stage_input, client)

    # Read query verifying relationship actually exists in the database
    records = client.run_read_query(
        "MATCH (f:Fact {fact_id: $fid})-[:FROM_SOURCE]->(s:Source {source_id: $sid}) RETURN f.subject AS subj, s.name AS sname",
        {"fid": str(fact.fact_id), "sid": str(source.source_id)}
    )
    assert len(records) == 1
    assert records[0]["subj"] == "A"
    assert records[0]["sname"] == "src-1"


def test_contradiction_conflicts_verified_via_read(client: ReadableNeo4jClient) -> None:
    # Completes unasserted graph structure in TestContradiction
    s1 = _make_source("s1")
    s2 = _make_source("s2")
    f1 = _make_fact(subject="X", predicate="is", obj="1", source=s1)
    f2 = _make_fact(subject="X", predicate="is", obj="2", source=s2)
    cid = ContradictionID(str(uuid4()))
    cset = ContradictionSet(
        contradiction_id=cid,
        conflicting_fact_ids=[f1.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT,
        detected_at=datetime.now(UTC),
    )
    stage_input = Stage6Input(facts=[f1, f2], contradictions=[cset], authority_assessments=[], resolutions=[])
    materialize(stage_input, client)

    records = client.run_read_query(
        "MATCH (cs:ContradictionSet {contradiction_id: $cid})-[:CONFLICTS]->(f:Fact) RETURN f.fact_id AS fid",
        {"cid": str(cid)}
    )
    returned_fids = {r["fid"] for r in records}
    assert returned_fids == {str(f1.fact_id), str(f2.fact_id)}


def test_resolution_winner_and_supersedes_verified_via_read(client: ReadableNeo4jClient) -> None:
    # Completes unasserted graph structure in TestResolution
    s1 = _make_source("s1", SourceType.DATABASE)
    s2 = _make_source("s2", SourceType.WEB)
    f1 = _make_fact(subject="X", predicate="is", obj="1", source=s1)
    f2 = _make_fact(subject="X", predicate="is", obj="2", source=s2)
    cid = ContradictionID(str(uuid4()))
    cset = ContradictionSet(
        contradiction_id=cid,
        conflicting_fact_ids=[f1.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT,
        detected_at=datetime.now(UTC),
    )
    rid = ResolutionID(str(uuid4()))
    res = Resolution(
        resolution_id=rid,
        contradiction_id=cset.contradiction_id,
        outcome=ResolutionOutcome.WINNER_SELECTED,
        winning_fact_id=f1.fact_id,
        superseded_fact_ids=[f2.fact_id],
        rationale="higher authority",
        resolved_at=datetime.now(UTC),
    )
    stage_input = Stage6Input(facts=[f1, f2], contradictions=[cset], authority_assessments=[], resolutions=[res])
    materialize(stage_input, client)

    resolves = client.run_read_query(
        "MATCH (r:Resolution {resolution_id: $rid})-[:RESOLVES]->(cs:ContradictionSet) RETURN cs.contradiction_id AS cid",
        {"rid": str(rid)}
    )
    assert len(resolves) == 1
    assert resolves[0]["cid"] == str(cid)

    winners = client.run_read_query(
        "MATCH (r:Resolution {resolution_id: $rid})-[:WINNER]->(f:Fact) RETURN f.fact_id AS fid",
        {"rid": str(rid)}
    )
    assert len(winners) == 1
    assert winners[0]["fid"] == str(f1.fact_id)

    supersedes = client.run_read_query(
        "MATCH (r:Resolution {resolution_id: $rid})-[:SUPERSEDES]->(f:Fact) RETURN f.fact_id AS fid",
        {"rid": str(rid)}
    )
    assert len(supersedes) == 1
    assert supersedes[0]["fid"] == str(f2.fact_id)


def test_unresolved_zero_edges_verified_via_read(client: ReadableNeo4jClient) -> None:
    # Completes skipped assertion in TestUnresolved
    s1 = _make_source("s1")
    s2 = _make_source("s2")
    f1 = _make_fact(subject="X", predicate="is", obj="1", source=s1)
    f2 = _make_fact(subject="X", predicate="is", obj="2", source=s2)
    cid = ContradictionID(str(uuid4()))
    cset = ContradictionSet(
        contradiction_id=cid,
        conflicting_fact_ids=[f1.fact_id, f2.fact_id],
        conflict_type=ConflictType.DIRECT,
        detected_at=datetime.now(UTC),
    )
    rid = ResolutionID(str(uuid4()))
    res = Resolution(
        resolution_id=rid,
        contradiction_id=cset.contradiction_id,
        outcome=ResolutionOutcome.UNRESOLVED,
        winning_fact_id=None,
        superseded_fact_ids=[],
        rationale="tie",
        resolved_at=datetime.now(UTC),
    )
    stage_input = Stage6Input(facts=[f1, f2], contradictions=[cset], authority_assessments=[], resolutions=[res])
    materialize(stage_input, client)

    winners = client.run_read_query(
        "MATCH (r:Resolution {resolution_id: $rid})-[:WINNER]->(f) RETURN count(f) AS cnt",
        {"rid": str(rid)}
    )
    assert winners[0]["cnt"] == 0

    supersedes = client.run_read_query(
        "MATCH (r:Resolution {resolution_id: $rid})-[:SUPERSEDES]->(f) RETURN count(f) AS cnt",
        {"rid": str(rid)}
    )
    assert supersedes[0]["cnt"] == 0


def test_idempotency_real_graph_counts_verified_via_read(client: ReadableNeo4jClient) -> None:
    # Completes skipped node/edge count verification in TestIdempotency
    s = _make_source("s-idem")
    f = _make_fact(subject="X", predicate="is", obj="Y", source=s)
    stage_input = Stage6Input(facts=[f], contradictions=[], authority_assessments=[], resolutions=[])

    materialize(stage_input, client)
    cnt1 = client.run_read_query("MATCH (n) RETURN count(n) AS nodes")[0]["nodes"]
    rels1 = client.run_read_query("MATCH ()-[r]->() RETURN count(r) AS rels")[0]["rels"]

    materialize(stage_input, client)
    cnt2 = client.run_read_query("MATCH (n) RETURN count(n) AS nodes")[0]["nodes"]
    rels2 = client.run_read_query("MATCH ()-[r]->() RETURN count(r) AS rels")[0]["rels"]

    assert cnt1 == cnt2 == 2
    assert rels1 == rels2 == 1


def test_rollback_verified_via_read(client: ReadableNeo4jClient) -> None:
    # Completes skipped TestRollback test
    s = _make_source("s-roll")
    statements: list[tuple[str, dict[str, object]]] = [
        ("CREATE (s:Source {source_id: $sid, name: $name, source_type: $st, locator: $loc})",
         {"sid": str(s.source_id), "name": s.name, "st": s.source_type.value, "loc": s.locator}),
        ("THIS IS INVALID CYPHER SYNTAX TO FORCE ROLLBACK", {}),
    ]

    with pytest.raises(Neo4jTransactionError):
        client.run_in_transaction(statements)

    records = client.run_read_query("MATCH (n) RETURN count(n) AS cnt")
    assert records[0]["cnt"] == 0, "Rollback failed: partial nodes remained committed!"

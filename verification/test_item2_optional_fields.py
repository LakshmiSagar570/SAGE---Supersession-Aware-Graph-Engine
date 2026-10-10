"""Verification for Open Item 2: Fact.evidence=None and Source.locator=None.

Contracts:
- Source.locator: str | None = Field(default=None)
- Fact.evidence: str | None = Field(default=None)

Verifies:
1. Pydantic models accept None without validation error.
2. Stages 2 to 5 pass through None without error.
3. Stage 6 queries format None parameters correctly.
4. Stage 6 persists to LIVE Neo4j with None values, and Neo4j stores them as null properties.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from contracts.fact_schema import (
    Fact,
    FactID,
    FactStatus,
    Source,
    SourceID,
    SourceType,
)
from contracts.stage_io import Stage6Input
from sage.pipeline.stage_2.temporal import enrich_temporally
from sage.pipeline.stage_3.detect import detect_contradictions
from sage.pipeline.stage_4.authority import infer_authority
from sage.pipeline.stage_5.resolve import resolve_contradictions
from sage.pipeline.stage_6 import queries
from sage.pipeline.stage_6.materialize import materialize
from sage.pipeline.stage_6.neo4j_client import Neo4jClient
from sage.pipeline.stage_6.queries import CREATE_CONSTRAINTS
from sage.pipeline.stage_6.validate import validate_stage6_input


class ReadableNeo4jClient(Neo4jClient):
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


def test_models_permit_none() -> None:
    now = datetime.now(UTC)
    s = Source(source_id=SourceID("s1"), name="S1", source_type=SourceType.DOCUMENT, locator=None)
    assert s.locator is None

    f = Fact(
        fact_id=FactID(str(uuid4())),
        subject="sub",
        predicate="pred",
        object="obj",
        source=s,
        evidence=None,
        extracted_at=now,
        effective_from=now,
        effective_to=None,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )
    assert f.evidence is None


def test_pipeline_stages_and_live_db_with_none_fields(client: ReadableNeo4jClient) -> None:
    now = datetime.now(UTC)
    s1 = Source(source_id=SourceID("src-none-1"), name="S1", source_type=SourceType.DATABASE, locator=None)
    s2 = Source(source_id=SourceID("src-none-2"), name="S2", source_type=SourceType.WEB, locator=None)

    f1 = Fact(
        fact_id=FactID(str(uuid4())),
        subject="Project Alpha",
        predicate="status is",
        object="Active",
        source=s1,
        evidence=None,
        extracted_at=now,
        effective_from=now,
        effective_to=None,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )
    f2 = Fact(
        fact_id=FactID(str(uuid4())),
        subject="Project Alpha",
        predicate="status is",
        object="Suspended",
        source=s2,
        evidence=None,
        extracted_at=now,
        effective_from=now,
        effective_to=None,
        confidence=1.0,
        status=FactStatus.DISCOVERED,
        metadata={},
    )

    # Stage 2
    enriched = enrich_temporally([f1, f2])
    assert enriched[0].evidence is None
    assert enriched[1].evidence is None

    # Stage 3
    contradictions = detect_contradictions(enriched)
    assert len(contradictions) == 1

    # Stage 4
    assessments = infer_authority(enriched, contradictions)
    assert len(assessments) == 2

    # Stage 5
    resolutions = resolve_contradictions(enriched, contradictions, assessments)
    assert len(resolutions) == 1

    # Stage 6 validate & query check
    stage6_input = Stage6Input(
        facts=enriched,
        contradictions=contradictions,
        authority_assessments=assessments,
        resolutions=resolutions,
    )
    validate_stage6_input(stage6_input)

    _, source_params = queries.merge_sources([s1, s2])
    sources_list = cast(list[dict[str, Any]], source_params["sources"])
    assert sources_list[0]["locator"] is None
    assert sources_list[1]["locator"] is None

    _, fact_params = queries.merge_facts(enriched)
    facts_list = cast(list[dict[str, Any]], fact_params["facts"])
    assert facts_list[0]["evidence"] is None
    assert facts_list[1]["evidence"] is None

    # Live Stage 6 Materialize to Neo4j
    output = materialize(stage6_input, client)
    assert output.status == "COMMITTED"
    assert output.facts_written == 2
    assert output.sources_written == 2

    # Live Database verification: verify properties in Neo4j are indeed null
    fact_records = client.run_read_query(
        "MATCH (f:Fact {fact_id: $fid}) RETURN f.evidence AS ev",
        {"fid": str(f1.fact_id)}
    )
    assert len(fact_records) == 1
    assert fact_records[0]["ev"] is None

    source_records = client.run_read_query(
        "MATCH (s:Source {source_id: $sid}) RETURN s.locator AS loc",
        {"sid": str(s1.source_id)}
    )
    assert len(source_records) == 1
    assert source_records[0]["loc"] is None

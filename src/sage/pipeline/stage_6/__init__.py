"""SAGE pipeline Stage 6 (Graph / Evidence Writing).

VERIFIED in this environment (pytest/Ruff/mypy actually ran and pass):
    validate.py      -- structural validation of Stage6Input
    queries.py        -- pure Cypher query/parameter construction
    materialize.py     -- validate -> sort -> build queries -> execute
                          via TransactionalClient -> Stage6Output
    stage.py          -- thin run_stage6() entry point

UNVERIFIED in this environment (written carefully, never executed --
this sandbox has no network access to any Neo4j instance):
    neo4j_client.py   -- real Neo4j driver wrapper

Stage 6 does not reason: it does not choose winners, infer authority,
detect contradictions, modify Fact semantics, reinterpret Resolution,
or invent any relationship not already justified by Stage 5's output.
It is a deterministic, idempotent (MERGE-based) persistence layer.

See each module's own docstring for full detail, and the top-level
delivery report for the complete VERIFIED/UNVERIFIED breakdown across
every Stage 6 file (including docker-compose.yml, .env.example, and
the integration test suite, none of which live in this package).
"""
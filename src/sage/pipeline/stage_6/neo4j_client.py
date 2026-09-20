"""
Stage 6 — Neo4j Client.

*** UNVERIFIED IN THIS ENVIRONMENT ***

This module has never been executed against a real Neo4j instance.
The sandbox this code was written in has no network access to a
database -- its bash tool is restricted to a fixed package-registry
allowlist (PyPI, npm, GitHub, etc.) and nothing resembling a database
port. This file is careful, considered code, but "careful" and
"verified" are different claims, and this is only the first one.

Before trusting this in any real capacity: run it against an actual
Neo4j instance (e.g. via docker-compose.yml in this same Stage 6
delivery) and confirm tests/integration/test_stage6_neo4j.py actually
passes. Nothing in this file's own correctness has been confirmed by
that process yet.

--------------------------------------------------------------------

Responsibility: own the Neo4j database connection and expose the
minimal surface materialize.py needs (see materialize.py's
TransactionalClient protocol), so the rest of Stage 6 -- and the rest
of SAGE -- never directly manages a Neo4j driver session.

Configuration is via environment variables, never hardcoded
credentials:

    NEO4J_URI       e.g. bolt://localhost:7687
    NEO4J_USERNAME  e.g. neo4j
    NEO4J_PASSWORD  (no default -- must be set)
    NEO4J_DATABASE  e.g. neo4j

All statements passed to run_in_transaction() execute inside ONE
Neo4j transaction: if any statement raises, the whole transaction
rolls back and the exception propagates -- no partial graph state is
left committed. See materialize.py's TransactionalClient protocol for
the exact contract this class must satisfy.
"""

from __future__ import annotations

import os
from typing import Any, Self

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import Neo4jError, ServiceUnavailable
except ImportError:  # pragma: no cover
    # The neo4j driver package may not be installed in every environment
    # this code is imported into (e.g. environments that only run the
    # mock-based unit tests and never touch this file at runtime). Import
    # failure is deferred to first actual use, not raised at import time,
    # so importing stage_6 as a package doesn't require the driver to be
    # installed unless Neo4jClient is actually instantiated.
    GraphDatabase = None  # type: ignore[assignment,misc]
    Neo4jError = Exception  # type: ignore[assignment,misc]
    ServiceUnavailable = Exception  # type: ignore[assignment,misc]


class Neo4jConnectionError(Exception):
    """Raised when the client cannot establish or verify connectivity
    to Neo4j. Distinct from Neo4jTransactionError -- this is a
    connectivity-layer failure, not a write-layer one."""


class Neo4jTransactionError(Exception):
    """Raised when a transaction fails partway through and is rolled
    back. The transaction's statements are NOT retried automatically --
    per spec, v0.1 keeps retry logic out of scope beyond "safe to
    retry because writes are idempotent MERGEs", not an automatic
    retry loop inside this client."""


class Neo4jReadError(Exception):
    """Raised when a read query fails to execute against Neo4j."""


class Neo4jClient:
    """Thin wrapper around the official Neo4j Python driver.

    verify_connectivity(), run_in_transaction(), and run_read_query() are
    the database operations exposed to Stage 6 -- see materialize.py's
    TransactionalClient protocol, which this class satisfies for writes.
    """

    def __init__(
        self,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        """Read connection settings from arguments if given, otherwise
        from environment variables. NEO4J_PASSWORD has no default --
        credentials are never hardcoded, per spec."""
        if GraphDatabase is None:  # pragma: no cover
            raise Neo4jConnectionError(
                "The 'neo4j' driver package is not installed. Install it "
                "(e.g. `pip install neo4j`) before using Neo4jClient."
            )

        self._uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self._username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
        self._password = password or os.environ.get("NEO4J_PASSWORD")
        self._database = database or os.environ.get("NEO4J_DATABASE", "neo4j")

        if not self._password:
            raise Neo4jConnectionError(
                "No Neo4j password configured. Set NEO4J_PASSWORD (or pass "
                "password= explicitly) -- credentials are never hardcoded "
                "or defaulted in this client."
            )

        self._driver = GraphDatabase.driver(
            self._uri, auth=(self._username, self._password)
        )

    def verify_connectivity(self) -> None:
        """Raise Neo4jConnectionError if the database is unreachable.
        Callers should call this before relying on the client for
        writes, rather than discovering connectivity failure mid-batch.
        """
        try:
            self._driver.verify_connectivity()
        except ServiceUnavailable as exc:
            raise Neo4jConnectionError(
                f"Could not reach Neo4j at {self._uri}: {exc}"
            ) from exc

    def run_in_transaction(
        self, statements: list[tuple[str, dict[str, object]]]
    ) -> None:
        """Execute every (query, params) pair in `statements`, in
        order, inside a single Neo4j transaction. Commits only if every
        statement succeeds. Rolls back and raises Neo4jTransactionError
        if any statement fails -- no partial graph state is left
        committed, satisfying materialize.py's TransactionalClient
        protocol.
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.execute_write(self._run_all, statements)
        except Neo4jError as exc:
            raise Neo4jTransactionError(
                f"Neo4j transaction failed and was rolled back: {exc}"
            ) from exc

    def run_read_query(
        self,
        query: str,
        params: dict[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a read Cypher query within an explicit read transaction.

        Returns all records as a list of dicts mapping column names to values.
        Uses driver.execute_read for cluster-aware read routing and automatic
        retry on transient network failures.
        """
        def _read_tx(tx: object) -> list[dict[str, Any]]:
            result = tx.run(query, params or {})  # type: ignore[attr-defined]
            return [dict(record) for record in result.data()]

        try:
            with self._driver.session(database=self._database) as session:
                return session.execute_read(_read_tx)
        except Neo4jError as exc:
            raise Neo4jReadError(f"Neo4j read query failed: {exc}") from exc

    @staticmethod
    def _run_all(tx: object, statements: list[tuple[str, dict[str, object]]]) -> None:
        """Run every statement using the driver-managed transaction
        object `tx`. execute_write already handles commit/rollback: if
        this function raises, the driver rolls back automatically and
        does not commit any of the statements already run within it.
        """
        for query, params in statements:
            tx.run(query, params)  # type: ignore[attr-defined]

    def create_constraints(self, constraint_statements: list[str]) -> None:
        """Run each CREATE CONSTRAINT ... IF NOT EXISTS statement.
        Constraints are schema operations, run outside the per-input
        write transaction (they're idempotent and only need to run
        once per database, typically at startup) rather than bundled
        into every materialize() call.
        """
        try:
            with self._driver.session(database=self._database) as session:
                for statement in constraint_statements:
                    session.run(statement)
        except Neo4jError as exc:
            raise Neo4jTransactionError(
                f"Failed to create Neo4j constraints: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the underlying driver's connection pool."""
        self._driver.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
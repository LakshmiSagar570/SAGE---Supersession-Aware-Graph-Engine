"""
Stage 6 — Orchestration.

Responsibility: the single public Stage 6 entry point.

    Stage6Input
          |
          v
    materialize()
          |
          v
    Stage6Output

No Cypher, no business rules, no authority logic, no contradiction
logic here — this module exists only to give Stage 6 the same thin
entry-point shape as every other stage.
"""

from __future__ import annotations

from contracts.stage_io import Stage6Input, Stage6Output

from .materialize import TransactionalClient, materialize


def run_stage6(stage_input: Stage6Input, client: TransactionalClient) -> Stage6Output:
    """Run the full Stage 6 pipeline: validate, normalize, and
    atomically persist stage_input via client."""
    return materialize(stage_input, client)
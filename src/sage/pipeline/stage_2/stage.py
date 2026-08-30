"""
Stage 2 — Orchestration.

Responsibility: wire enrich_temporally() into the public Stage 2 entry
point.

    Stage2Input
          |
          v
   enrich_temporally()
          |
          v
    Stage2Output

This module contains no temporal reasoning of its own — that logic
lives entirely in temporal.py. stage.py only receives input, delegates,
and constructs output.
"""

from __future__ import annotations

from contracts.stage_io import Stage2Input, Stage2Output

from .temporal import enrich_temporally


def run_stage2(stage_input: Stage2Input) -> Stage2Output:
    """Run the full Stage 2 pipeline: enrich facts temporally."""
    enriched_facts = enrich_temporally(stage_input.facts)
    return Stage2Output(facts=enriched_facts)
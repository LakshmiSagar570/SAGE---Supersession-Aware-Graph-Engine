"""
Stage 5 — Orchestration.

Responsibility: wire resolve_contradictions() into the public Stage 5
entry point.

    Stage5Input
          |
          v
   resolve_contradictions()
          |
          v
    Stage5Output

This module contains no resolution-decision logic of its own — that
lives entirely in resolve.py. stage.py only receives input, delegates,
and constructs output, passing facts, contradictions, and
authority_assessments through unchanged.
"""

from __future__ import annotations

from contracts.stage_io import Stage5Input, Stage5Output

from .resolve import resolve_contradictions


def run_stage5(stage_input: Stage5Input) -> Stage5Output:
    """Run the full Stage 5 pipeline: resolve each contradiction where
    the evidence supports it, pass facts/contradictions/authority
    assessments through unchanged."""
    resolutions = resolve_contradictions(
        stage_input.facts,
        stage_input.contradictions,
        stage_input.authority_assessments,
    )
    return Stage5Output(
        facts=stage_input.facts,
        contradictions=stage_input.contradictions,
        authority_assessments=stage_input.authority_assessments,
        resolutions=resolutions,
    )
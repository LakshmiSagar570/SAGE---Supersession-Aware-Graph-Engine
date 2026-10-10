"""
Stage 4 — Orchestration.

Responsibility: wire infer_authority() into the public Stage 4 entry
point.

    Stage4Input
          |
          v
   infer_authority()
          |
          v
    Stage4Output

This module contains no authority-scoring logic of its own — that
lives entirely in authority.py. stage.py only receives input,
delegates, and constructs output, passing facts and contradictions
through unchanged.
"""

from __future__ import annotations

from contracts.stage_io import Stage4Input, Stage4Output

from .authority import infer_authority


def run_stage4(stage_input: Stage4Input) -> Stage4Output:
    """Run the full Stage 4 pipeline: infer authority for sources
    participating in contradictions, pass facts and contradictions
    through unchanged."""
    assessments = infer_authority(stage_input.facts, stage_input.contradictions)
    return Stage4Output(
        facts=stage_input.facts,
        contradictions=stage_input.contradictions,
        authority_assessments=assessments,
    )
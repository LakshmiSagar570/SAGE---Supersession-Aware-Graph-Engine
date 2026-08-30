"""
Stage 3 — Orchestration.

Responsibility: wire detect_contradictions() into the public Stage 3
entry point.

    Stage3Input
          |
          v
   detect_contradictions()
          |
          v
    Stage3Output

This module contains no contradiction-detection logic of its own —
that lives in pairing.py (candidate pairing) and detect.py (contract
packaging). stage.py only receives input, delegates, and constructs
output, passing facts through unchanged.
"""

from __future__ import annotations

from contracts.stage_io import Stage3Input, Stage3Output

from .detect import detect_contradictions


def run_stage3(stage_input: Stage3Input) -> Stage3Output:
    """Run the full Stage 3 pipeline: detect contradictions, pass facts
    through unchanged."""
    contradictions = detect_contradictions(stage_input.facts)
    return Stage3Output(
        facts=stage_input.facts,
        contradictions=contradictions,
    )
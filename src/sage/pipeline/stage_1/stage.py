"""
src/sage/pipeline/stage_1/stage.py

Stage 1 orchestration: Stage1Input -> Stage1Output.

Ties ingest.py (raw document -> usable text) and extract.py (usable
text -> Fact[]) together behind the single public entry point other
code should call. Callers should use run_stage1(), not ingest()/
extract() directly -- those stay importable for unit testing each
concern in isolation, per the ingestion/extraction separation locked
in design review.
"""

from __future__ import annotations

from contracts.fact_schema import Source, SourceID
from contracts.stage_io import Stage1Input, Stage1Output

from .extract import extract
from .ingest import ingest


def _build_document_source(stage_input: Stage1Input) -> Source:
    """
    Build the Source every extracted Fact will cite, from the
    Stage1Input's own reference/source_type. `name` uses the reference
    itself for v0.1; extracting a friendlier name (e.g. from a
    "Document ID:" header line) is a reasonable future refinement, not
    something this stage needs to guess at now.
    """
    return Source(
        source_id=SourceID(stage_input.reference),
        name=stage_input.reference,
        source_type=stage_input.source_type,
        locator=stage_input.reference,
    )


def run_stage1(stage_input: Stage1Input) -> Stage1Output:
    """Run Stage 1 ingestion + extraction end to end."""
    raw_text = ingest(stage_input)
    document_source = _build_document_source(stage_input)
    facts = extract(raw_text, document_source)
    return Stage1Output(facts=facts)
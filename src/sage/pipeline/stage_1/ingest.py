"""
src/sage/pipeline/stage_1/ingest.py

Stage 1 ingestion: turns a Stage1Input into raw usable text.

This module is deliberately narrow for v0.1: it handles only
SourceType.DOCUMENT with plain-text (.txt) content. It does not fetch
URLs, call APIs, or query databases -- those are future extensions
against the same Stage1Input envelope (see contracts/stage_io.py),
not something this module guesses at or stubs out.

Ingestion and extraction are kept deliberately separate (see extract.py):
this module's only job is "raw document -> usable text". It has no
opinion about what claims that text contains.
"""

from __future__ import annotations

from pathlib import Path

from contracts.fact_schema import SourceType
from contracts.stage_io import Stage1Input


class UnsupportedSourceTypeError(Exception):
    """Raised when Stage 1 ingestion is asked to handle a SourceType it
    does not yet implement. v0.1 supports DOCUMENT only."""


class IngestionError(Exception):
    """Raised when a DOCUMENT source cannot actually be read."""


def ingest(stage_input: Stage1Input) -> str:
    """
    Produce raw text from a Stage1Input.

    v0.1 behavior:
      - source_type must be DOCUMENT. Any other SourceType raises
        UnsupportedSourceTypeError rather than silently guessing at
        WEB/API/DATABASE/OTHER handling that hasn't been designed yet.
      - if raw_payload is already populated (content was already in
        hand when Stage1Input was constructed), it is used directly.
      - if raw_payload is None, `reference` is treated as a local
        filesystem path and read from disk.
    """
    if stage_input.source_type != SourceType.DOCUMENT:
        raise UnsupportedSourceTypeError(
            f"Stage 1 v0.1 supports SourceType.DOCUMENT only; "
            f"received {stage_input.source_type!r}. WEB, API, DATABASE, "
            f"and OTHER extractors are not yet implemented."
        )

    if stage_input.raw_payload is not None:
        raw_text = _decode_payload(stage_input.raw_payload)
    else:
        path = Path(stage_input.reference)
        if not path.is_file():
            raise IngestionError(
                f"DOCUMENT reference does not point to an existing file: "
                f"{stage_input.reference!r}"
            )

        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise IngestionError("input file is not valid UTF-8.") from exc

    return raw_text
def _decode_payload(payload: str | bytes) -> str:
    """Return payload as str, decoding bytes as UTF-8 if necessary."""
    if isinstance(payload, str):
        return payload

    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError(
            "raw_payload bytes are not valid UTF-8."
        ) from exc
def test_malformed_raw_payload_raises_ingestion_error():
    input_data = Stage1Input(
        document_id=...,
        source_path=...,
        raw_payload=b"\xff\xfe\xfd",
    )

    with pytest.raises(IngestionError):
        ingest(input_data)
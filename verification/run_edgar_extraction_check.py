# verification/run_edgar_extraction_check.py
"""
EDGAR real-document validation -- Stage 1 extraction only.

Purpose: measure what the frozen, unmodified Stage 1 extractor actually
does against real SEC filing text, as opposed to the synthetic case_a-e
fixtures. This is deliberately Stage-1-only, not a full Stage 1-6 run --
the question being answered here is "does extraction find anything",
not "does the reasoning pipeline work" (that was already verified
against synthetic fixtures in Cases A-E and the C/D fix).

STRICT SCOPE, per standing instruction: this script does not modify
extract.py, any other frozen Stage 1-6 module, or any contract. It only
calls the existing, unmodified extract() function and reports results.
No LLM, no API, no new extraction patterns. That is deliberately a
later, separate decision.

Fixtures in fixtures/edgar/ are short, real excerpts retrieved via web
search/fetch, not full filings:
  - apple_10k_2024_*.txt: Apple Inc. FY2024 Form 10-K (filed 2024-11-01,
    accession 0000320193-24-000123)
  - tenet_10k_incorporation.txt: Tenet Healthcare Corp Form 10-K
    (COMPANY INFORMATION section, incorporation statement)
  - ict_8k_cfo_appointment.txt: International Commercial Television Inc.
    Form 8-K (2014), Item 5.02 CFO appointment
  - 8x8_8k_cfo_appointment.txt: 8x8, Inc. Form 8-K (2002), Item 5
    Other Events, CFO appointment announcement
"""
import sys
from pathlib import Path
from uuid import uuid4

from contracts.fact_schema import Source, SourceID, SourceType
from sage.pipeline.stage_1.extract import extract

# Each fixture, with a short human note on what it's testing for --
# not asserted programmatically, just printed for context.
_FIXTURES: list[tuple[str, str]] = [
    (
        "fixtures/edgar/apple_10k_2024_properties.txt",
        "Near-miss: real HQ sentence uses 'is located in', not "
        "'is headquartered in' -- does NOT match the frozen pattern "
        "even though it expresses the same fact.",
    ),
    (
        "fixtures/edgar/apple_10k_2024_cybersecurity.txt",
        "Control: real prose naming a role ('Head of Corporate "
        "Information Security') but not in the 'is the {role} of' or "
        "'was appointed {role} of' shape Stage 1 recognizes.",
    ),
    (
        "fixtures/edgar/apple_10k_2024_talent_risk.txt",
        "Control: real risk-factor prose mentioning 'Chief Executive "
        "Officer' as a term, not as a claim about who holds the role.",
    ),
    (
        "fixtures/edgar/tenet_10k_incorporation.txt",
        "Near-miss: real incorporation sentence uses 'was incorporated "
        "in the State of X in YEAR', not 'was founded on YYYY-MM-DD' -- "
        "same fact type (company founding), different real phrasing "
        "and no ISO-format date, so the frozen pattern cannot match "
        "even structurally.",
    ),
    (
        "fixtures/edgar/ict_8k_cfo_appointment.txt",
        "Near-miss: real CFO appointment leads with 'Our Board of "
        "Directors has appointed X as Y', not '{subject} was appointed "
        "{role} of {object} on {date}' -- subject/verb order differs, "
        "date is prose ('effective January 1, 2014') not ISO format, "
        "and the sentence has trailing clauses after the date.",
    ),
    (
        "fixtures/edgar/8x8_8k_cfo_appointment.txt",
        "Near-miss: terser real CFO appointment ('has been appointed "
        "chief financial officer of X') -- passive construction, no "
        "date in the claim sentence at all, additional clause "
        "('replacing David Stoll') breaks the pattern's required "
        "sentence-ending shape.",
    ),
]


def main() -> None:
    print("=" * 70)
    print("EDGAR EXTRACTION CHECK -- Stage 1 only, frozen extractor")
    print("=" * 70)

    total_facts = 0
    for path_str, note in _FIXTURES:
        path = Path(path_str)
        if not path.exists():
            print(f"\n[MISSING FIXTURE] {path_str} -- skipping")
            continue

        raw_text = path.read_text()
        source = Source(
            source_id=SourceID(str(uuid4())),
            name=path.stem,
            source_type=SourceType.DOCUMENT,
            locator=str(path),
        )
        facts = extract(raw_text, source)
        total_facts += len(facts)

        print(f"\n{'-' * 70}")
        print(f"FILE: {path.name}")
        print(f"NOTE: {note}")
        print(f"EXTRACTED: {len(facts)} fact(s)")
        for f in facts:
            print(f"  {f.subject!r} -- {f.predicate!r} -- {f.object!r}")
        if not facts:
            print("  (zero facts extracted from this real excerpt)")

    print(f"\n{'=' * 70}")
    print(f"TOTAL: {total_facts} fact(s) extracted across {len(_FIXTURES)} real excerpt(s)")
    print("=" * 70)


if __name__ == "__main__":
    main()
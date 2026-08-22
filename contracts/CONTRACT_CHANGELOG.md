SAGE v0.1 Contract Baseline
============================

- Canonical Fact model established.
- FactID, SourceID, ContradictionID, ResolutionID established as NewType identifiers.
- Source separated from AuthorityAssessment.
- Fact temporal fields established:
  effective_from, effective_to, extracted_at.
- Fact status vocabulary established.
- ContradictionSet established as Stage 3 output.
- ContradictionSet represents relationships between 2+ distinct facts conceptually.
- AuthorityAssessment established as Stage 4 output.
- Resolution established as Stage 5 output.
- superseded_fact_ids intentionally plural.
- Stage I/O uses explicit named models rather than generics.
- Stage outputs carry cumulative pipeline context.
- Stage 2 mutation policy is behavioral and tested, not encoded in stage_io.py.
- Stage 1 raw_source_reference is explicitly provisional.
- Stage 6 output is intentionally undefined until persistence implementation exists.
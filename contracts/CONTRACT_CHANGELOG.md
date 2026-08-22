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
- Source has a source_type field (DOCUMENT/DATABASE/API/WEB/OTHER);
  these specific categories are a v0.1 addition, not part of earlier
  locked design, and were introduced during contract review.

- Fact temporal fields established: effective_from, effective_to,
  extracted_at -- separating when a fact was true from when SAGE
  learned it, so Stage 3 can distinguish facts that genuinely
  contradict from facts that were both true at different times.
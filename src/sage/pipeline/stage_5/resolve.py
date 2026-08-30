"""
Stage 5 — Resolution.

Responsibility: given an already-established contradiction and the
authority assessments associated with its participating sources,
determine whether the evidence supports a resolution.

    facts: list[Fact]
    contradictions: list[ContradictionSet]
    authority_assessments: list[AuthorityAssessment]
            |
            v
    resolve_contradictions()
            |
            v
    list[Resolution]

Stage 5 does NOT extract facts, infer temporal dates, detect
contradictions, infer authority scores, modify facts, modify statuses,
modify contradiction sets, modify authority assessments, resolve
facts that aren't inside a ContradictionSet, invent missing authority,
break authority ties arbitrarily, or claim that a winning fact is
objectively true.

It DOES: consume established contradictions, consume established
authority assessments, compare available authority evidence, select a
winner when uniquely justified, otherwise return UNRESOLVED, and
produce an auditable Resolution.

--------------------------------------------------------------------
DECISION POLICY (v0.1, deliberately conservative — see spec sections
2, 4, 6):

For each ContradictionSet, look up the authority_score of every
participating fact's source (via its AuthorityAssessment). If any
participating fact's source has no assessment, that's insufficient
evidence — UNRESOLVED, no score is fabricated. Otherwise, find the
maximum score among participants:

    - if exactly one fact holds that maximum -> WINNER_SELECTED,
      that fact wins, every other participating fact is superseded.
    - if two or more facts share that maximum (a tie) -> UNRESOLVED,
      no winner is arbitrarily chosen.

No epsilon/fuzzy-tie tolerance is used — ties are exact float
equality, per spec section 6 ("don't introduce an epsilon unless we
explicitly decide that policy"). No list order, dict iteration order,
or UUID ordering is used as a hidden tiebreaker anywhere in this
policy.

ALL_REJECTED is a valid ResolutionOutcome in the real contract, but
this purely-comparative v0.1 policy has no mechanism to reach it — it
never evaluates a fact's own merit in isolation, only compares
competing facts' source authority against each other. This module
therefore only ever produces WINNER_SELECTED or UNRESOLVED. See
contracts/fact_schema.py's ResolutionOutcome docstring for the same
note from the contract side.
--------------------------------------------------------------------

Provenance: the real Resolution contract has no direct contradiction_id
or assessment_id field. Per spec section 9, this module does not
modify the contract to add one — instead, the full chain (which
contradiction, which facts, which authority evidence) is preserved in
the rationale text itself, using the IDs the contract does expose
(fact_id via winning_fact_id/superseded_fact_ids).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from contracts.fact_schema import (
    AuthorityAssessment,
    ContradictionSet,
    Fact,
    FactID,
    Resolution,
    ResolutionID,
    ResolutionOutcome,
    SourceID,
)


def resolve_contradictions(
    facts: list[Fact],
    contradictions: list[ContradictionSet],
    authority_assessments: list[AuthorityAssessment],
) -> list[Resolution]:
    """Produce one Resolution per ContradictionSet.

    Facts, contradictions, and authority_assessments are only read,
    never mutated. Empty contradictions returns an empty list — Stage 5
    does not manufacture resolutions when there's nothing to resolve.
    """
    if not contradictions:
        return []

    facts_by_id = _index_facts_by_id(facts)
    scores_by_source_id = _index_scores_by_source_id(authority_assessments)

    return [
        _resolve_one_contradiction(contradiction, facts_by_id, scores_by_source_id)
        for contradiction in contradictions
    ]


def _index_facts_by_id(facts: list[Fact]) -> dict[FactID, Fact]:
    return {fact.fact_id: fact for fact in facts}


def _index_scores_by_source_id(
    assessments: list[AuthorityAssessment],
) -> dict[SourceID, float]:
    return {a.source_id: a.authority_score for a in assessments}


def _resolve_one_contradiction(
    contradiction: ContradictionSet,
    facts_by_id: dict[FactID, Fact],
    scores_by_source_id: dict[SourceID, float],
) -> Resolution:
    """Resolve a single ContradictionSet. See module docstring,
    DECISION POLICY, for the full rule."""
    resolved_at = datetime.now(UTC)
    participating_facts = _participating_facts(contradiction, facts_by_id)

    scored_facts = _scores_for_participants(participating_facts, scores_by_source_id)
    if scored_facts is None:
        return _build_unresolved(
            contradiction, participating_facts, resolved_at,
            reason="one or more participating facts has no authority "
            "assessment for its source",
        )

    winner, losers = _select_winner(scored_facts)
    if winner is None:
        return _build_unresolved(
            contradiction, participating_facts, resolved_at,
            reason="the highest authority score is shared by multiple "
            "competing facts (a tie)",
        )

    return _build_winner_selected(contradiction, winner, losers, resolved_at)


def _participating_facts(
    contradiction: ContradictionSet, facts_by_id: dict[FactID, Fact]
) -> list[Fact]:
    """Resolve a ContradictionSet's fact_ids back to actual Fact objects,
    in the order the contradiction lists them."""
    return [
        facts_by_id[fact_id]
        for fact_id in contradiction.conflicting_fact_ids
        if fact_id in facts_by_id
    ]


def _scores_for_participants(
    participating_facts: list[Fact], scores_by_source_id: dict[SourceID, float]
) -> list[tuple[Fact, float]] | None:
    """Look up each participating fact's source's authority score.

    Returns None if ANY participant is missing a score — insufficient
    evidence is grounds for UNRESOLVED for the whole contradiction, not
    a reason to silently drop the unscored fact from consideration.
    """
    scored: list[tuple[Fact, float]] = []
    for fact in participating_facts:
        score = scores_by_source_id.get(fact.source.source_id)
        if score is None:
            return None
        scored.append((fact, score))
    return scored


def _select_winner(
    scored_facts: list[tuple[Fact, float]],
) -> tuple[Fact | None, list[Fact]]:
    """Given (fact, score) pairs, return (winner, losers) if there's a
    unique maximum, or (None, []) if the maximum is tied.

    Exact float equality is used for tie detection — no epsilon
    tolerance, per spec section 6. No list order or any other hidden
    tiebreaker is used: ties are always resolved to (None, []).
    """
    max_score = max(score for _, score in scored_facts)
    at_max = [fact for fact, score in scored_facts if score == max_score]

    if len(at_max) != 1:
        return None, []

    winner = at_max[0]
    losers = [fact for fact, _ in scored_facts if fact.fact_id != winner.fact_id]
    return winner, losers


def _build_winner_selected(
    contradiction: ContradictionSet,
    winner: Fact,
    losers: list[Fact],
    resolved_at: datetime,
) -> Resolution:
    rationale = (
        f"Resolution for contradiction {contradiction.contradiction_id} "
        f"({contradiction.conflict_type.value}): fact {winner.fact_id} "
        f"(source {winner.source.source_id}) was selected because its "
        f"source received a higher authority policy score than the "
        f"{len(losers)} competing fact(s) it superseded "
        f"({', '.join(str(f.fact_id) for f in losers)}, from source(s) "
        f"{', '.join(str(f.source.source_id) for f in losers)}). This "
        f"reflects the v0.1 source-authority policy documented in "
        f"docs/authority_policy.md and is not a determination of "
        f"objective factual truth."
    )
    return Resolution(
        resolution_id=ResolutionID(str(uuid4())),
        outcome=ResolutionOutcome.WINNER_SELECTED,
        winning_fact_id=winner.fact_id,
        superseded_fact_ids=[f.fact_id for f in losers],
        rationale=rationale,
        resolved_at=resolved_at,
    )


def _build_unresolved(
    contradiction: ContradictionSet,
    participating_facts: list[Fact],
    resolved_at: datetime,
    *,
    reason: str,
) -> Resolution:
    fact_ids = ", ".join(str(f.fact_id) for f in participating_facts)
    rationale = (
        f"Resolution for contradiction {contradiction.contradiction_id} "
        f"({contradiction.conflict_type.value}) among facts [{fact_ids}]: "
        f"no winner was selected because {reason}. The available "
        f"evidence does not establish a unique resolution under the "
        f"v0.1 authority policy."
    )
    return Resolution(
        resolution_id=ResolutionID(str(uuid4())),
        outcome=ResolutionOutcome.UNRESOLVED,
        winning_fact_id=None,
        superseded_fact_ids=[],
        rationale=rationale,
        resolved_at=resolved_at,
    )
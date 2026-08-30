"""
Stage 3 — Contradiction-candidate pairing logic (contract-independent).

This module implements every part of Stage 3's detection logic that does
NOT depend on the shape of the real ContradictionSet contract:

    - pairwise semantic compatibility (same subject + predicate,
      different object)
    - temporal interval overlap, including effective_to=None handling
    - canonical pair ordering (deterministic, not loop-order-dependent)
    - duplicate-pair suppression across 3+ facts

It deliberately does NOT construct, import, or assume any shape for
ContradictionSet. The public function here, find_contradiction_pairs(),
returns plain tuple[Fact, Fact] pairs — the raw candidates a future
detect.py will wrap into whatever the real ContradictionSet contract
turns out to require. Per the Stage 3 spec (section 14), that contract
must be inspected from the real contracts/fact_schema.py, not
recreated from memory, so no ContradictionSet-shaped code exists here.

No Fact is ever mutated. This module only reads facts and returns
information about which pairs are contradiction candidates.

--------------------------------------------------------------------
DOCUMENTED TEMPORAL SEMANTICS (per spec section 6's requirement to
document the exact interval comparison implemented):

    effective_to = None means the claim is understood to still be in
    effect as of "now" — an open interval [effective_from, +infinity)
    — NOT "unknown duration" and NOT "no temporal claim exists".

    This reading is the only one consistent with the spec's own
    worked example in section 5/F: two open-ended claims
    (effective_from=2020/None and effective_from=2022/None) are
    explicitly called a contradiction, which only holds if both
    open intervals are compared as overlapping through the present.

    Two intervals [A_start, A_end] and [B_start, B_end] overlap iff:

        A_start <= B_end  AND  B_start <= A_end

    where a None end is treated as +infinity for this comparison.
    This is a conservative, standard interval-overlap test — it does
    not attempt to infer or guess any date that isn't already present
    on the Fact.
--------------------------------------------------------------------
"""

from __future__ import annotations

from itertools import combinations

from contracts.fact_schema import Fact, FactID


def find_contradiction_pairs(facts: list[Fact]) -> list[tuple[Fact, Fact]]:
    """Return every pair of facts that are contradiction candidates.

    A pair is a candidate iff:
        - same subject
        - same predicate
        - different object
        - overlapping temporal validity
        - NOT the identical claim (same subject+predicate+object is
          never a contradiction, regardless of temporal overlap)

    Results are deterministic:
        - each unordered pair appears at most once (canonical
          ordering, not affected by input list order or loop order)
        - output list is sorted by the pair's canonical fact_id
          ordering, so repeated calls on the same input always
          produce the same output in the same order

    No Fact is mutated. Empty input returns an empty list.
    """
    candidate_pairs = [
        _canonical_pair(fact_a, fact_b)
        for fact_a, fact_b in combinations(facts, 2)
        if _is_contradiction_candidate(fact_a, fact_b)
    ]

    # Fact is a Pydantic BaseModel with mutable fields (dict metadata),
    # so it's unhashable and can't go directly into a set. Deduplicating
    # via a str-based key derived from each pair's canonical fact_ids
    # gives the same structural guarantee — combinations() already
    # visits each unordered pair once, and canonical fact_id ordering
    # means any accidental re-derivation of the same pair collapses to
    # the same key — without requiring Fact itself to be hashable,
    # which would mean touching the contract.
    seen_keys: set[tuple[str, str]] = set()
    unique_pairs: list[tuple[Fact, Fact]] = []
    for pair in candidate_pairs:
        key = _pair_sort_key(pair)
        if key not in seen_keys:
            seen_keys.add(key)
            unique_pairs.append(pair)

    return sorted(unique_pairs, key=_pair_sort_key)


def _is_contradiction_candidate(fact_a: Fact, fact_b: Fact) -> bool:
    """Apply the full semantic + temporal contradiction test to one pair."""
    if fact_a.subject != fact_b.subject:
        return False
    if fact_a.predicate != fact_b.predicate:
        return False
    if fact_a.object == fact_b.object:
        # Identical claim (same subject+predicate+object) is never a
        # contradiction, no matter what the temporal fields say.
        return False

    return _temporal_intervals_overlap(fact_a, fact_b)


def _temporal_intervals_overlap(fact_a: Fact, fact_b: Fact) -> bool:
    """See module docstring for the documented interval-overlap semantics.

    effective_to=None is treated as an open upper bound (+infinity),
    not as "unknown" — see the DOCUMENTED TEMPORAL SEMANTICS section
    above for why.
    """
    a_start, a_end = fact_a.effective_from, fact_a.effective_to
    b_start, b_end = fact_b.effective_from, fact_b.effective_to

    a_start_before_or_at_b_end = b_end is None or a_start <= b_end
    b_start_before_or_at_a_end = a_end is None or b_start <= a_end

    return a_start_before_or_at_b_end and b_start_before_or_at_a_end


def _canonical_pair(fact_a: Fact, fact_b: Fact) -> tuple[Fact, Fact]:
    """Order a pair deterministically by fact_id, so (A, B) and (B, A)
    are always represented identically regardless of encounter order.

    Per spec section 10: "fact_id A < fact_id B can establish canonical
    pair ordering." Comparison goes through _fact_id_sort_key (string
    form) rather than comparing UUID objects directly, so this ordering
    always matches the one used for final list sorting in
    find_contradiction_pairs — using two different comparison bases for
    "which fact comes first in a pair" versus "how pairs are sorted"
    would be an easy source of inconsistency.
    """
    if _fact_id_sort_key(fact_a.fact_id) <= _fact_id_sort_key(fact_b.fact_id):
        return (fact_a, fact_b)
    return (fact_b, fact_a)


def _pair_sort_key(
    pair: tuple[Fact, Fact],
) -> tuple[str, str]:
    """Deterministic sort key for the final output list ordering."""
    first, second = pair
    return (_fact_id_sort_key(first.fact_id), _fact_id_sort_key(second.fact_id))


def _fact_id_sort_key(fact_id: FactID) -> str:
    """FactID is already a str-based type, but funneling through a single
    named helper keeps the "what are we sorting by" decision in one
    place rather than repeated inline, in case fact_id's underlying
    representation needs revisiting again."""
    return str(fact_id)
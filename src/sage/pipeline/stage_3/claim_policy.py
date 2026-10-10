# src/sage/pipeline/stage_3/claim_policy.py
"""
Stage 3 -- semantic claim-key derivation policy.

This module is the entire implementation of the accepted Stage 3
semantic-identity design (v2). It exists so that pairing.py's
contradiction-candidate test can compare facts by the slot they
actually contest, rather than always assuming the subject field is
that slot.

DELIBERATE SCOPE, per the accepted design:
    - contracts/fact_schema.py is NOT modified and is not imported for
      write access here -- this module only reads Fact fields that
      already exist today (subject, predicate, object).
    - stage_1/extract.py is NOT modified. This module has no awareness
      of extract.py at import time; it only recognizes the *shape* of
      predicate strings extract.py happens to already produce, via
      plain prefix/suffix matching -- not by importing anything from
      Stage 1.
    - This module does NOT attempt entity resolution. "CEO" and "Chief
      Executive Officer" are treated as different claim types. This is
      a named, accepted limitation, not a bug.
    - This module does NOT attempt to model co-occupied roles (e.g.
      legitimate co-CEOs). Every OBJECT_ANCHORED claim type is assumed
      single-occupancy. This is a named, accepted v0.1 limitation.

WHY SHAPE-MATCHING, NOT A PREDICATE STRING LOOKUP TABLE:
    Fact.predicate is not drawn from a fixed enum. Two of Stage 1's
    four extraction patterns use a predicate_template containing a
    {role} placeholder ("was appointed {role} of", "is the {role} of"),
    interpolated with whatever free-text role Stage 1's regex captured.
    The resulting predicate strings ("is the Chief Executive Officer
    of", "is the Chairman of", ...) are therefore unbounded -- an exact
    string lookup table would silently fail to recognize any role text
    not already enumerated. Matching on the fixed (prefix, suffix)
    shape of the *template*, and extracting the role text from between
    them, correctly generalizes to any role Stage 1's existing patterns
    can produce, without needing to know what specific roles exist.

    Only "is headquartered in" and "was founded on" are genuinely fixed
    literal predicate strings; everything else in the object-anchored
    set is a shape, not a literal.
"""

from __future__ import annotations

from typing import NamedTuple

from contracts.fact_schema import Fact

# (prefix, suffix) pairs matching the two role-shaped predicate
# templates that currently exist in stage_1/extract.py:
#     "was appointed {role} of"
#     "is the {role} of"
#
# A predicate matching one of these shapes is treated as
# OBJECT_ANCHORED: the object (company) is the contested slot's
# anchor, and the subject (person) is the value being contested for
# that slot.
#
# Any predicate NOT matching one of these shapes falls back to
# SUBJECT_ANCHORED, which reproduces today's existing behavior exactly
# (subject = anchor, object = contested value). This includes both of
# Stage 1's non-role-shaped predicates ("is headquartered in", "was
# founded on") and, deliberately, any predicate this policy doesn't
# recognize -- an unrecognized shape must never be silently treated as
# OBJECT_ANCHORED, since that could fabricate contradictions between
# facts that were never actually competing claims about the same slot.
_OBJECT_ANCHORED_SHAPES: list[tuple[str, str]] = [
    ("is the ", " of"),
    ("was appointed ", " of"),
]


class ClaimKey(NamedTuple):
    """The result of interpreting one Fact for contradiction-candidate
    comparison purposes.

    anchor + claim_type together identify "the same contested slot".
    contested_value is the value being claimed for that slot.

    Two facts are Stage 3 contradiction candidates only if their
    (anchor, claim_type) match, their contested_value differs, and
    (per pairing.py, unchanged by this module) their temporal
    intervals overlap.
    """

    anchor: str
    claim_type: str
    contested_value: str


def derive_claim_key(fact: Fact) -> ClaimKey:
    """Derive the contradiction-candidate identity key for one Fact.

    This is a pure function: it only reads fact.subject, fact.predicate,
    and fact.object. It never mutates the Fact and never reads or
    writes any field outside those three.
    """
    role = _extract_object_anchored_role(fact.predicate)

    if role is not None:
        # OBJECT_ANCHORED: the object (e.g. a company) is the anchor;
        # the role text (normalized) is the claim type; the subject
        # (e.g. a person) is the contested value.
        return ClaimKey(
            anchor=fact.object,
            claim_type=_normalize_role(role),
            contested_value=fact.subject,
        )

    # SUBJECT_ANCHORED (default): reproduces today's existing
    # comparison exactly -- subject is the anchor, predicate is the
    # claim type, object is the contested value.
    return ClaimKey(
        anchor=fact.subject,
        claim_type=fact.predicate,
        contested_value=fact.object,
    )


def _extract_object_anchored_role(predicate: str) -> str | None:
    """Return the role text if `predicate` matches one of the known
    object-anchored predicate shapes, else None.

    Matching is exact prefix/suffix containment -- not a regex, and not
    a lookup of the role text itself. Only the shape around the role is
    checked; the role text in between can be anything.
    """
    for prefix, suffix in _OBJECT_ANCHORED_SHAPES:
        if predicate.startswith(prefix) and predicate.endswith(suffix):
            start = len(prefix)
            end = len(predicate) - len(suffix)
            if start < end:
                # Guards against a degenerate predicate that is only
                # the prefix+suffix with no role text between them
                # (e.g. a malformed "is the  of") -- such a predicate
                # does not represent a real role claim and should not
                # be treated as one.
                return predicate[start:end]
    return None


def _normalize_role(role: str) -> str:
    """Normalize role text for claim-type comparison.

    Deliberately minimal: case- and whitespace-normalization only.
    This does NOT attempt synonym resolution -- "CEO" and "Chief
    Executive Officer" remain different claim types after this
    normalization. That is a named, accepted limitation (see module
    docstring), not an oversight.
    """
    return role.strip().lower()
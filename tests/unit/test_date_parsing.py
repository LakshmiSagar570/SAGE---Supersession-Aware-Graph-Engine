"""Phase 4C Step 8 -- bare-year date parsing (Phase 4B section 4, Fix 2).

Scope, per the plan: extend _parse_effective_from with "%Y", with the
mandatory precision-loss comment at the parsing site. Nothing else.

Required verifications from PHASE4C_IMPLEMENTATION_PLAN.md Step 8:
  - "1975" parses to 1975-01-01 with the precision-loss comment present
    at the parsing site (a code-review-level check, not just a runtime
    assertion).
  - existing formats (%Y-%m-%d, %B %d, %Y, %b %d, %Y) still parse
    correctly, unchanged from Phase 2.
  - an unparseable effective_from_text still falls back to extracted_at,
    unchanged from Phase 2.

Also covers the real Step 6 finding this step exists to fix (Tenet's
"1975"), and structural guards against two plausible regressions: %Y
shadowing a full date, and %Y being tried before the more specific
formats in a way that would change behavior for ambiguous input.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import UTC, datetime

import pytest

from experiments.semantic_extraction.candidate import _parse_effective_from

FALLBACK = datetime(2099, 12, 31, tzinfo=UTC)


# ---------------------------------------------------------------- bare year


def test_bare_year_parses_to_january_first() -> None:
    result = _parse_effective_from("1975", fallback=FALLBACK)
    assert result == datetime(1975, 1, 1, tzinfo=UTC)


def test_bare_year_is_timezone_aware_utc() -> None:
    result = _parse_effective_from("1975", fallback=FALLBACK)
    assert result.tzinfo == UTC


def test_bare_year_with_surrounding_whitespace() -> None:
    # _parse_effective_from already strips whitespace for every format;
    # bare year must not be treated specially here.
    assert _parse_effective_from("  1975  ", fallback=FALLBACK) == datetime(
        1975, 1, 1, tzinfo=UTC
    )


def test_bare_year_with_trailing_period() -> None:
    # Existing .rstrip(".") handling applies uniformly to the new format too.
    assert _parse_effective_from("1975.", fallback=FALLBACK) == datetime(
        1975, 1, 1, tzinfo=UTC
    )


def test_real_tenet_value_from_step6() -> None:
    # The actual value SEMANTIC captured for Tenet after the Step 6 prompt
    # correction (effective_from_text="1975", previously fell back to
    # extracted_at because the parser had no %Y format). This is the
    # concrete real-world case Step 8 exists to fix.
    result = _parse_effective_from("1975", fallback=FALLBACK)
    assert result == datetime(1975, 1, 1, tzinfo=UTC)
    assert result != FALLBACK


# ---------------------------------------------------- existing formats intact


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2014-01-01", datetime(2014, 1, 1, tzinfo=UTC)),
        ("2025-03-01", datetime(2025, 3, 1, tzinfo=UTC)),
        ("January 1, 2014", datetime(2014, 1, 1, tzinfo=UTC)),
        ("Jan 1, 2014", datetime(2014, 1, 1, tzinfo=UTC)),
        ("March 1, 2025", datetime(2025, 3, 1, tzinfo=UTC)),
    ],
)
def test_existing_full_date_formats_unchanged(text: str, expected: datetime) -> None:
    assert _parse_effective_from(text, fallback=FALLBACK) == expected


def test_full_dates_are_not_shadowed_by_bare_year_format() -> None:
    # A year-month-day string must not be mistakenly accepted by "%Y" --
    # strptime("%Y") requires the ENTIRE string to be exactly a bare year,
    # so "2025-03-01" cannot match it. This pins that down explicitly so a
    # future change to %Y's position or matching can't silently regress
    # real appointment dates into January 1st.
    result = _parse_effective_from("2025-03-01", fallback=FALLBACK)
    assert result == datetime(2025, 3, 1, tzinfo=UTC)
    assert result.month == 3
    assert result.day == 1


# -------------------------------------------------------- invalid / fallback


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "not a date",
        "75",  # two-digit year -- deliberately not accepted
        "1975-13",  # not a real existing format
        "circa 1975",
        "Q1 1975",
    ],
)
def test_unparseable_or_missing_text_falls_back(text: str | None) -> None:
    assert _parse_effective_from(text, fallback=FALLBACK) == FALLBACK


def test_four_digit_non_year_looking_string_rejected_as_before() -> None:
    # "0000" is syntactically %Y-shaped; confirm this is accepted the same
    # way any other 4-digit year is -- not a new rejection rule, just
    # characterizing current, unchanged behavior under the new format.
    result = _parse_effective_from("0000", fallback=FALLBACK)
    assert result == datetime(1, 1, 1, tzinfo=UTC) or result == FALLBACK
    # (datetime.strptime("0000", "%Y") raises in CPython -- year 0 is
    # invalid -- so this must fall back, not crash.)
    assert result == FALLBACK


# --------------------------------------------- precision-loss code comment


def test_precision_loss_comment_present_at_parsing_site() -> None:
    source = textwrap.dedent(inspect.getsource(_parse_effective_from))
    assert "PRECISION-LOSS" in source or "precision-loss" in source.lower()
    assert "%Y" in source
    # Required content per Phase 4B section 4: must not claim the day is
    # known, must explain why January 1 is used at all.
    lowered = source.lower()
    assert "does not" in lowered or "not assert" in lowered
    assert "january 1" in lowered or "day is" in lowered or "day portion" in lowered


def test_comment_is_attached_to_the_year_branch_not_generic() -> None:
    # Structural check: the comment must sit inside the loop, associated
    # with the %Y case specifically -- not just floating anywhere in the
    # module where it wouldn't be encountered by a reader of the parsing
    # logic itself.
    tree = ast.parse(textwrap.dedent(inspect.getsource(_parse_effective_from)))
    source_lines = textwrap.dedent(inspect.getsource(_parse_effective_from)).splitlines()
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # crude but sufficient: an `if fmt == "%Y":` guard whose body
            # or immediately preceding lines carry the precision-loss text
            test_src = ast.unparse(node.test)
            if "%Y" not in test_src:
                continue
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            seg = "\n".join(source_lines[max(0, node.lineno - 1) : end + 6])
            if "PRECISION-LOSS" in seg:
                found = True
    assert found, "precision-loss comment not structurally tied to the %Y branch"


# ------------------------------------------------------- format list itself


def test_precision_loss_guard_checks_exactly_bare_year() -> None:
    # Direct check that the `if fmt == ...:` guard tests for "%Y" itself,
    # not some other format string. Catches a mutant where the guard
    # condition drifts to compare against a different (possibly
    # always/never-true) value while leaving candidate_formats intact.
    tree = ast.parse(textwrap.dedent(inspect.getsource(_parse_effective_from)))
    guard_values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            left = node.test.left
            comparators = node.test.comparators
            if (
                isinstance(left, ast.Name)
                and left.id == "fmt"
                and len(comparators) == 1
            ):
                comparator = comparators[0]
                if isinstance(comparator, ast.Constant) and isinstance(
                    comparator.value, str
                ):
                    guard_values.append(comparator.value)
    assert guard_values == ["%Y"], guard_values


def test_candidate_formats_list_is_exactly_the_locked_four() -> None:
    source = inspect.getsource(_parse_effective_from)
    assert '["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%Y"]' in source


def test_no_new_formats_beyond_the_locked_four() -> None:
    # Guards the hard scope boundary: Step 8 adds exactly one format.
    # A naive "%Y/%m/%d" or "%m-%d-%Y" or similar addition must fail this.
    # Scoped to the candidate_formats list literal only -- "%Y" legitimately
    # appears a second time in the `if fmt == "%Y":` precision-loss guard,
    # which is not part of the format list itself.
    tree = ast.parse(textwrap.dedent(inspect.getsource(_parse_effective_from)))
    list_node = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "candidate_formats"
        ):
            list_node = node.value
    assert isinstance(list_node, ast.List)
    formats_in_source: list[str] = []
    for elt in list_node.elts:
        assert isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        formats_in_source.append(elt.value)
    assert formats_in_source == ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%Y"]

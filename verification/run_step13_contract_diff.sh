#!/usr/bin/env bash
# Phase 4C Step 13, criterion 6 -- explicit diff of contracts/fact_schema.py
# and Stage 2-6 against their pre-Phase-4C state.
#
# WHY THIS RUNS AGAINST GIT HISTORY, NOT A RECONSTRUCTED FILE: the only
# trustworthy "pre-4C" baseline is Sagar's own repository's commit
# history -- every step in this project has been committed and tagged
# as it completed, and PHASE4C_IMPLEMENTATION_PLAN.md's own summary
# table states explicitly which files were supposed to stay untouched
# through Steps 2-12. This script finds the real commit that predates
# Phase 4C Step 7 (the earliest Phase 4C-tagged commit this
# conversation has direct knowledge of) and diffs the current working
# tree against it for exactly the two file sets the plan says must be
# unchanged. It does NOT invent or reconstruct file content from
# memory.
#
# WHAT "PRE-4C" MEANS HERE, PRECISELY: PHASE4C_IMPLEMENTATION_PLAN.md's
# own Step 1 says the 150-test baseline was captured "before any file
# in this plan is created or edited." Steps 1-6 were committed by
# Sagar directly (not through an installer this conversation produced)
# before phase4c-step7 existed as a tag. This script therefore treats
# the commit immediately BEFORE the earliest commit reachable from
# phase4c-step7 that already contains Step 7's changes as the
# practical "pre-Phase-4C" baseline for files that should never change
# throughout ANY of Phase 4C -- contracts/fact_schema.py and Stage 2-6.
# If Sagar's repository has an explicit tag or commit marking the true
# end of Step 1 / start of Step 2, that is a MORE precise baseline than
# this script's heuristic -- see the --baseline option below to use it
# directly instead.
#
# Usage:
#   bash verification/run_step13_contract_diff.sh [--baseline <ref>]
#
#   --baseline <ref>   Git ref to diff against (commit SHA, tag, or
#                       branch). If omitted, the script finds the
#                       parent of the earliest commit that already
#                       contains the Step 7 predicate-normalization
#                       marker, and uses that as the baseline --
#                       printed explicitly before any comparison runs,
#                       so the exact ref used is never silently
#                       assumed.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

FILES=(
  "contracts/fact_schema.py"
  "src/sage/pipeline/stage_2"
  "src/sage/pipeline/stage_3"
  "src/sage/pipeline/stage_4"
  "src/sage/pipeline/stage_5"
  "src/sage/pipeline/stage_6"
)

BASELINE=""
if [ "${1:-}" = "--baseline" ]; then
  BASELINE="$2"
fi

if [ -z "$BASELINE" ]; then
  if git rev-parse -q --verify "refs/tags/phase4c-step6" >/dev/null; then
    # The precise, correct baseline: the explicit tag marking the end
    # of Step 6 / before any of Steps 7-12's changes exist. Preferred
    # over any heuristic search whenever it exists, since it is an
    # intentional marker Sagar created, not an inference.
    BASELINE="phase4c-step6"
    echo "Using the explicit 'phase4c-step6' tag as the pre-Phase-4C-Step-7"
    echo "baseline (the most precise baseline available -- end of Step 6,"
    echo "before any of Steps 7-12's changes)."
  else
    echo "No 'phase4c-step6' tag found and no --baseline given; falling"
    echo "back to locating the commit that first introduced Step 7's"
    echo "normalize_semantic_predicate marker, then using its PARENT"
    echo "commit as the baseline. This fallback is LESS precise than an"
    echo "explicit phase4c-step6 tag -- if this repository predates that"
    echo "tagging convention, pass --baseline <ref> explicitly instead,"
    echo "naming whatever commit/tag you know marks the true end of"
    echo "Step 1 / before Step 2 began, for the most defensible result."
    STEP7_COMMIT=$(git log --all --reverse --format="%H" -S "normalize_semantic_predicate" -- experiments/semantic_extraction/candidate.py | head -1)
    if [ -z "$STEP7_COMMIT" ]; then
      echo "ABORT: could not locate a commit introducing normalize_semantic_predicate."
      echo "Pass --baseline <ref> explicitly."
      exit 1
    fi
    BASELINE="${STEP7_COMMIT}^"
    echo "Found Step 7 commit: $STEP7_COMMIT"
  fi
fi

RESOLVED_BASELINE=$(git rev-parse "$BASELINE")
echo ""
echo "Baseline ref:      $BASELINE"
echo "Resolved to commit: $RESOLVED_BASELINE"
git log -1 --format="  %H %ci %s" "$RESOLVED_BASELINE"
echo ""
echo "Current HEAD:"
git log -1 --format="  %H %ci %s" HEAD
echo ""
echo "======================================================================"
echo "Diffing baseline -> HEAD for the files that must be unchanged"
echo "throughout all of Phase 4C (contracts/fact_schema.py, Stage 2-6):"
echo "======================================================================"
echo ""

ANY_CHANGE=0
for f in "${FILES[@]}"; do
  echo "--- $f ---"
  if git diff --quiet "$RESOLVED_BASELINE" HEAD -- "$f"; then
    echo "  (no changes)"
  else
    echo "  CHANGED:"
    git --no-pager diff --stat "$RESOLVED_BASELINE" HEAD -- "$f"
    ANY_CHANGE=1
  fi
  echo ""
done

echo "======================================================================"
if [ "$ANY_CHANGE" = 0 ]; then
  echo "RESULT: NO CHANGES to contracts/fact_schema.py or Stage 2-6 between"
  echo "$RESOLVED_BASELINE and HEAD. Criterion 6 PASSES against this baseline."
  if [ "$BASELINE" != "phase4c-step6" ]; then
    echo ""
    echo "NOTE: this baseline marks the start of Step 7, not necessarily the"
    echo "true start of Phase 4C (before Step 2). Per the plan, Steps 2-6"
    echo "only ever READ contracts/fact_schema.py (never modified it -- Step"
    echo "9's own explicit, non-negotiable rule is that any detected change"
    echo "to fact_schema.py reverts immediately), and Stage 2-6 were already"
    echo "frozen and verified before Phase 4C began at all (per"
    echo "SAGE_V01_E2E_VERIFICATION_REPORT.md). So a clean diff from this"
    echo "baseline is strong evidence for the full-Phase-4C claim, but it is"
    echo "not a literal diff all the way back to before Step 2 unless a tag"
    echo "or commit from that point is passed via --baseline."
  fi
else
  echo "RESULT: CHANGES DETECTED in one or more files above. Criterion 6"
  echo "FAILS as stated -- do not silently explain this away. Report it,"
  echo "inspect the real diff above, and determine whether it is a genuine"
  echo "regression or a difference between this baseline heuristic and the"
  echo "true end of Step 1 (re-run with an explicit --baseline if so)."
fi
echo "======================================================================"

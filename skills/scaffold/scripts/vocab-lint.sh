#!/usr/bin/env bash
# Fail when scaffold vocabulary leaks into product channels. The scaffold's
# namespace is generated (item ids, phase ids, revision tags), so the leak is
# mechanically detectable; this is the firing mechanism behind the rule that
# code, docs, and commit messages carry no process vocabulary.
#
# Usage: vocab-lint.sh <product-path> [<product-path>...]
#   Scans exactly the named files/directories plus the commit messages of
#   the current branch; exits nonzero on any hit. Name product paths only —
#   pointed at a repo root it would scan the scaffold workspace and fire on
#   the machinery itself.
set -u

if [ "$#" -lt 1 ]; then
    echo "usage: vocab-lint.sh <product-path> [<product-path>...]" >&2
    exit 2
fi

patterns='item-[0-9][0-9][0-9]|phase-[0-9][0-9]|\bR[0-9]-[0-9]+\b|goal-function|autonomy-grant|\bledger\.json\b|\.scaffolding/'

status=0

hits=$(grep -rEn "$patterns" "$@" 2>/dev/null)
if [ -n "$hits" ]; then
    echo "scaffold vocabulary in product files:" >&2
    printf '%s\n' "$hits" >&2
    status=1
fi

log_hits=$(git log --format='%H %s %b' 2>/dev/null | grep -En "$patterns")
if [ -n "$log_hits" ]; then
    echo "scaffold vocabulary in commit messages:" >&2
    printf '%s\n' "$log_hits" >&2
    status=1
fi

# Control line: prove the patterns themselves still match, so a silent regex
# break cannot pass as a clean scan.
if ! printf 'item-001\n' | grep -qE "$patterns"; then
    echo "vocab-lint self-test failed: patterns match nothing" >&2
    status=2
fi

exit "$status"

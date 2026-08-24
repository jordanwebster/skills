#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=${test_dir%/tests}

source "$test_dir/lib.sh"

output_file=$(mktemp "${TMPDIR:-/tmp}/loop-m0.XXXXXX")
trap 'rm -f "$output_file"' EXIT

if timeout 120 "$repo_root/docs/loop/build/check.sh" >"$output_file"; then
    fail "the whole-build check must remain red until all seeded failures pass"
fi

output=$(cat "$output_file")
assert_eq \
    "build incomplete: M3 supervision is not implemented" \
    "$output" \
    "the whole-build check should name the first unfinished M3 gap"

goal_output=$(timeout 120 env PYTHONPATH="$repo_root/framework" \
    python3 "$repo_root/framework/tests/toy_flight_goal.py")
assert_eq \
    "toy flight M2 green" \
    "$goal_output" \
    "the M2 toy flight should run green unattended"

timeout 120 env PYTHONPATH="$repo_root/framework" \
    python3 -m unittest discover -s "$repo_root/framework/tests" -p 'test_*.py'

echo "loop M0-M2 tests passed"

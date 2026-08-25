#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=${test_dir%/tests}

source "$test_dir/lib.sh"

output_file=$(mktemp "${TMPDIR:-/tmp}/loop-m0.XXXXXX")
trap 'rm -f "$output_file"' EXIT

if ! timeout 120 "$repo_root/docs/loop/build/check.sh" >"$output_file"; then
    fail "the whole-build check must be green after the seeded failures pass"
fi

output=$(cat "$output_file")
assert_eq \
    "build complete: toy flight and seeded-failure suite are green" \
    "$output" \
    "the whole-build check should name the completed goal function"

goal_output=$(timeout 120 env PYTHONPATH="$repo_root/framework" \
    python3 "$repo_root/framework/tests/toy_flight_goal.py")
assert_eq \
    "toy flight M5 bless round-trip green" \
    "$goal_output" \
    "the complete M5 toy flight should run green unattended"

timeout 120 env PYTHONPATH="$repo_root/framework" \
    python3 -m unittest discover -s "$repo_root/framework/tests" -p 'test_*.py'

echo "loop M0-M5 framework tests passed"

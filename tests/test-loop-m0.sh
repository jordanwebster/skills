#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=${test_dir%/tests}

source "$test_dir/lib.sh"

output_file=$(mktemp "${TMPDIR:-/tmp}/loop-m0.XXXXXX")
trap 'rm -f "$output_file"' EXIT

if timeout 120 "$repo_root/docs/loop/build/check.sh" >"$output_file"; then
    fail "the whole-build check must remain red at M0"
fi

output=$(cat "$output_file")
assert_eq \
    "build incomplete: M1 toy-flight runner is not implemented" \
    "$output" \
    "the M0 goal function should fail for the planned M1 gap"

timeout 120 env PYTHONPATH="$repo_root/framework" \
    python3 -m unittest discover -s "$repo_root/framework/tests" -p 'test_*.py'

echo "loop M0 tests passed"

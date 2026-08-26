#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=${test_dir%/tests}

source "$test_dir/lib.sh"

[ -x "$repo_root/skills/delegate/scripts/delegate" ] || fail "the delegate launcher must be executable"

help_output=$(timeout 30 "$repo_root/skills/delegate/scripts/delegate" --help)
printf '%s\n' "$help_output" | grep -q 'resolve' || fail "the delegate launcher must expose resolve"
printf '%s\n' "$help_output" | grep -q 'doctor' || fail "the delegate launcher must expose doctor"

timeout 120 env PYTHONPATH="$repo_root/skills/delegate/lib" \
    python3 -m unittest discover -s "$test_dir/delegate" -p 'test_*.py'

echo "delegate CLI tests passed"

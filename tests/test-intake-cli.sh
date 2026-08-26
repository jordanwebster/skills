#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=${test_dir%/tests}

source "$test_dir/lib.sh"

[ -x "$repo_root/skills/intake/scripts/intake" ] || fail "the intake launcher must be executable"

help_output=$(timeout 30 "$repo_root/skills/intake/scripts/intake" --help)
printf '%s\n' "$help_output" | grep -q 'finalize' || fail "the intake launcher must expose finalize"

timeout 120 env PYTHONPATH="$repo_root/skills/intake/lib" \
    python3 -m unittest discover -s "$test_dir/intake" -p 'test_*.py'

echo "intake CLI tests passed"


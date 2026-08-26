#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=${test_dir%/tests}

source "$test_dir/lib.sh"

[ -x "$repo_root/skills/autopilot/scripts/autopilot" ] || fail "the autopilot launcher must be executable"

help_output=$(timeout 30 "$repo_root/skills/autopilot/scripts/autopilot" --help)
printf '%s\n' "$help_output" | grep -q 'status' || fail "the launcher must run the CLI"

timeout 300 env PYTHONPATH="$repo_root/skills/autopilot/lib:$test_dir/autopilot" \
    python3 -m unittest discover -s "$test_dir/autopilot" -p 'test_*.py'

echo "autopilot tests passed"

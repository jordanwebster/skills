#!/usr/bin/env bash
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)
framework_root=$repo_root/framework

if ! unit_output=$(timeout 120 env PYTHONPATH="$framework_root" \
    python3 -m unittest discover -s "$framework_root/tests" -p 'test_*.py' 2>&1); then
    echo "build incomplete: framework unit suite failed"
    exit 1
fi

if ! goal_output=$(timeout 120 env PYTHONPATH="$framework_root" \
    python3 "$framework_root/tests/toy_flight_goal.py" 2>&1); then
    if [ -n "$goal_output" ]; then
        printf '%s\n' "$goal_output" | sed -n '1p'
    else
        echo "build incomplete: toy-flight goal function failed without a reason"
    fi
    exit 1
fi

echo "build incomplete: M5 judge, outbox, and bless are not implemented"
exit 1

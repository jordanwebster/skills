#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
python3 -m unittest discover -s "$test_dir/handoff" -p 'test_*.py'

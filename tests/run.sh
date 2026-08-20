#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

for test_file in "$test_dir"/test-*.sh; do
    timeout 120 "$test_file"
done

echo "all tests passed"

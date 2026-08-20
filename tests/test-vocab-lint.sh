#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH= cd -- "$test_dir/.." && pwd)
lint=$repo_root/skills/scaffold/scripts/vocab-lint.sh
# shellcheck source=tests/lib.sh
. "$test_dir/lib.sh"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
fixture=$scratch/repo
new_fixture_repo "$fixture"

mkdir -p "$fixture/src"
printf 'clean product line\n' >"$fixture/src/app.py"
git -C "$fixture" add src
git -C "$fixture" commit -q -m "clean product commit"

if ! (cd "$fixture" && "$lint" src >/dev/null 2>&1); then
    fail "a clean product tree must pass the lint"
fi

printf '# resolves item-042 of the plan\n' >>"$fixture/src/app.py"
if (cd "$fixture" && "$lint" src >/dev/null 2>&1); then
    fail "scaffold vocabulary in product code must fail the lint"
fi

printf 'another clean product line\n' >"$fixture/src/app.py"
git -C "$fixture" add src
git -C "$fixture" commit -q -m "close item-042 for phase-01"
if (cd "$fixture" && "$lint" src >/dev/null 2>&1); then
    fail "scaffold vocabulary in commit messages must fail the lint"
fi

echo "ok - vocabulary lint"

#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH= cd -- "$test_dir/.." && pwd)
scripts_dir=$repo_root/skills/handoff/scripts
# shellcheck source=tests/lib.sh
. "$test_dir/lib.sh"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
fixture=$scratch/repo
new_fixture_repo "$fixture"

handoff_dir=$fixture/.handoff/demo
mkdir -p "$handoff_dir/proofs"
printf 'working output\n' >"$handoff_dir/proofs/terminal.txt"

in_fixture() {
    (cd "$fixture" && "$@")
}

run_report() {
    set +e
    report_output=$(in_fixture "$scripts_dir/stale.sh" "$handoff_dir")
    report_status=$?
    set -e
}

run_report
assert_eq 1 "$report_status" "a handoff without a freshness record must produce exit one"
assert_eq "missing $handoff_dir/freshness" "$report_output" "the missing record must be reported"

in_fixture "$scripts_dir/stamp.sh" "$handoff_dir" tool=fixture >/dev/null
run_report
assert_eq 0 "$report_status" "a fresh handoff must produce exit zero"
assert_eq "fresh $handoff_dir tool=fixture" "$report_output" "a fresh handoff and its extra inputs must be reported"

printf 'subject change\n' >>"$fixture/app.txt"
git -C "$fixture" add app.txt
git -C "$fixture" commit -q -m "change subject"
run_report
assert_eq 1 "$report_status" "a stale handoff must produce exit one"
assert_eq "stale $handoff_dir tool=fixture" "$report_output" "a subject-changing commit must stale the whole handoff"

in_fixture "$scripts_dir/stamp.sh" "$handoff_dir" tool=fixture >/dev/null
run_report
assert_eq 0 "$report_status" "re-stamping after re-verification must restore freshness"

echo "ok - handoff freshness"

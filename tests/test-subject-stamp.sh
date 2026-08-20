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

in_fixture() {
    (cd "$fixture" && "$@")
}

base_commit=$(git -C "$fixture" rev-parse HEAD)
base_subject=$(in_fixture "$scripts_dir/subject-rev.sh")

# Compatibility: repositories that historically committed a top-level
# handoffs/ directory keep a stable subject across evidence-only commits.
mkdir -p "$fixture/handoffs/legacy"
printf 'legacy evidence\n' >"$fixture/handoffs/legacy/outline.md"
git -C "$fixture" add handoffs
git -C "$fixture" commit -q -m "legacy evidence commit"
legacy_subject=$(in_fixture "$scripts_dir/subject-rev.sh")
assert_eq "$base_subject" "$legacy_subject" "legacy evidence-only commits must preserve the subject revision"
explicit_subject=$(in_fixture "$scripts_dir/subject-rev.sh" "$base_commit")
assert_eq "$base_subject" "$explicit_subject" "explicit commits must be supported"

# Untracked evidence never affects the subject.
mkdir -p "$fixture/.handoff/demo"
printf 'proof outline\n' >"$fixture/.handoff/demo/outline.md"
untracked_subject=$(in_fixture "$scripts_dir/subject-rev.sh")
assert_eq "$base_subject" "$untracked_subject" "untracked evidence must not change the subject revision"

printf 'subject change\n' >>"$fixture/app.txt"
git -C "$fixture" add app.txt
git -C "$fixture" commit -q -m "change subject"
changed_subject=$(in_fixture "$scripts_dir/subject-rev.sh")
assert_ne "$base_subject" "$changed_subject" "subject changes must change the subject revision"

if (cd "$fixture" && "$scripts_dir/subject-rev.sh" does-not-exist >"$scratch/bad-ref.out" 2>"$scratch/bad-ref.err"); then
    fail "subject-rev must reject a bad ref"
fi
grep -q 'not a commit' "$scratch/bad-ref.err" || fail "bad-ref diagnostic must be clear"

if (cd "$scratch" && "$scripts_dir/subject-rev.sh" >"$scratch/outside.out" 2>"$scratch/outside.err"); then
    fail "subject-rev must reject a directory outside a git repository"
fi
grep -q 'not inside a git repository' "$scratch/outside.err" || fail "outside-repository diagnostic must be clear"

handoff_dir=$fixture/.handoff/demo
in_fixture "$scripts_dir/stamp.sh" "$handoff_dir" zeta=last alpha=first format=markdown >/dev/null
expected_record=$(printf 'subject=%s\nalpha=first\nformat=markdown\nzeta=last' "$changed_subject")
actual_record=$(cat "$handoff_dir/freshness")
assert_eq "$expected_record" "$actual_record" "the record must put subject first and sort named inputs"

printf 'old data that must be replaced\n' >"$handoff_dir/freshness"
in_fixture "$scripts_dir/stamp.sh" "$handoff_dir" base=$base_commit >/dev/null
actual_replacement=$(cat "$handoff_dir/freshness")
assert_eq "subject=$changed_subject
base=$base_commit" "$actual_replacement" "stamp must replace an existing record"

if in_fixture "$scripts_dir/stamp.sh" "$handoff_dir" subject=forged >/dev/null 2>"$scratch/reserved.err"; then
    fail "stamp must reject the reserved subject input"
fi
grep -q 'reserved' "$scratch/reserved.err" || fail "reserved-name diagnostic must be clear"

echo "ok - subject revision and the freshness record"

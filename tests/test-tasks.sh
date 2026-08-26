#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=${test_dir%/tests}

source "$test_dir/lib.sh"

tasks=$repo_root/skills/tasks/scripts/tasks
[ -x "$tasks" ] || fail "the tasks launcher must be executable"

scratch=$(mktemp -d "${TMPDIR:-/tmp}/tasks-test.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export TASKS_LOCAL_STORE=$scratch/tasks.json
export TASKS_CONFIG=$scratch/absent.toml
export TASKS_REPO=fixture

first=$(timeout 30 "$tasks" add "Fix the widget" --body "it wobbles")
assert_eq "Filed: T-1        Fix the widget" "$first" "add files a task with a sequential id"

duplicate=$(timeout 30 "$tasks" add "fix the widget")
assert_eq "Already filed: T-1        Fix the widget" "$duplicate" "add is idempotent on title within a repo"

later=$(timeout 30 "$tasks" add "Polish" --later)
printf '%s\n' "$later" | grep -q '\[later\]' || fail "--later must label the task"

open_count=$(timeout 30 "$tasks" list --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
assert_eq "2" "$open_count" "list shows both open tasks"

timeout 30 "$tasks" edit T-1 --add-label bug >/dev/null
shown=$(timeout 30 "$tasks" show T-1)
printf '%s\n' "$shown" | grep -q 'labels: repo:fixture, bug' || fail "edit must add labels and keep the repo label"
printf '%s\n' "$shown" | grep -q 'it wobbles' || fail "show must print the body"

timeout 30 "$tasks" close T-1 --reason "merged as abc123" >/dev/null
closed=$(timeout 30 "$tasks" list --state closed)
printf '%s\n' "$closed" | grep -q 'T-1' || fail "close must move the task out of the open list"
remaining=$(timeout 30 "$tasks" list)
printf '%s\n' "$remaining" | grep -q 'T-1' && fail "a closed task must not be listed as open"

timeout 30 "$tasks" add "Elsewhere" --repo other >/dev/null
here_count=$(timeout 30 "$tasks" list | wc -l | tr -d ' ')
all_count=$(timeout 30 "$tasks" list --all-repos | wc -l | tr -d ' ')
assert_eq "1" "$here_count" "list is scoped to the current repo"
assert_eq "2" "$all_count" "--all-repos crosses repos"

timeout 30 "$tasks" reopen T-1 >/dev/null
printf '%s\n' "$(timeout 30 "$tasks" list)" | grep -q 'T-1' || fail "reopen must return the task to the open list"

backends=$(timeout 30 "$tasks" backends)
printf '%s\n' "$backends" | grep -q 'local  (configured)' || fail "backends must list local as configured"
printf '%s\n' "$backends" | grep -q 'linear' || fail "backends must list the bundled linear backend"

missing=$(TASKS_CONFIG=$scratch/bad.toml sh -c "printf '[backend]\nprovider = \"nowhere\"\n' > $scratch/bad.toml; timeout 30 '$tasks' list" 2>&1 || true)
printf '%s\n' "$missing" | grep -q 'no backend named' || fail "an unknown backend must be reported plainly"

echo "ok - tasks"

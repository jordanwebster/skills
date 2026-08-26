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
assert_eq "Filed: T-1        filed   Fix the widget" "$first" "add files a task at stage filed"

duplicate=$(timeout 30 "$tasks" add "fix the widget")
assert_eq "Already filed: T-1        filed   Fix the widget" "$duplicate" "add is idempotent on title within a repo"

timeout 30 "$tasks" add "Polish" >/dev/null

workable=$(timeout 30 "$tasks" list)
assert_eq "No tasks ready or doing.
Also open: 2 filed  (tasks list --stage filed)
Lifecycle: filed 2  shaped 0  ready 0  doing 0" "$workable" "filed tasks are inert but counted"
filed_count=$(timeout 30 "$tasks" list --stage filed --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
assert_eq "2" "$filed_count" "--stage filed shows the backlog"

shaped=$(timeout 30 "$tasks" shape T-1 --append "Requirements: stop the wobble")
printf '%s\n' "$shaped" | grep -q 'shaped  Fix the widget' || fail "shape must move the task to stage shaped"
printf '%s\n' "$(timeout 30 "$tasks" show T-1)" | grep -q 'Requirements: stop the wobble' || fail "shape --append must keep the old body"

ready=$(timeout 30 "$tasks" ready T-1)
printf '%s\n' "$ready" | grep -q 'ready   Fix the widget' || fail "ready must promote the task"
assert_eq "T-1        ready   Fix the widget
Also open: 1 filed  (tasks list --stage filed)
Lifecycle: filed 1  shaped 0  ready 1  doing 0" "$(timeout 30 "$tasks" list)" "a ready task is workable; the backlog is summarised"
ready_json=$(timeout 30 "$tasks" list --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
assert_eq "1" "$ready_json" "--json carries only the listed tasks"

started=$(timeout 30 "$tasks" start T-1)
printf '%s\n' "$started" | grep -q 'doing   Fix the widget' || fail "start must mark the task doing"
open_count=$(timeout 30 "$tasks" list --stage all --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
assert_eq "2" "$open_count" "--stage all shows every open task"

timeout 30 "$tasks" edit T-1 --add-label bug >/dev/null
shown=$(timeout 30 "$tasks" show T-1)
printf '%s\n' "$shown" | grep -q 'labels: repo:fixture, bug' || fail "edit must add labels and keep the repo label"
printf '%s\n' "$shown" | grep -q 'it wobbles' || fail "show must print the body"
printf '%s\n' "$shown" | grep -q 'stage: doing' || fail "show must print the stage"

timeout 30 "$tasks" close T-1 --reason "merged as abc123" >/dev/null
closed=$(timeout 30 "$tasks" list --state closed)
printf '%s\n' "$closed" | grep -q 'T-1' || fail "close must move the task out of the open list"
remaining=$(timeout 30 "$tasks" list --stage all)
printf '%s\n' "$remaining" | grep -q 'T-1' && fail "a closed task must not be listed as open"

timeout 30 "$tasks" add "Elsewhere" --repo other >/dev/null
timeout 30 "$tasks" ready T-3 >/dev/null
here_count=$(timeout 30 "$tasks" list --stage all --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
all_count=$(timeout 30 "$tasks" list --stage all --all-repos --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
assert_eq "1" "$here_count" "list is scoped to the current repo"
assert_eq "2" "$all_count" "--all-repos crosses repos"

timeout 30 "$tasks" reopen T-1 >/dev/null
printf '%s\n' "$(timeout 30 "$tasks" list --stage filed)" | grep -q 'T-1' || fail "reopen must return the task to the backlog"

backends=$(timeout 30 "$tasks" backends)
printf '%s\n' "$backends" | grep -q 'local  (configured)' || fail "backends must list local as configured"
printf '%s\n' "$backends" | grep -q 'linear' || fail "backends must list the bundled linear backend"

doctor=$(timeout 30 "$tasks" doctor)
printf '%s\n' "$doctor" | grep -q 'Tasks ready: local' || fail "doctor must report the configured backend"
printf '%s\n' "$doctor" | grep -q 'label: repo:fixture' || fail "doctor must report the repository label"
doctor_json=$(timeout 30 "$tasks" doctor --json)
assert_eq "True local repo:fixture" "$(printf '%s' "$doctor_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["ok"], d["backend"]["provider"], d["repository"]["label"])')" "doctor JSON must be stable and composable"

near=$(timeout 30 "$tasks" add "Polishing")
printf '%s\n' "$near" | grep -q 'Filed: T-4' || fail "a near duplicate must still be filed"
printf '%s\n' "$near" | grep -q 'Possible duplicate: T-2 Polish' || fail "add must offer a non-blocking near-duplicate hint"
near_json=$(timeout 30 "$tasks" add "Polished" --json)
assert_eq "False T-2" "$(printf '%s' "$near_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["already_exists"], d["near_duplicates"][0]["id"])')" "add JSON must expose duplicate hints without blocking creation"

missing=$(TASKS_CONFIG=$scratch/bad.toml sh -c "printf '[backend]\nprovider = \"nowhere\"\n' > $scratch/bad.toml; timeout 30 '$tasks' list" 2>&1 || true)
printf '%s\n' "$missing" | grep -q 'no backend named' || fail "an unknown backend must be reported plainly"
printf '%s\n' "$missing" | grep -q 'Recovery:' || fail "a backend failure must provide one recovery action"

missing_json=$(TASKS_CONFIG=$scratch/bad.toml timeout 30 "$tasks" list --json || true)
assert_eq "configuration True" "$(printf '%s' "$missing_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["error"]["class"], bool(d["error"]["recovery"]))')" "JSON failures must classify the error and provide recovery"

printf '{broken\n' >"$scratch/corrupt.json"
corrupt_json=$(TASKS_LOCAL_STORE=$scratch/corrupt.json timeout 30 "$tasks" doctor --json || true)
assert_eq "backend True" "$(printf '%s' "$corrupt_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["error"]["class"], bool(d["error"]["recovery"]))')" "doctor must return stable recovery for a corrupt local store"

echo "ok - tasks"

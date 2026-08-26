---
name: tasks
description: Read and update tracked work through one command with pluggable local or Linear backends. Use when the operator asks about a tracker or backlog, when tracked work is the stated source, or when authorized follow-ups should be filed. Do not invoke for ordinary work merely because a tracker is installed; tracker failure never blocks otherwise authorized product work.
---

# Tasks

Use optional durable task memory without turning it into requirements,
planning, scheduling, or execution. Agents use the `tasks` command instead of
speaking to a tracker directly.

Locate it from the loaded skill:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
tasks=$skill_dir/scripts/tasks
```

## Lifecycle

- `filed`: an inert idea or follow-up.
- `shaped`: its statement and requirements are settled, but it is unscheduled.
- `ready`: the operator has made it available to pick up.
- `doing`: an agent has taken it.

Closing is separate from stage. Promoting to ready, closing, canceling, and
reopening require the operator's word in the current conversation or an
explicit standing grant. Reading, filing authorized follow-ups, and shaping
during requested backlog work do not grant wider product authority.

## Command

```text
tasks list [--stage filed|shaped|ready|doing|all] [--state open|closed|all]
tasks show <id>
tasks add "title" [--body text] [--label label]
tasks shape <id> [--title text] [--body text | --append text]
tasks ready|start|reopen <id>
tasks stage <id> filed|shaped|ready|doing
tasks edit <id> [--title text] [--body text] [--add-label label] [--remove-label label]
tasks close <id> [--reason text] [--cancel]
tasks doctor
tasks backends
```

All verbs accept `--repo` and `--json`. `list` defaults to ready and doing work
for the current repository and reports one compact lifecycle count. `add` is
exactly idempotent on a normalized open title in that repository. Similar
titles are non-blocking hints: the newly requested task is still filed.

Use `tasks doctor` only when explicitly asked to diagnose Tasks or after a
configuration, authentication, or connectivity failure. It reports the config,
backend, reachability, authentication, and repository label without a model
call. Every command failure includes one recovery action. Do not retry a failed
tracker write as if it succeeded, and do not let it stop unrelated authorized
product work.

Configuration defaults to `~/.config/tasks/config.toml`; without it, the local
backend stores tasks under `~/.local/state/tasks/`. A backend executable named
`tasks-backend-<provider>` receives versioned JSON on stdin and returns JSON on
stdout. The bundled local backend is the reference protocol implementation.

## Consumes

- Operator tracker intent, configured backend, repository identity, and task
  references.

## Produces

- Optional task records, lifecycle counts, duplicate hints, and actionable
  diagnostics.

## Does not own

- Acceptance, implementation plans, staffing, execution, or completion.
- Automatic work selection or permission inferred from old tracker state.
- A dependency that can block product work unrelated to the requested tracker
  operation.

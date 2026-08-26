---
name: tasks
description: Find, file, edit, and close tracked work through one small command with pluggable backends (a local file, Linear). Use whenever work involves looking up, filing, or closing tracked tasks - before starting a piece of work, when noticing follow-ups, and after a merge.
---

# Tasks

One command, `tasks`, over whatever tracker the operator uses. Agents
never talk to a tracker directly; they run the command, and a backend
executable does the rest. Task storage stays dumb: statements, granularity,
and which repository owns a task are settled with the operator in
conversation, not by the tool.

## Locate the machinery

Set `skill_file` to the path through which this `SKILL.md` was loaded;
the installed skill directory is a symlink:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
tasks=$skill_dir/scripts/tasks
```

## The verbs

```
tasks list [--all-repos] [--state open|closed|all] [--label L] [--search text]
tasks show <id>
tasks add "title" [--body text] [--label L] [--later]
tasks edit <id> [--title …] [--body …] [--add-label L] [--remove-label L]
tasks close <id> [--reason …] [--cancel]
tasks reopen <id>
tasks backends
```

Add `--json` for machine-readable output. Every task carries a
`repo:<name>` label; the name is the current repository's directory name
unless the config's portfolio maps its path to another name, or `--repo`
says otherwise. `add` is idempotent: an open task with the same title in
the same repository is returned instead of duplicated. `--later` marks a
follow-up nobody is scheduling yet — the label is `later`.

## When to use it

- **Before work starts**: `tasks list` to see what is already filed and
  `tasks show` for the one being picked up; a task that carries confirmed
  requirements is the input downstream work trusts.
- **While working**: file what you notice and will not do now — `tasks add
  "…" --later`. Widening the current work is a question for the operator,
  not a task filed quietly.
- **At the end**: an autopilot flight prints its follow-ups at landing;
  file them with `--later`. Close the task the work delivered after the
  merge is confirmed, with the merge commit in `--reason`.

## Authority

Reads need no permission. Writes — `add`, `edit`, `close`, `reopen` —
happen on the operator's word in the current conversation ("file those",
"close it") or an explicit standing grant in the config. Never infer
permission from an old task, from silence, or from the skill being
installed. When the backend is unreachable, say what you would have filed
and stop; never invent a filing.

## Configuration and backends

`~/.config/tasks/config.toml` (or `$TASKS_CONFIG`) names the backend and
the operator's repository portfolio; `templates/tasks.toml` in the skills
repository is the reference copy. With no config at all, tasks go to a
local JSON file under `~/.local/state/tasks/`.

A backend is one executable named `tasks-backend-<provider>`, bundled
under `backends/` beside this file or anywhere on `PATH`. It receives the
operation as its argument and one JSON request on stdin, and prints one
JSON result — a task, a list of tasks, or `{"error": …}`. The bundled
`local` backend is the reference implementation of the protocol; `linear`
speaks Linear's GraphQL API with a key from the environment. Adding a
tracker means adding one such executable.

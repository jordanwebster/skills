---
name: tasks
description: Find, file, shape, and close tracked work through one small command with pluggable backends (a local file, Linear). Use whenever work involves looking up, filing, gardening, or closing tracked tasks - before starting a piece of work, when noticing follow-ups, when the operator wants to clean up the backlog, and after a merge.
---

# Tasks

One command, `tasks`, over whatever tracker the operator uses. Agents
never talk to a tracker directly; they run the command, and a backend
executable does the rest. Task storage stays dumb: statements,
granularity, and which repository owns a task are settled with the
operator in conversation, not by the tool.

## Locate the machinery

Set `skill_file` to the path through which this `SKILL.md` was loaded;
the installed skill directory is a symlink:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
tasks=$skill_dir/scripts/tasks
```

## The lifecycle

Every open task is at one stage:

| Stage | Meaning | Who moves it there |
| --- | --- | --- |
| **filed** | An idea, a follow-up, a tossed-off sentence. Inert: no agent picks it up. | Anyone, any time: `tasks add` |
| **shaped** | Statement settled, repository assigned, requirements attached. Still not scheduled. | A gardening walk, or intake: `tasks shape` |
| **ready** | An agent could pick it up now. | The operator's word: `tasks ready` |
| **doing** | An agent has it. | The agent: `tasks start` |

Closing is orthogonal: `tasks close` (done) or `tasks close --cancel`
from any stage; `tasks reopen` returns a task to filed.

## The verbs

```
tasks list [--stage filed|shaped|ready|doing|all] [--all-repos] [--state open|closed|all] [--label L] [--search text]
tasks show <id>
tasks add "title" [--body text] [--label L]              # stage filed
tasks shape <id> [--title …] [--body … | --append …]     # stage shaped
tasks ready <id>                                         # stage ready — operator's word
tasks start <id>                                         # stage doing
tasks stage <id> <stage>                                 # set a stage directly
tasks edit <id> [--title …] [--body …] [--add-label L] [--remove-label L]
tasks close <id> [--reason …] [--cancel]
tasks reopen <id>
tasks backends
```

`tasks list` alone shows what can be worked — ready and doing. Add
`--json` for machine-readable output. Every task carries a `repo:<name>`
label; the name is the current repository's directory name unless the
config's portfolio maps its path to another name, or `--repo` says
otherwise. `add` is idempotent: an open task with the same title in the
same repository is returned instead of duplicated.

## When to use it

- **Before work starts**: `tasks list` for what is ready, `tasks show`
  for the one being picked up, `tasks start` when taking it. A shaped
  task's body is the requirements downstream work trusts; a task picked
  up unshaped goes through intake first.
- **While working**: file what you notice and will not do now with
  `tasks add`. It lands filed and inert. Widening the current work is a
  question for the operator, not a task filed quietly.
- **At the end**: an autopilot flight prints its follow-ups at landing;
  file them. Close the task the work delivered after the merge is
  confirmed, with the merge commit in `--reason`.

## Gardening

When the operator points at the backlog, walk it with them: `tasks list
--stage filed` (and shaped), one task at a time, no command framing in
the conversation. For each: settle the statement, the repository, and
whether it duplicates or belongs under another; shape what is worth
shaping — offering to run intake on anything substantial enough to need
confirmed requirements — and record the result with `tasks shape`; cancel
what is stale; and promote with `tasks ready` only what the operator
endorses in that conversation. Refining and promoting are separate
events: a simple task can go straight to ready unshaped, and a shaped
task can wait.

## Authority

Reads need no permission. Filing (`add`) and shaping are ordinary work an
agent may do while it works or gardens. Promoting to ready, closing, and
cancelling happen on the operator's word in the current conversation —
"file those", "that's ready", "close it" — or an explicit standing grant
in the config. Never infer permission from an old task, from silence, or
from the skill being installed. When the backend is unreachable, say what
you would have done and stop; never invent a filing.

## Configuration and backends

`~/.config/tasks/config.toml` (or `$TASKS_CONFIG`) names the backend and
the operator's repository portfolio; `templates/tasks.toml` in the skills
repository is the reference copy. With no config at all, tasks go to a
local JSON file under `~/.local/state/tasks/`.

A backend is one executable named `tasks-backend-<provider>`, bundled
under `backends/` beside this file or anywhere on `PATH`. It receives the
operation as its argument and one JSON request on stdin, and prints one
JSON result — a task, a list of tasks, or `{"error": …}`. The bundled
`local` backend is the reference implementation of the protocol. `linear`
speaks Linear's GraphQL API with a key from the environment or from a
command the config names (a keychain lookup, say), and maps stages onto
the team's workflow: filed and shaped are the backlog state (shaped adds a
`shaped` label), ready is Todo, doing is In Progress. Adding a tracker
means adding one such executable.

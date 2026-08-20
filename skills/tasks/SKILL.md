---
name: tasks
description: Manage tracked work through a durable six-verb task seam. Use whenever work involves finding, filing, shaping, gardening, linking, promoting, closing, or otherwise reasoning about tracked tasks and their dependencies.
---

# Tasks

Keep task storage dumb. Shape statements, granularity, repository ownership,
and relationships with the operator in conversation. Treat this contract as a
behavioral definition; do not claim that an adapter or control enforces it.

## Use only the seam

Express every task-backend interaction as exactly one of these verbs. Never
call a backend outside their bindings.

| Verb | Contract |
| --- | --- |
| `get(ref \| selector)` | Return the verbatim statement plus backend ID, lane, repo, state, labels, provenance, and links. Allow selectors to return sets. |
| `neighbors(ref)` | Return dependencies in both directions plus related work, duplicates, umbrella, and cross-repo siblings. |
| `file(statement, context, repo, lane, operation_key)` | Create one task at the depth actually shaped and return its stable identity. |
| `link(left, relation, right, operation_key)` | Add a dependency, related, duplicate, sibling, or umbrella edge and read it back. Treat edges as statements about the work. |
| `close(ref, reason, idempotency_input)` | Move a task to the appropriate completed or canceled state and read it back. |
| `promote(ref, endorsement, operation_key)` | Move a braindump to ready after the operator's live endorsement and read the lane back. |

Read backend selection and repository identity from the consumer's
`.tasks.toml` — this skill's own configuration file, kept untracked at the
repository root. Require every task to carry exactly one `repo:<name>` label
matching its assigned repo.

## Bind Linear

Use only `get_issue`, `list_issues`, `create_issue`, `update_issue`,
`list_issue_labels`, and `list_issue_statuses`. Follow the available tool
schemas for argument spelling.

| Verb | Linear calls |
| --- | --- |
| `get` | Use `get_issue` for an ID. Use `list_issues` for a selector, then `get_issue` when full context is absent. |
| `neighbors` | Use `get_issue` to read blocking, blocked-by, related, duplicate, and parent/child context. Use `list_issues` only to resolve referenced issues. |
| `file` | Use `list_issue_labels` and, when state selection is needed, `list_issue_statuses`; then use `create_issue`. Confirm the created identity with `get_issue`. |
| `link` | Use `update_issue` with the schema's blocking, blocked-by, related, or duplicate field; then use `get_issue` to confirm both ends. Represent sibling and umbrella relationships as related links, not sub-issues. |
| `close` | Use `list_issue_statuses`, `update_issue` with the team's matching completed or canceled state, then `get_issue`. |
| `promote` | Use `list_issue_labels` and `list_issue_statuses`, then `update_issue` to remove `braindump`, preserve every other label, and select the team's ordinary unstarted state; confirm with `get_issue`. |

Mark braindumps with the single `braindump` label and leave them in ordinary
Backlog or Triage states. Represent ready work with ordinary workflow states,
normally Todo, and no `braindump` label. Exclude labeled braindumps and work
with unsatisfied dependencies when selecting ready tasks. Do not invent a
project, state, or custom field.

Before filing or promoting, verify that the required `braindump` and exactly
one `repo:<name>` label already exist. If the allowed surface cannot express
or read back an operation, including because a required label is missing,
treat that operation as unavailable and use the degradation path. Never
smuggle an effect through comments, descriptions, or another backend call.

## Keep lanes provenance-based

File every agent-solo idea and operator braindump as a **braindump**. Keep it
inert: it cannot trigger execution or demand triage.

Use **ready** only after the operator endorses the statement, granularity,
repo assignment, and proposed edges live in conversation. Treat an instruction
such as “file those” after shaping as endorsement; never infer endorsement
from an old task, silence, or skill installation.

Match filing depth to shaping depth. File a tossed-off sentence as one
umbrella braindump. File a graph only when that graph was actually shaped;
never inflate a one-liner into a speculative tree.

Split a cross-repo goal into per-repo sibling tasks joined by dependency and
related edges. Assign the umbrella to one coordinating repo and close it only
after the last child merge is confirmed. Keep decomposition below delegation
granularity inside the repo-local handoff.

## Garden conversationally

Enter gardening mode when the operator points at the accumulated backlog; use
no command framing. Walk braindumps together and settle their statements,
granularity, repo assignments, dependencies, duplicates, and umbrella or
sibling relationships. Promote endorsed work to ready and close stale work in
the appropriate canceled state.

Refining and promoting are separate events. When a walked task is substantial
enough that building it would need confirmed requirements, probe the skill
catalog for a skill named `intake`; if present, offer the operator the choice
to refine the task now or defer refinement until someone picks it up. A task
may be promoted unrefined, and a simple task needs no refinement at all.
Requirements confirmed during gardening attach to the task so downstream work
starts already aligned.

Treat the first gardening session as the operator's Linear cleanup. Keep that
as a standing note until the operator confirms the cleanup is complete. Shape
a fresh idea in any conversation without entering gardening mode.

## Make writes durable

Give every mutating operation a stable operation key. Before the external
effect, create `receipts/<operation-key>` in the caller's evidence directory
with the verb, canonical inputs, backend, and `pending` status. For `file`,
also include the operation key in backend-visible context so a create can be
found after a crash.

After the write, read the effect back and replace `pending` with the backend
identity and observed result. On resume, reconcile the receipt with `get` or
`neighbors` before writing: complete a receipt for an existing effect, retry
an absent effect, and surface an ambiguous effect without guessing.

Perform external effects last and derive them from confirmed Git state. Close
execution work only after confirming its merge; use the merge commit as the
idempotency input, read before writing, and treat the backend's observed
terminal state as the receipt. Make closure terminal and idempotent. Use an
ordinary operation key for operator-endorsed gardening closures.

## Degrade without blocking review

When no backend is configured, it is unreachable, or an operation is
unavailable, append the intended statement, context, repo, lane, links, and
mutation to the caller's `filed.md` outbox. Allocate new filings a stable
`local-<yyyymmdd>-<slug>` ID, with a lowercase `[a-z0-9-]` slug. Record
unavailable mutations as explicit intent, never invented success.

During a later gardening session, reconcile outboxes and local IDs with
backend identities before applying pending mutations. Treat a seam failure as
a seam result: never block, weaken, or otherwise change handoff review because
task storage failed.

## Respect authority

Allow `get` and `neighbors` without authorization. Perform no external write
through `file`, `link`, `close`, or `promote` without the operator's word in
the current conversation or standing authority in `.tasks.toml`.

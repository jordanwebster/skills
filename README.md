# Agent skills

The operator's composable agent-skills collection. A conversational agent
invokes only the capability needed for the risk present; significant
unattended work can cross durable acceptance, planning, execution, and proof
boundaries without making the operator manage the machinery.

- **intake** — compact durable alignment after the operator commits to work
  whose outcomes, boundaries, or demonstrations still need several decisions.
  Exploration and one or two local questions stay in conversation.
- **autopilot** — an unattended loop of fresh agents for work too large
  for one sitting: a flight plan the operator approves in a browser, a
  deterministic preflight that checks every role and tool locally, a task list agents
  pull from and add to, one review per chunk, and a final acceptance with
  captured proof against the requirements. Roles resolve to models through
  the delegate roster.
- **handoff** — proportionate proof where a user sees the result. Easily judged
  behavior gets compact proof without an automatic review; risky, long,
  architectural, inbound, or difficult work gets one decision page and one
  independent review. Work whose diff and focused checks suffice declines it.
- **tasks** — one `tasks` command over pluggable backends (a local file,
  Linear): find, file, edit, and close tracked work; writes on the
  operator's word.
- **delegate** — deterministic staffing policy: role contracts, an
  operator-owned roster binding roles to models and effort, vendor command
  construction, and local diagnosis without provider calls.

The bar every operator-facing surface meets is stated once in
[`docs/OPERATOR-SURFACE.md`](docs/OPERATOR-SURFACE.md) and restated by each
skill in its own words.

Install every skill into Claude and Codex with `./install.sh` — it also links
the `intake`, `delegate`, `autopilot`, `handoff`, and `tasks` commands into
`~/.local/bin`; add
`--agent-config` to symlink the global agent configuration.

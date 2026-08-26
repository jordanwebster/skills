# Agent skills

The operator's agent-skills collection: one lifecycle for significant work,
crossed by exactly two operator conversations, with everything between them
invisible.

- **intake** — alignment before work: turn a vague ask into
  operator-confirmed requirements, every assumption marked row by row.
- **autopilot** — an unattended loop of fresh agents for work too large
  for one sitting: a flight plan the operator approves in a browser, a
  task list agents pull from and add to, one review per chunk, and a final
  acceptance against the requirements. Roles resolve to models through
  the delegate roster.
- **handoff** — high-bandwidth review replacing code review: proofs, an
  independent fresh-context reviewer, and a one-page front page for the
  merge decision. Small self-contained fixes decline it and ship with a
  passing test and a clear commit message. Authoritative design:
  [`docs/SPEC.md`](docs/SPEC.md).
- **tasks** — the backend-independent task seam: find, file, relate,
  promote, and close tracked work; storage stays dumb and external writes
  stay operator-authorized.
- **delegate** — staffing policy: role contracts, an operator-owned roster
  binding roles to models, a staffing log, and escalation.

The bar every operator-facing surface meets is stated once in
[`docs/OPERATOR-SURFACE.md`](docs/OPERATOR-SURFACE.md) and restated by each
skill in its own words.

Install every skill into Claude and Codex with `./install.sh`; add
`--agent-config` to symlink the global agent configuration.

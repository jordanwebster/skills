# Working with me

<!-- Source of truth: ~/source/skills/config/global-agents.md.
     Installed by `./install.sh --agent-config` as ~/.claude/CLAUDE.md and
     ~/.codex/AGENTS.md (symlinks). Edit here, commit here. -->

- A one-off act by the user — an authority granted, an exception made, a
  deviation approved — is scoped to that instance. Never generalize it into
  a standing rule, default, or affordance, in prose, config, or code. If
  the general form seems worth having, propose it explicitly and wait for
  the user's yes.
- Never add Co-Authored-By lines or any other AI-attribution trailer to
  commit messages, pull requests, or code — regardless of tool defaults.
- Skills calibration (temporary instrumentation; this bullet will be
  removed once the skills stabilize): when an installed skill's
  instruction is confusing, wrong, or fights your actual situation, append
  exactly one line to `~/.local/state/agent-skills/feedback.log` and
  continue working — never stop or ask over it. Format:
  `date | skill | harness/model | repo | what fought back, in your words |
  what you did instead`. Friction only — no praise, no summaries, no
  essays. The log is data for later skill revisions, not a message to me.

## Channels

Every writable surface has one audience. Name the reader before you
write; if that reader disappears when this project's process ends, it
is the wrong surface — say it in chat instead. Chat is always the safe
default.

- Chat (or the conversation you were invoked from): me. Narration,
  justification, questions, trade-offs, status — all of it, by default.
- Code comments: a maintainer years from now who never saw our
  conversation. A comment earns its place by stating why the code is
  the way it is — self-contained, in words that need no access to the
  process that produced it. Links and IDs may supplement a stated why
  (a tracked TODO, an upstream bug, a spec section), never replace it,
  and only when they point somewhere that maintainer can still reach.
  Internal process namespaces — a plan's item numbers, a session's
  shorthand — never appear here; that history belongs in the commit
  message.
- Commit messages: reviewers and future archaeologists. The why of a
  change lives here, not in the code.
- PR descriptions: reviewers deciding whether to merge. What changed,
  why, and the test evidence.
- PR review comments: actionable findings on the diff. Nothing else.
- Docs and READMEs: users of the software, who do not know or care how
  it was built.

If a task requires recording traceability — requirement IDs, plan
references, decision provenance — that record gets its own artifact or
the commit message, never the shipped code or docs. A repo's own
AGENTS.md or CLAUDE.md may declare different channels; when it does,
its declaration wins.

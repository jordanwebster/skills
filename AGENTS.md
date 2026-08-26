# Operating Rules

This is the operator's generic agent-skills repo. Its founding resident is
Handoff, whose authoritative spec is `docs/SPEC.md`; future skills join as
sibling directories under `skills/`. The spec's ratified ledger is settled:
never re-litigate a recorded decision, and flag any implementation choice that
would contradict one instead of making it.

- Wrap every test invocation in `timeout`. A firing timeout is a hang to
  diagnose, not a slow suite.
- Never add Co-Authored-By trailers.
- Shell scripts: `#!/usr/bin/env bash`, compatible with bash 3.2 (macOS
  default), no dependencies beyond git and POSIX tools. The autopilot CLI
  is Python 3.11+ standard library only. Tests run via
  `timeout 300 tests/run.sh`.
- Skills follow the open agent-skills standard (`SKILL.md` plus frontmatter
  and bundled scripts or prompts) so one source serves Claude Code and Codex;
  never write harness-specific variants.
- This repo is its own first consumer: once the machinery exists, work here
  goes through it. Until then, make granular commits with clear messages and
  never squash.

## Layout

- `skills/handoff/` — the founding skill and its bundled scripts/prompts.
- `skills/tasks/` — the backend-independent task seam.
- `skills/intake/` — requirements alignment before work starts.
- `skills/autopilot/` — the unattended flight loop: skill, prompts, plan
  template, and the `autopilot` CLI under `lib/`.
- `skills/delegate/` — staffing policy: roles, roster, staffing log.
- `templates/` — the consumer instruction and configuration footprint.
- `config/` — the operator's global agent configuration (symlinked by
  `install.sh --agent-config`).
- `docs/SPEC.md` — Handoff's authoritative design.
- `docs/OPERATOR-SURFACE.md` — the canonical operator-surface bar and
  decision-row grammar each skill restates.
- `docs/INSTALL.md` — collection and consumer installation instructions.
- `tests/` — fixture-repository shell tests; `tests/autopilot/` holds the
  CLI's Python tests, run through `tests/test-autopilot.sh`.
- `install.sh` — installs every skill into both supported harnesses.

Handoff evidence lives untracked under `.handoff/`; it never enters this
repository's history.

## Handoff

Large or consequential work ends with a handoff; use the `handoff` skill
from the start. Small self-contained fixes end with a passing test and a
clear commit message — no handoff.

Machinery: `.` (authoritative rules in `docs/SPEC.md`).

Repo config: `.handoff.toml`, local-only and untracked. Tasks configuration
is operator-global at `~/.config/tasks/config.toml`. Reference copies live
under `templates/`; operator facts never enter shared history.

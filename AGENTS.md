# Operating Rules

This is the operator's agent-skills repo: one lifecycle for significant
work — intake, autopilot, handoff — with tasks and delegate beside them.
Each skill's `SKILL.md` is its authoritative design; there is no separate
spec. Design decisions are recorded in commit messages.

- Wrap every test invocation in `timeout`. A firing timeout is a hang to
  diagnose, not a slow suite.
- Never add Co-Authored-By trailers.
- Shell scripts: `#!/usr/bin/env bash`, compatible with bash 3.2 (macOS
  default), no dependencies beyond git and POSIX tools. Tests run via
  `timeout 300 tests/run.sh`.
- Skills follow the open agent-skills standard (`SKILL.md` plus frontmatter
  and bundled scripts or prompts) so one source serves Claude Code and Codex;
  never write harness-specific variants. Bundled CLIs are Python 3.11+
  standard library only.
- This repo is its own first consumer: once the machinery exists, work here
  goes through it. Until then, make granular commits with clear messages and
  never squash.

## Layout

- `skills/handoff/` — the merge-decision page: the proof plan, the
  reviewer and front-page prompts, and the page command (the renderer is
  autopilot's).
- `skills/tasks/` — the `tasks` CLI under `lib/` and its pluggable backends
  under `backends/`.
- `skills/intake/` — requirements alignment before work starts.
- `skills/autopilot/` — the unattended flight loop: skill, prompts, plan
  template, and the `autopilot` CLI under `lib/`.
- `skills/delegate/` — staffing policy: roles and the operator's roster.
- `templates/` — the consumer instruction and configuration footprint.
- `config/` — the operator's global agent configuration (symlinked by
  `install.sh --agent-config`).
- `docs/OPERATOR-SURFACE.md` — the canonical operator-surface bar and
  decision-row grammar each skill restates.
- `docs/INSTALL.md` — collection and consumer installation instructions.
- `tests/` — fixture-repository shell tests; `tests/autopilot/` holds the
  CLI's Python tests, run through `tests/test-autopilot.sh`.
- `install.sh` — installs every skill into both supported harnesses and
  links each skill's command into `~/.local/bin`.

Handoff evidence lives untracked under `.handoff/` and flight state under
`.autopilot/`; neither enters this repository's history.

## Handoff

Work whose promise a diff cannot show ends with proof of it working;
work that cannot be judged in one sitting ends with a handoff page. Use
the `handoff` skill from the start — the proof plan comes before the code.
Small self-contained fixes whose diff shows everything end with a passing
test and a clear commit message.

### Capturing proof here

The commands are the product: a transcript of the command and its output
(`script -q <file> <command>`, or the test's own output) is the capture.
Rendered pages are proof when a page is the promise: render with
`skills/autopilot/scripts/autopilot page <file.md> --no-open` and
screenshot the HTML in a browser.

Tasks configuration is operator-global at `~/.config/tasks/config.toml`;
the reference copy lives under `templates/`. Operator facts never enter
shared history.

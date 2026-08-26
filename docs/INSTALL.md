# Install the skills collection

Clone this repository to a stable path and run the installer from that
checkout:

```bash
git clone <skills-repository-url> /absolute/path/to/skills
cd /absolute/path/to/skills
./install.sh
```

With no skill names, the installer symlinks every directory under `skills/`
into both `~/.claude/skills/` and `~/.agents/skills/`. Name one or more skills
to install only that subset:

```bash
./install.sh handoff
./install.sh handoff tasks
```

Each skill remains self-contained in this checkout, which is the single source
used by both harnesses. Override the destinations with
`HANDOFF_CLAUDE_SKILLS_DIR` and `HANDOFF_AGENTS_SKILLS_DIR` when needed.

`./install.sh --uninstall` removes only skill links that resolve to this
checkout. Add skill names to uninstall only a subset. Foreign files and
foreign links remain unchanged.

## Configure each consumer repository

Copy the trigger sections you want from `templates/AGENTS-handoff.md` and
`templates/AGENTS-autopilot.md` into the repository's `AGENTS.md`. Nothing
else is per-repository.

Tasks needs no per-repo setup: copy `templates/tasks.toml` once to
`~/.config/tasks/config.toml` and pick a backend. With no config, tasks go
to a local JSON file. The `linear` backend needs a Linear API key in the
environment (`LINEAR_API_KEY` by default) and, when the key sees several
teams, a team key in the config. The delegate roster lives at
`~/.config/delegate/roster.toml`; see `skills/delegate/templates/roster.toml`.

While there is one user, installations intentionally follow the latest global
checkout and version skew is accepted. Revisit release tags when a colleague
adopts the repository.

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

Installing `tasks` also configures Linear's hosted MCP server in each
available CLI's user scope. Use `--skip-mcp` to omit that setup. The
`codex mcp add` step starts an interactive browser OAuth flow, so run it from
a terminal. Interrupting that flow may roll the registration back; rerun the
installer to try again. An absent CLI or failed MCP setup is reported without
blocking skill-link installation.

`./install.sh --uninstall` removes only skill links that resolve to this
checkout. Add skill names to uninstall only a subset. Foreign files, foreign
links, and MCP registrations remain unchanged.

## Configure each consumer repository

A consumer repository has only two pieces of configuration:

1. Copy the trigger sections you want from `templates/AGENTS-handoff.md` and
   `templates/AGENTS-scaffold.md` into `AGENTS.md`, replacing the machinery
   placeholder with the absolute path to this checkout.
2. Copy `templates/handoff.toml` to `.handoff.toml` and `templates/tasks.toml`
   to `.tasks.toml` at the repository root, set the values, and keep both
   untracked (gitignore them) — backend choice, sibling repos, and standing
   authority are operator facts that never belong in shared history.

Do not create `docs/decisions/` during installation. Handoff creates that
directory only when the operator makes the first ratified decision that needs
a permanent record.

While there is one user, installations intentionally follow the latest global
checkout and version skew is accepted. Revisit release tags when a colleague
adopts the repository.

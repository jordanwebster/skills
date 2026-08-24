# Decisions taken during the unattended build

One line per decision, with rationale. For the operator's later review — recorded,
never pre-approved.

- 2026-08-24 — Keep `scaffold` as the CLI and Python package name because the build plan proposes it and retaining the existing operator vocabulary is the reversible default.
- 2026-08-24 — Require Python 3.11 or newer because it is the build plan's proposed floor and permits a modern stdlib-only implementation.
- 2026-08-24 — Put framework code in the top-level `framework/` directory because the brief forbids edits under `skills/` and a sibling directory keeps code separate from skill instructions.
- 2026-08-24 — Make journal rows self-contained with a hashed `state_after` snapshot because append-before-materialize then gives deterministic crash recovery without a second reconstruction format.

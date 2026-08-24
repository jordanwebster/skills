# Decisions taken during the unattended build

One line per decision, with rationale. For the operator's later review — recorded,
never pre-approved.

- 2026-08-24 — Keep `scaffold` as the CLI and Python package name because the build plan proposes it and retaining the existing operator vocabulary is the reversible default.
- 2026-08-24 — Require Python 3.11 or newer because it is the build plan's proposed floor and permits a modern stdlib-only implementation.
- 2026-08-24 — Put framework code in the top-level `framework/` directory because the brief forbids edits under `skills/` and a sibling directory keeps code separate from skill instructions.
- 2026-08-24 — Make journal rows self-contained with a hashed `state_after` snapshot because append-before-materialize then gives deterministic crash recovery without a second reconstruction format.
- 2026-08-24 — Identify the plan's one canonical machine block as `<script type="application/json" id="scaffold-plan">` because it is inert HTML, exactly selectable with the standard library, and leaves all surrounding prose non-authoritative.
- 2026-08-24 — Preserve plan order as the deterministic tie-breaker within the ready frontier because it makes dispatch reproducible without inventing a second priority field.
- 2026-08-24 — Limit M1 verification to proving that a typed claim names the product repository's clean immutable `HEAD` because artifact-based result judgment belongs to M2 and must not be smuggled in as a trusted exit-code check.
- 2026-08-24 — Add `.scaffolding/` to the product repository's local Git exclude during `init` because flight state must not enter worker product commits and the exclusion must remain machine-local.

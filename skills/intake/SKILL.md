---
name: intake
description: Align and confirm a durable acceptance contract for consequential work that must cross contexts. Use after the operator commits to work when several requirements, boundaries, or success demonstrations remain unsettled. Skip for exploration, one or two locally resolvable questions, and already-confirmed requirements.
---

# Intake

Turn what the conversation already established into a compact acceptance
contract a fresh agent can trust. Do not restart discovery from a blank slate.

Use durable Intake only when decisions must be reconciled or handed to another
context. For a small change, ask the necessary question in conversation and
continue without an artifact.

## Alignment

Probe checkable facts read-only before asking. Present only consequential
ambiguities, largest blast radius first, with a recommended default. Surface a
contradiction between the operator and the substrate; never resolve it silently.

Describe acceptance in the operator's language:

- observable expectations and exclusions;
- a small proposed set of demonstrations at the boundary the operator judges;
- material limitations or accepted gaps;
- consequential decisions and exceptional operator acts.

The operator may accept, reject, strengthen, replace, or add demonstrations.
Challenge evidence that cannot support its claim, while allowing an explicitly
accepted weaker demonstration to remain as a visible limitation. Do not ask the
operator to choose capture tools, fixtures, commands, or engineering checks;
planning owns those mechanics.

Ask separately only for costly or weak demonstrations, exceptional authority,
or an agent-proposed expansion. Otherwise present one compact recap for a final
all-ok. Reopen only the affected delta when later facts contradict the contract.

## Durable boundary

Create the contract from [templates/requirements.md](templates/requirements.md).
After the operator explicitly confirms the complete recap, replace its pending
confirmation marker and run:

```text
intake finalize <contract> [--json]
intake inspect <contract> [--receipt PATH] [--json]
```

The command validates structure, coverage, resolved decisions, expansions, and
unfinished placeholders, then atomically writes
`<contract>.acceptance.json`. It cannot judge semantic consistency or confer
authority; invoking it asserts that the operator already gave the final all-ok.
`inspect` validates the current receipt and returns normalized expectations,
demonstrations, coverage, limitations, and accepted gaps. It is the public
machine boundary for a planner or orchestrator that must prove an accepted
demonstration did not disappear; callers do not parse Intake's Markdown.

Return the confirmed contract to the conversational concierge. For one-sitting
work, it normally resolves the configured implementer through Delegate unless
the current session is explicitly known to satisfy that binding; use a
specialist when the work materially requires one. Work that must cross several
implementation contexts instead proceeds to fresh Autopilot planning. Intake
records acceptance but does not make either staffing decision.

## Consumes

- The settled conversation and relevant read-only substrate observations.
- Only the remaining consequential ambiguities.

## Produces

- One confirmed acceptance contract that stands alone in a fresh context.
- One narrow receipt containing its digest and confirmation time.

## Does not own

- Architecture, decomposition, staffing, transports, retries, or run bounds.
- Capture tools, replay recipes, fixtures, tests, or engineering verification.
- Implementation or execution planning.

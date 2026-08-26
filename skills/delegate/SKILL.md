---
name: delegate
description: Resolve or diagnose agent staffing by mapping a requested role and effort through the operator-owned roster to a mind and dispatch specification. Use when an agent or driver will dispatch work, or when a binding cannot launch. Do not use merely because ordinary work is being discussed or performed locally.
---

# Delegate

Delegate is deterministic staffing infrastructure. The caller chooses the work
and role; Delegate resolves the operator's policy without making a provider call.

## Resolve staffing

Bindings live in `$DELEGATE_ROSTER`, or
`~/.config/delegate/roster.toml` when it is unset. Start from
[templates/roster.toml](templates/roster.toml). The roster is operator-owned;
agents may propose a change but never silently substitute or rewrite a binding.

```text
delegate resolve <role> [--effort E] [--json]
delegate doctor [--role <role>] [--effort E] [--json]
```

`resolve --json` is the composition boundary. It returns the semantic mind,
constraints, a preferred native transport description, and a fully constructed
fallback CLI argv. Treat `command` as an argv array, never shell text. Unknown
roles and `unavailable = "reason"` are hard configuration failures.

`doctor` parses and resolves the roster, constructs commands, and checks local
executables. It never launches an agent or spends provider capacity. The first
real dispatch is the connectivity and authentication test.

The caller selects its richest transport for the resolved mind: a compatible
native subagent when available, otherwise the returned fallback command. It
records the actual transport and any requested property that transport could
not honor. The caller owns the prompt, cwd, process lifetime, redaction, and
outcome classification.

Read [references/roles.md](references/roles.md) when choosing or interpreting a
role. A worker never selects its own role or effort.

## Consumes

- A caller-selected role and optional effort.
- The operator-owned roster.

## Produces

- A validated mind: family, model, effort, and constraints.
- Preferred and fallback transport descriptions, including fallback argv.
- One actionable configuration failure when resolution is impossible.

## Does not own

- Work selection, role assignment, prompt construction, or agent execution.
- Retry policy, escalation judgment, or mid-run rebinding.
- Provider connectivity checks or performance history.

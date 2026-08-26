# Delegate roles

Use the narrowest role matching the caller's assigned work. Role selection is a
planning or dispatch decision; this reference does not authorize a dispatch.

| Role | Contract | Writes product? |
| --- | --- | --- |
| `planner` | Fresh context reads confirmed acceptance and the substrate, then writes or revises the execution plan. | No |
| `implementer` | Implements a bounded piece of work and its engineering checks. | Yes |
| `ui-developer` | Implements user-interface work when specialist staffing is material. | Yes |
| `prober` | Performs read-only reconnaissance and records observations. | No, except requested fixtures |
| `qa-tester` | Exercises user-facing behavior naively and reports defects without working around them. | No |
| `reviewer` | Reviews one completed increment against a fixed must-fix bar and is not its author. | No |
| `closer` | Judges the finished result once against confirmed acceptance and its evidence. | No |

Cross-family review uses a separately named roster role such as
`reviewer-cross-family`. A repeated need for escalation is a proposal to change
the operator's roster, never permission for a silent permanent rebind.

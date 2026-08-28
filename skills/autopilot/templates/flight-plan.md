# THE RESULT IN A SHORT LINE, UNDER 70 CHARACTERS

## Goal

ONE PARAGRAPH IN THE OPERATOR'S WORDS, UNDER 60 WORDS: what the flight
delivers and what a user can do afterwards that they cannot now.

**Done means:** THE OBSERVABLE END STATE IN UNDER 40 WORDS — what passes, what
exists, and what the operator can try.

## Route

One `### Milestone N` card per chunk, in order. The title comes from the
machine block. Keep each field to about 220 characters, and refer to another
milestone by its number, written as a capital M and the number.

### Milestone 1 — FIRST CAUSAL STAGE

- **Produces:** WHAT EXISTS AFTER THIS STAGE — components, fixtures, findings,
  or the next stage's task split.
- **Unlocks:** WHAT THE NEXT STAGE CAN NOW DO; for the last stage, what lands.
- **Validated by:** THE TEST LEVEL — unit, boundary replay, whole-flight, live
  capture, or person — and whether it is fast, offline, and deterministic.
- **Branch:** DELETE THIS LINE UNLESS RESEARCH CREATES A REAL FORK. WHAT IS
  BEING FOUND OUT?
  - If OUTCOME A → WHAT HAPPENS NEXT (default)
  - If OUTCOME B → WHAT HAPPENS NEXT
- **Enables:** DELETE THIS LINE UNLESS THIS STAGE BUILDS TEST CAPABILITY LATER
  STAGES DEPEND ON. M2 — how those stages become testable: fast, offline,
  deterministic, or isolated.

### Milestone 2 — SECOND CAUSAL STAGE

- **Produces:** WHAT EXISTS AFTER THIS STAGE.
- **Unlocks:** WHAT LANDS.
- **Validated by:** THE TEST LEVEL AND ITS PROPERTIES.

The page derives each milestone's gate, its exact command, and its task count
from the machine block. Do not write them here.

## Shape

### Components

- **COMPONENT** — what it owns, where it lives (`path/`), and what it depends on.

### Interfaces and APIs

- `signature or endpoint` — what it promises, its inputs and outputs, and its
  error behaviour.

### Data shapes

- **SHAPE** — fields, where it is produced, and where it is consumed.

## Human judgment

ONE SHORT PARAGRAPH UNDER 80 WORDS: what cannot be settled by an automated
check and where the operator will see it on the completion page.

## What you will be asked

| Act | When | Default | Exposure |
| --- | --- | --- | --- |
| Approve this route | Now | Nothing starts | 10 minutes |
| ANY OTHER ACT, OR DELETE THIS ROW | TRIGGER | WHAT HAPPENS WITHOUT AN ANSWER | COST OR BLAST RADIUS |

## Out of scope

- WHAT THIS FLIGHT DELIBERATELY DOES NOT DO, so nobody builds it by accident.

## Open questions

| Question | Default if you say nothing | Blast radius if the default is wrong |
| --- | --- | --- |
| A QUESTION THE REQUIREMENTS LEAVE OPEN, OR DELETE THIS SECTION | DEFAULT | COST |

## Rejected alternatives

- **ALTERNATIVE** — why not, so the idea stays dead.

```flight-plan
{
  "goal": "ONE SENTENCE",
  "config": {
    "max_iterations": 40,
    "expected_iterations": {"min": 8, "max": 14},
    "retry_cap": 3,
    "iteration_timeout": 3600,
    "check": "timeout 1800 ./path/to/whole-flight-check",
    "check_timeout": 1800,
    "preflight": ["timeout 60 npx playwright --version"]
  },
  "evidence": [
    {
      "id": "SUBJECT-NAME",
      "claim": "WHAT THE RESULT PROVES IN PRODUCT LANGUAGE",
      "demonstrations": ["COPY EXACT ID FROM acceptance.json"],
      "stages": [1, 2],
      "artifacts": ["evidence/EXPECTED-CAPTURE.ext"],
      "replay": {"kind": "command", "command": "timeout 300 COMMAND"}
    }
  ],
  "chunks": [
    {"id": 1, "title": "FIRST CAUSAL STAGE", "role": "implementer", "check": "timeout 600 COMMAND", "review": true},
    {"id": 2, "title": "SECOND CAUSAL STAGE", "role": "implementer", "check": "timeout 600 COMMAND", "review": true}
  ],
  "tasks": [
    {"id": 1, "chunk": 1, "title": "TASK TITLE", "done_when": "OBSERVABLE CRITERION", "check": "timeout 300 COMMAND", "depends_on": []},
    {"id": 2, "chunk": 2, "title": "TASK TITLE", "done_when": "OBSERVABLE CRITERION", "check": "timeout 300 COMMAND", "depends_on": [1]}
  ]
}
```

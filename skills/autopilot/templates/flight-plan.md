# Flight plan: GOAL IN A FEW WORDS

## Goal

ONE PARAGRAPH IN THE OPERATOR'S WORDS: what the flight delivers and what a
user can do afterwards that they cannot now.

**Done means:** THE OBSERVABLE END STATE — what passes, what exists, what
the operator can try.

## Design

THE APPROACH IN A PARAGRAPH. Then the concrete shape:

### Components

- **COMPONENT** — what it owns, where it lives (`path/`), what it depends on.

### Interfaces and APIs

- `signature or endpoint` — what it promises, its inputs and outputs, its
  error behaviour.

### Data shapes

- **SHAPE** — fields, where it is produced, where it is consumed.

## Proof

How each promise will be shown to work, decided now so the bar cannot drop
once the evidence is in. Evidence sits at the boundary where a user would
see the promise: a screenshot or recording for anything visual, a
transcript for a command, a before/after pair for data, a test transcript
when the test itself exercises that boundary.

| Accepted demonstration | Evidence coverage | Replay recipe |
| --- | --- | --- |
| WHAT THE OPERATOR CONFIRMED | WHAT WILL BE SHOWN AND WHERE | COMMAND, STEPS, OR ACCEPTED NOT-REPLAYABLE REASON |

Per-chunk checks and the whole-flight check are in the block below. The
`preflight` commands prove every capture and verification tool exists
before takeoff; a missing one stops the flight before it starts.

WHAT CAN ONLY BE JUDGED BY A PERSON, AND WHERE THAT SHOWS UP ON THE
WRAP-UP PAGE.

## Chunks and tasks

```flight-plan
{
  "goal": "ONE SENTENCE",
  "config": {
    "max_iterations": 40,
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
      "demonstrations": ["ACCEPTED DEMONSTRATION SUBJECT"],
      "artifacts": ["evidence/EXPECTED-CAPTURE.ext"],
      "replay": {"kind": "command", "command": "timeout 300 COMMAND"}
    }
  ],
  "chunks": [
    {"id": 1, "title": "CHUNK TITLE", "role": "implementer", "check": "timeout 600 COMMAND", "review": true}
  ],
  "tasks": [
    {"id": 1, "chunk": 1, "title": "TASK TITLE", "done_when": "OBSERVABLE CRITERION", "check": "timeout 300 COMMAND", "depends_on": []}
  ]
}
```

## Staffing

WHICH ROLE DOES WHAT AND WHY. Roles resolve to models through the
operator's roster; the table above counts tasks per role. ROUGH SHAPE OF
THE RUN: iterations expected, anything unusually expensive.

## What you will be asked

| Act | When | What is asked | Rough cost |
| --- | --- | --- | --- |
| Approve this plan | Now | Say yes in chat, or edit and say yes | 10 minutes |
| ANY OTHER ACT, OR DELETE THIS ROW | TRIGGER | PLAIN-WORDS REQUEST | MINUTES |

## Out of scope

- WHAT THIS FLIGHT DELIBERATELY DOES NOT DO, so nobody builds it by accident.

## Open questions

| Question | Default if you say nothing | Blast radius if the default is wrong |
| --- | --- | --- |
| A QUESTION THE REQUIREMENTS LEAVE OPEN, OR DELETE THIS SECTION | DEFAULT | COST |

## Rejected alternatives

- **ALTERNATIVE** — why not, so the idea stays dead.

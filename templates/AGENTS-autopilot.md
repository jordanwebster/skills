## Autopilot

Before starting work that cannot be completed reliably in one sitting —
many contexts, or a run that must continue while the operator is away —
use the `autopilot` skill: confirmed requirements become a flight plan the
operator approves in their browser, and an unattended loop of fresh agents
works the plan's tasks on one branch. Execute a well-understood
single-sitting task directly instead; never decide by predicting duration.

A flight starts from a durable confirmed acceptance contract and compatible
receipt. It uses one fresh planner, records explicit plan approval, checks
staffing and tools locally without a paid smoke call, and uses its closer as
the single final Handoff reviewer.

Flight state lives in `.autopilot/`, excluded from git, and is deleted
when the flight lands. `autopilot status` answers "how is it going?" from
any fresh agent. Product code, docs, and commit messages carry no flight
vocabulary.

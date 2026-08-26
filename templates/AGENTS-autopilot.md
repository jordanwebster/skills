## Autopilot

Before starting work that cannot be completed reliably in one sitting —
many contexts, or a run that must continue while the operator is away —
use the `autopilot` skill: confirmed requirements become a flight plan the
operator approves in their browser, and an unattended loop of fresh agents
works the plan's tasks on one branch. Execute a well-understood
single-sitting task directly instead; never decide by predicting duration.

Flight state lives in `.autopilot/`, excluded from git, and moves to the
operator's records when the flight lands. `autopilot status` answers "how
is it going?" from any fresh agent. Product code, docs, and commit
messages carry no flight vocabulary.

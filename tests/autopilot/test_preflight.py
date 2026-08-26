from __future__ import annotations

import unittest

from autopilot import preflight
from autopilot.plan import read_plan
from autopilot.roster import Roster, RosterError

from helpers import FlightCase, plan_markdown, task, toy_plan, write_roster


class PreflightTests(FlightCase):
    def checks(self, plan: dict, *, roster: Roster | None = None, smoke: bool = True) -> list[preflight.Check]:
        flight = self.seed(plan)
        return preflight.run(flight, read_plan(flight.plan_path), roster or self.roster, smoke=smoke, environment=self.env)

    def test_everything_passes_with_the_fake_roster(self) -> None:
        plan = toy_plan([task(1, "a")], config={"preflight": ["true", "test -f README.md"]})
        checks = self.checks(plan)
        self.assertTrue(all(check.ok for check in checks), preflight.report(checks))
        kinds = sorted({check.kind for check in checks})
        self.assertEqual(kinds, ["cli", "command", "role", "smoke"])
        smokes = [check for check in checks if check.kind == "smoke"]
        self.assertEqual(len(smokes), 1, "identical bindings are launched once")
        self.assertIn("preflight-python3-fake.log", str(list((self.root / ".autopilot" / "runtime" / "logs").glob("*"))[0]))

    def test_unknown_role_fails(self) -> None:
        plan = toy_plan([task(1, "a", role="desiner")])
        checks = self.checks(plan, smoke=False)
        failed = [check for check in checks if not check.ok]
        self.assertEqual([(check.kind, check.subject) for check in failed], [("role", "desiner")])
        self.assertIn("roles:", failed[0].detail)
        with self.assertRaises(RosterError):
            self.roster.resolve("desiner")

    def test_missing_cli_and_failing_command(self) -> None:
        roster = Roster(write_roster(self.base / "broken.toml", cli="/nonexistent/agent"))
        plan = toy_plan([task(1, "a")], config={"preflight": ["exit 3"]})
        checks = self.checks(plan, roster=roster)
        failed = {(check.kind, check.subject): check.detail for check in checks if not check.ok}
        self.assertIn(("cli", "/nonexistent/agent"), failed)
        self.assertIn(("command", "exit 3"), failed)
        self.assertFalse(any(check.kind == "smoke" for check in checks), "no smoke for a CLI that is not there")

    def test_start_refuses_a_plan_the_roster_cannot_staff(self) -> None:
        flight = self.seed(toy_plan([task(1, "a", role="desiner")]))
        started = self.cli("start")
        self.assertEqual(started.returncode, 1)
        self.assertIn("FAIL role     desiner", started.stdout)
        self.assertIn("check(s) failed", started.stdout)
        flight.load()
        self.assertEqual(flight.data["status"], "planned")
        self.assertEqual(self.cli("preflight", "--no-smoke").returncode, 1)

    def test_start_passes_preflight_and_reports_it(self) -> None:
        self.seed(toy_plan([task(1, "a")]))
        started = self.cli("start", "--no-smoke")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertIn("ok   role     planner", started.stdout)
        self.assertIn("Driver running", started.stdout)
        self.cli("stop")


if __name__ == "__main__":
    unittest.main()

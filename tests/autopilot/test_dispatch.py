from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from autopilot import dispatch
from autopilot.roster import Binding


def binding(cli: str, *args: str) -> Binding:
    return Binding(
        role="implementer",
        family="generic",
        model="m",
        effort="",
        constraints=[],
        preferred={"kind": "native", "family": "generic"},
        command=(cli, *args),
    )


class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.log = self.dir / "agent.log"

    def run_agent(self, cli: str, *args: str, timeout: float = 30) -> dispatch.Outcome:
        return dispatch.run_agent(binding(cli, *args), "prompt", cwd=self.dir, log_path=self.log, timeout=timeout)

    def test_ok_exit(self) -> None:
        outcome = self.run_agent("bash", "-c", "cat >/dev/null; echo done")
        self.assertEqual(outcome.exit_class, dispatch.EXIT_OK)
        self.assertIn("done", self.log.read_text())

    def test_timeout_kills_the_process_group(self) -> None:
        started = time.monotonic()
        outcome = self.run_agent("bash", "-c", "sleep 30 & wait", timeout=1)
        self.assertEqual(outcome.exit_class, dispatch.EXIT_TIMEOUT)
        self.assertLess(time.monotonic() - started, 15)

    def test_infra_markers_classify_provider_failures(self) -> None:
        outcome = self.run_agent("bash", "-c", "echo 'API Error: 529 Overloaded — at capacity'; exit 1")
        self.assertEqual(outcome.exit_class, dispatch.EXIT_INFRA)

    def test_plain_failure_is_an_error(self) -> None:
        outcome = self.run_agent("bash", "-c", "echo 'tests failed'; exit 3")
        self.assertEqual(outcome.exit_class, dispatch.EXIT_ERROR)
        self.assertEqual(outcome.return_code, 3)

    def test_missing_executable_is_infra(self) -> None:
        outcome = self.run_agent("/nonexistent/agent")
        self.assertEqual(outcome.exit_class, dispatch.EXIT_CONFIG)

    def test_secrets_are_redacted_from_logs(self) -> None:
        outcome = dispatch.run_agent(
            binding("bash", "-c", "echo token=$MY_API_KEY; echo sk-ant-abcdefghijklmnop"),
            "prompt",
            cwd=self.dir,
            log_path=self.log,
            timeout=10,
            environment={"MY_API_KEY": "supersecretvalue", "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(outcome.exit_class, dispatch.EXIT_OK)
        text = self.log.read_text()
        self.assertNotIn("supersecretvalue", text)
        self.assertNotIn("sk-ant-abcdefghijklmnop", text)
        self.assertIn("<redacted>", text)

    def test_check_runs_under_timeout(self) -> None:
        passed, output = dispatch.run_check("echo hello && exit 0", cwd=self.dir, timeout=5)
        self.assertTrue(passed)
        self.assertEqual(output, "hello")
        passed, output = dispatch.run_check("sleep 5", cwd=self.dir, timeout=0.5)
        self.assertFalse(passed)
        self.assertIn("exceeded", output)

    def test_delegate_command_is_not_reconstructed(self) -> None:
        resolved = binding("agent", "--vendor-owned", "-")
        self.assertEqual(dispatch.build_command(resolved, self.dir), ["agent", "--vendor-owned", "-"])

    def test_auth_and_stale_flags_are_configuration_failures(self) -> None:
        auth = self.run_agent("bash", "-c", "echo 'not authenticated'; exit 1")
        self.assertEqual(auth.exit_class, dispatch.EXIT_CONFIG)
        stale = self.run_agent("bash", "-c", "echo 'unknown option --effort'; exit 2")
        self.assertEqual(stale.exit_class, dispatch.EXIT_CONFIG)


if __name__ == "__main__":
    unittest.main()

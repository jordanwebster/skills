from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "skills" / "delegate" / "lib"


class DelegateCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.roster = self.root / "roster.toml"
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = str(LIB)
        self.env["DELEGATE_ROSTER"] = str(self.roster)

    def write(self, text: str) -> None:
        self.roster.write_text(text, encoding="utf-8")

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "delegate", *args],
            text=True,
            capture_output=True,
            env=self.env,
            timeout=10,
            check=False,
        )

    def test_resolve_returns_transport_neutral_binding_and_argv(self) -> None:
        self.write("""[implementer]
cli = "claude"
args = ["-p", "--permission-mode", "auto"]
model = "opus"
effort = "high"
constraints = { sandbox = "workspace-write" }
""")
        result = self.run_cli("resolve", "implementer", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        binding = output["binding"]
        self.assertEqual(binding["mind"], {"family": "claude", "model": "opus", "effort": "high"})
        self.assertEqual(binding["constraints"], {"sandbox": "workspace-write"})
        self.assertEqual(binding["transports"]["preferred"], {"kind": "native", "family": "claude"})
        self.assertEqual(
            binding["transports"]["fallback"]["command"],
            ["claude", "-p", "--permission-mode", "auto", "--model", "opus", "--effort", "high"],
        )

    def test_codex_adapter_and_effort_override(self) -> None:
        self.write("""[reviewer]
cli = "codex"
args = ["exec", "--sandbox", "read-only"]
model = "gpt"
effort = "medium"
effort_arg = "-c model_reasoning_effort=<effort>"
""")
        result = self.run_cli("resolve", "reviewer", "--effort", "high", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        binding = json.loads(result.stdout)["binding"]
        self.assertEqual(binding["mind"]["effort"], "high")
        self.assertEqual(
            binding["transports"]["fallback"]["command"],
            [
                "codex", "-a", "never", "exec", "--sandbox", "read-only", "--model", "gpt",
                "-c", "model_reasoning_effort=high", "-",
            ],
        )

    def test_unknown_and_unavailable_roles_are_hard_failures(self) -> None:
        self.write("""[planner]
unavailable = "not installed on this machine"
""")
        unknown = self.run_cli("resolve", "reviewer", "--json")
        self.assertEqual(unknown.returncode, 1)
        self.assertEqual(json.loads(unknown.stdout)["error"]["code"], "unknown_role")
        unavailable = self.run_cli("resolve", "planner", "--json")
        self.assertEqual(unavailable.returncode, 1)
        self.assertEqual(json.loads(unavailable.stdout)["error"]["code"], "unavailable_binding")

    def test_missing_roster_has_stable_error_envelope(self) -> None:
        result = self.run_cli("resolve", "planner", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        self.assertEqual(output["schema_version"], 1)
        self.assertFalse(output["ok"])
        self.assertEqual(output["error"]["code"], "roster_missing")

    def test_doctor_is_local_and_reports_missing_executable(self) -> None:
        self.write("""[implementer]
cli = "/definitely/not/an/agent"
model = "model"
effort = ""
""")
        result = self.run_cli("doctor", "--json")
        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertEqual(output["error"]["code"], "doctor_failed")
        self.assertEqual(output["checks"][0]["code"], "missing_executable")

    def test_doctor_accepts_an_installed_generic_cli_without_launching_it(self) -> None:
        self.write(f"""[prober]
cli = {json.dumps(sys.executable)}
args = ["-c", "raise SystemExit('doctor must not launch me')"]
family = "test"
model = "fixture"
effort = ""
""")
        result = self.run_cli("doctor", "--role", "prober", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["ok"])
        self.assertEqual(output["checks"][0]["command"][0], sys.executable)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from scaffold.__main__ import _init, main
from scaffold.adapters.roster import Roster, RosterAdapter, RosterError
from scaffold.adapters.process import _run_process
from scaffold.loop import run_loop
from scaffold.plan import import_plan, retained_plan_path
from scaffold.store import Store


SECRET = "sk-fixture-secret-1234567890"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


class RosterTests(unittest.TestCase):
    def test_role_and_effort_resolution_is_mechanical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            roster_path = Path(temporary) / "roster.toml"
            roster_path.write_text(
                """
[default]
cli = "claude"
args = ["-p"]
model = "opus"
effort = "high"

[implementer]
cli = "codex"
args = ["exec"]
model = "gpt-test"
effort = "medium"
effort_arg = "-c model_reasoning_effort=<effort>"
""",
                encoding="utf-8",
            )
            roster = Roster(roster_path)

            selected = roster.resolve("implementer", "xhigh")
            fallback = roster.resolve("unknown-role", "small")

            self.assertEqual("codex/gpt-test/xhigh", selected.label)
            self.assertEqual(
                ("-c", "model_reasoning_effort=xhigh"), selected.effort_args
            )
            self.assertFalse(selected.used_default)
            self.assertFalse(selected.effort_fallback)
            self.assertEqual("claude/opus/high", fallback.label)
            self.assertTrue(fallback.used_default)
            self.assertTrue(fallback.effort_fallback)

    def test_roster_requires_default_and_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            roster_path = Path(temporary) / "roster.toml"
            roster_path.write_text(
                '[implementer]\ncli="codex"\nmodel="gpt"\neffort="high"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RosterError, "default"):
                Roster(roster_path)

            roster_path.write_text(
                '[default]\ncli="codex"\nmodel="gpt"\neffort="high"\n'
                'unsafe="yes"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RosterError, "unknown fields"):
                Roster(roster_path)


class ProcessGroupTests(unittest.TestCase):
    def test_descendants_are_stopped_after_success_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = (
                "import signal,sys,time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); p=Path(sys.argv[1]); "
                "i=0; p.write_text('ready'); "
                "exec(\"while True:\\n i += 1\\n p.write_text(str(i))\\n time.sleep(.02)\")"
            )
            for name, parent_tail, timeout, expected_timeout in (
                (
                    "success",
                    "while not marker.exists():\n time.sleep(.01)",
                    3.0,
                    False,
                ),
                (
                    "timeout",
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    "while True:\n time.sleep(1)",
                    0.2,
                    True,
                ),
            ):
                with self.subTest(name=name):
                    marker = root / f"{name}.txt"
                    stderr_path = root / f"{name}.stderr"
                    parent = (
                        "import signal,subprocess,sys,time; from pathlib import Path; "
                        "marker=Path(sys.argv[1]); "
                        f"subprocess.Popen([sys.executable, '-c', {child!r}, str(marker)]); "
                        f"exec({parent_tail!r})"
                    )
                    return_code, timed_out = _run_process(
                        [sys.executable, "-c", parent, str(marker)],
                        prompt="probe",
                        cwd=root,
                        environment=os.environ.copy(),
                        stdout_path=root / f"{name}.stdout",
                        stderr_path=stderr_path,
                        timeout=timeout,
                    )
                    self.assertEqual(expected_timeout, timed_out)
                    self.assertTrue(
                        marker.is_file(),
                        stderr_path.read_text(encoding="utf-8"),
                    )
                    stopped_value = marker.read_text(encoding="utf-8")
                    time.sleep(0.1)
                    self.assertEqual(
                        stopped_value, marker.read_text(encoding="utf-8")
                    )

class RealAdapterFlightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.product = self.root / "product"
        self.product.mkdir()
        git(self.product, "init", "--quiet")
        git(self.product, "config", "user.name", "Adapter Test")
        git(self.product, "config", "user.email", "adapter@example.invalid")
        checks = self.product / "checks"
        checks.mkdir()
        (checks / "check_file.py").write_text(
            textwrap.dedent(
                """\
                import json
                import os
                from pathlib import Path

                exists = Path("artifact.txt").is_file()
                Path(os.environ["SCAFFOLD_RESULT_PATH"]).write_text(
                    json.dumps({
                        "schema_version": 1,
                        "candidate_head": os.environ["SCAFFOLD_CANDIDATE_HEAD"],
                        "check_id": os.environ["SCAFFOLD_CHECK_ID"],
                        "observations": [{
                            "id": "artifact-exists",
                            "status": "passed" if exists else "failed",
                        }],
                    }) + "\\n",
                    encoding="utf-8",
                )
                raise SystemExit(0 if exists else 1)
                """
            ),
            encoding="utf-8",
        )
        (self.product / "README.md").write_text("# Product\n", encoding="utf-8")
        (self.product / "control-alias").symlink_to(".SCAFFOLDING")
        git(self.product, "add", "README.md", "checks/check_file.py", "control-alias")
        git(self.product, "commit", "--quiet", "-m", "Initialize adapter product")
        self.base_head = git(self.product, "rev-parse", "HEAD")
        with redirect_stdout(io.StringIO()):
            _init(self.product, "Adapter flight", "adapter-flight")
        self.workspace = self.product / ".scaffolding" / "adapter-flight"
        self.store = Store(self.workspace)
        self.plan_path = self.root / "plan.html"
        self.plan_path.write_text(
            '<script type="application/json" id="scaffold-plan">\n'
            + json.dumps(
                {
                    "schema_version": 1,
                    "goal": "Adapter flight",
                    "test_paths": ["checks/**"],
                    "tasks": [
                        {
                            "id": "build",
                            "title": "Build through a real adapter",
                            "role": "implementer",
                            "effort": "high",
                            "check": "python3 checks/check_file.py",
                            "depends_on": [],
                            "decisions": ["Write artifact.txt"],
                        }
                    ],
                }
            )
            + "\n</script>\n",
            encoding="utf-8",
        )
        import_plan(self.store, self.plan_path)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        fixture = self.bin_dir / "fixture-cli.py"
        fixture.write_text(self._fixture_source(), encoding="utf-8")
        fixture.chmod(0o755)
        (self.bin_dir / "codex").symlink_to(fixture)
        (self.bin_dir / "claude").symlink_to(fixture)

    def test_codex_fixture_runs_green_and_redacts_retained_logs(self) -> None:
        self._assert_vendor_flight("codex")

    def test_claude_fixture_runs_green_and_cannot_see_control_alias(self) -> None:
        self._assert_vendor_flight("claude")

    def test_quota_failure_is_infrastructure_and_does_not_import_candidate(self) -> None:
        roster_path = self._write_roster("codex")
        adapter = RosterAdapter(self.store, roster_path)
        with patch.dict(os.environ, {"SCAFFOLD_FIXTURE_MODE": "quota"}):
            result = run_loop(
                self.store,
                self.product,
                adapter,
                holder="fixture-worker",
                dispatch_timeout=5,
                durable_paths=(retained_plan_path(self.store),),
                binding_label="roster",
            )

        self.assertEqual("failed", result.status)
        task = self.store.load()["tasks"][0]
        self.assertEqual(1, task["attempts"]["infra"])
        self.assertEqual(0, task["attempts"]["work"])
        self.assertEqual(self.base_head, git(self.product, "rev-parse", "HEAD"))

    def test_malformed_claim_burns_work_without_importing_candidate(self) -> None:
        roster_path = self._write_roster("claude")
        adapter = RosterAdapter(self.store, roster_path)
        with patch.dict(os.environ, {"SCAFFOLD_FIXTURE_MODE": "malformed"}):
            result = run_loop(
                self.store,
                self.product,
                adapter,
                holder="fixture-worker",
                dispatch_timeout=5,
                durable_paths=(retained_plan_path(self.store),),
            )

        self.assertEqual("failed", result.status)
        task = self.store.load()["tasks"][0]
        self.assertEqual(0, task["attempts"]["infra"])
        self.assertEqual(1, task["attempts"]["work"])
        self.assertEqual(self.base_head, git(self.product, "rev-parse", "HEAD"))

    def test_roster_arguments_cannot_override_vendor_sandbox(self) -> None:
        roster_path = self._write_roster("codex")
        source = roster_path.read_text(encoding="utf-8").replace(
            'args = ["exec"]',
            'args = ["exec", "--dangerously-bypass-approvals-and-sandbox"]',
        )
        roster_path.write_text(source, encoding="utf-8")
        result = run_loop(
            self.store,
            self.product,
            RosterAdapter(self.store, roster_path),
            holder="fixture-worker",
            dispatch_timeout=5,
            durable_paths=(retained_plan_path(self.store),),
        )

        self.assertEqual("failed", result.status)
        transcript = json.loads(
            (self.workspace / "adapter-results" / "build" / "transcript.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("must be exactly", transcript["error"])
        task = self.store.load()["tasks"][0]
        self.assertEqual(1, task["attempts"]["infra"])
        self.assertEqual(0, task["attempts"]["work"])
        self.assertEqual(self.base_head, git(self.product, "rev-parse", "HEAD"))

    def test_candidate_containing_auth_secret_is_not_published(self) -> None:
        roster_path = self._write_roster("codex")
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": SECRET, "SCAFFOLD_FIXTURE_MODE": "commit-secret"},
        ):
            result = run_loop(
                self.store,
                self.product,
                RosterAdapter(self.store, roster_path),
                holder="fixture-worker",
                dispatch_timeout=5,
                durable_paths=(retained_plan_path(self.store),),
            )

        self.assertEqual("failed", result.status)
        self.assertEqual(self.base_head, git(self.product, "rev-parse", "HEAD"))
        task = self.store.load()["tasks"][0]
        self.assertEqual(1, task["attempts"]["work"])
        retained = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.workspace / "adapter-results").rglob("*")
            if path.is_file()
        )
        self.assertNotIn(SECRET, retained)
        self.assertIn("candidate contains a sensitive value", retained)

    def test_candidate_with_deleted_intermediate_secret_is_not_published(self) -> None:
        roster_path = self._write_roster("claude")
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": SECRET,
                "SCAFFOLD_FIXTURE_MODE": "commit-secret-then-delete",
            },
        ):
            result = run_loop(
                self.store,
                self.product,
                RosterAdapter(self.store, roster_path),
                holder="fixture-worker",
                dispatch_timeout=5,
                durable_paths=(retained_plan_path(self.store),),
            )

        self.assertEqual("failed", result.status)
        self.assertEqual(self.base_head, git(self.product, "rev-parse", "HEAD"))
        task = self.store.load()["tasks"][0]
        self.assertEqual(1, task["attempts"]["work"])
        retained = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.workspace / "adapter-results").rglob("*")
            if path.is_file()
        )
        self.assertNotIn(SECRET, retained)
        self.assertIn("candidate contains a sensitive value in history", retained)

    def _assert_vendor_flight(self, vendor: str) -> None:
        roster_path = self._write_roster(vendor)
        output = io.StringIO()
        with patch.dict(os.environ, {"M4_TEST_API_KEY": SECRET}):
            with redirect_stdout(output):
                return_code = main(
                    [
                        "run",
                        str(self.workspace),
                        "--adapter",
                        "roster",
                        "--roster",
                        str(roster_path),
                        "--holder",
                        "fixture-worker",
                    ]
                )

        self.assertEqual(0, return_code, output.getvalue())
        self.assertIn("complete: all tasks are green", output.getvalue())
        self.assertTrue((self.product / "artifact.txt").is_file())
        task = self.store.load()["tasks"][0]
        self.assertEqual("green", task["verdict"])
        retained = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.workspace / "adapter-results").rglob("*")
            if path.is_file()
        )
        self.assertNotIn(SECRET, retained)
        self.assertIn("<redacted>", retained)
        transcript = json.loads(
            (self.workspace / "adapter-results" / "build" / "transcript.json").read_text(
                encoding="utf-8"
            )
        )
        command = transcript["command"]
        if vendor == "codex":
            self.assertIn("workspace-write", command)
            self.assertIn("--output-schema", command)
            self.assertIn("--ignore-user-config", command)
            self.assertEqual(["-a", "never", "exec"], command[1:4])
        else:
            self.assertIn("--json-schema", command)
            self.assertIn("--setting-sources", command)
            settings = Path(command[command.index("--settings") + 1])
            self.assertIn("scaffold-worker-", str(settings))

    def _write_roster(self, vendor: str) -> Path:
        roster_path = self.root / f"{vendor}-roster.toml"
        executable = self.bin_dir / vendor
        if vendor == "codex":
            args = '["exec"]'
            effort_arg = 'effort_arg = "-c model_reasoning_effort=<effort>"\n'
        else:
            args = '["-p"]'
            effort_arg = ""
        roster_path.write_text(
            "[default]\n"
            f'cli = "{executable}"\n'
            f"args = {args}\n"
            f'model = "fixture-model"\n'
            'effort = "high"\n'
            + effort_arg
            + "\n[implementer]\n"
            f'cli = "{executable}"\n'
            f"args = {args}\n"
            f'model = "fixture-model"\n'
            'effort = "high"\n'
            + effort_arg,
            encoding="utf-8",
        )
        return roster_path

    @staticmethod
    def _fixture_source() -> str:
        return textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json
            import os
            from pathlib import Path
            import subprocess
            import sys

            vendor = Path(sys.argv[0]).name
            prompt = sys.stdin.read()
            if "structured claim" not in prompt:
                print("missing structured-claim brief", file=sys.stderr)
                raise SystemExit(2)
            if os.environ.get("SCAFFOLD_FIXTURE_MODE") == "quota":
                print("quota exceeded", file=sys.stderr)
                raise SystemExit(1)
            if Path(".scaffolding").exists() or Path("control-alias").exists():
                print("worker could reach framework control state", file=sys.stderr)
                raise SystemExit(3)
            if subprocess.run(["git", "remote"], check=True, capture_output=True, text=True).stdout.strip():
                print("worker clone retained a source remote", file=sys.stderr)
                raise SystemExit(5)
            if "M4_TEST_API_KEY" in os.environ:
                print("worker inherited an unrelated secret", file=sys.stderr)
                raise SystemExit(6)
            working_directory = Path.cwd().resolve()
            for directory_name in ("PWD", "OLDPWD"):
                inherited = os.environ.get(directory_name)
                if not inherited or Path(inherited).resolve() != working_directory:
                    print(f"{{directory_name}} disclosed the source checkout", file=sys.stderr)
                    raise SystemExit(7)
            if os.environ.get("SCAFFOLD_FIXTURE_MODE") == "commit-secret-then-delete":
                Path("transient.txt").write_text(os.environ["ANTHROPIC_API_KEY"] + "\\n")
                subprocess.run(["git", "config", "user.name", "Fixture CLI"], check=True)
                subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], check=True)
                subprocess.run(["git", "add", "transient.txt"], check=True)
                subprocess.run(["git", "commit", "--quiet", "-m", "Add transient data"], check=True)
                Path("transient.txt").unlink()
            content = "built by " + vendor + "\\n"
            if os.environ.get("SCAFFOLD_FIXTURE_MODE") == "commit-secret":
                content = os.environ["OPENAI_API_KEY"] + "\\n"
            Path("artifact.txt").write_text(content)
            subprocess.run(["git", "config", "user.name", "Fixture CLI"], check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "add", "--all"], check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "Build adapter artifact"], check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip()
            claim = {{
                "claim": "passes",
                "candidate_head": head,
                "artifacts": ["artifact.txt", "{SECRET}"],
            }}
            if os.environ.get("SCAFFOLD_FIXTURE_MODE") == "malformed":
                claim = {{"claim": "passes"}}
            print("{SECRET}", file=sys.stderr)
            if vendor == "codex":
                output_path = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
                output_path.write_text(json.dumps(claim) + "\\n")
                print(json.dumps({{"type": "result", "secret": "{SECRET}"}}))
            elif vendor == "claude":
                print(json.dumps({{"type": "result", "structured_output": claim}}))
            else:
                raise SystemExit(4)
            """
        )


if __name__ == "__main__":
    unittest.main()

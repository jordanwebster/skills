from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "skills" / "intake" / "lib"


def contract(*, confirmed: bool = True, covers: str = "retry, no-duplicate", decision: str = "none") -> str:
    if decision == "none":
        decisions = "- None."
    elif decision == "open":
        decisions = """- How many retries? <!-- id: retry-count -->
  - Decision: Three
  - Blast radius: Requests may take longer
  - Provenance: agent-proposed
  - Resolution: open"""
    else:
        decisions = """- How many retries? <!-- id: retry-count -->
  - Decision: Three
  - Blast radius: Requests may take longer
  - Provenance: agent-proposed
  - Resolution: vetoed"""
    confirmation = "CONFIRMED" if confirmed else "PENDING"
    return f"""# Acceptance contract

## Goal

Retry transient checkout failures without duplicate charges.

## Observable expectations

- A transient failure is retried. <!-- id: retry -->

## Exclusions

- A retry never creates a second charge. <!-- id: no-duplicate -->

## Acceptance scenarios

- Retry through the test gateway. <!-- id: test-gateway; covers: {covers} -->
  - Demonstration: A transcript at the payment boundary.
  - Limitation: The gateway is a test environment.

## Material decisions

{decisions}

## Accepted gaps

- None.

## Exceptional operator acts

- None.

## Waivers

- None.

## Confirmation

Final all-ok: {confirmation}
"""


class IntakeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "acceptance.md"
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = str(LIB)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "intake", *args],
            text=True,
            capture_output=True,
            env=self.env,
            timeout=10,
            check=False,
        )

    def test_finalize_writes_narrow_digest_receipt(self) -> None:
        self.path.write_text(contract(), encoding="utf-8")
        result = self.run_cli("finalize", str(self.path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        digest = "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(output["contract_digest"], digest)
        receipt_path = Path(output["receipt"])
        expected_receipt = self.path.resolve().with_name(self.path.name + ".acceptance.json")
        self.assertEqual(receipt_path, expected_receipt)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(set(receipt), {"schema_version", "contract_digest", "confirmed_at"})
        self.assertEqual(receipt["contract_digest"], digest)

    def test_pending_confirmation_is_an_actionable_json_error(self) -> None:
        self.path.write_text(contract(confirmed=False), encoding="utf-8")
        result = self.run_cli("finalize", str(self.path), "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        error = json.loads(result.stdout)["error"]
        self.assertEqual(error["code"], "unfinished_contract")
        self.assertIn("confirmation", error["recovery"])
        self.assertFalse(Path(str(self.path) + ".acceptance.json").exists())

    def test_every_expectation_and_exclusion_needs_coverage(self) -> None:
        self.path.write_text(contract(covers="retry"), encoding="utf-8")
        result = self.run_cli("finalize", str(self.path), "--json")
        self.assertEqual(result.returncode, 1)
        error = json.loads(result.stdout)["error"]
        self.assertEqual(error["code"], "uncovered_expectations")
        self.assertIn("no-duplicate", error["message"])

    def test_open_material_decision_fails(self) -> None:
        self.path.write_text(contract(decision="open"), encoding="utf-8")
        result = self.run_cli("finalize", str(self.path), "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "unresolved_decision")

    def test_vetoed_agent_expansion_needs_replacement(self) -> None:
        self.path.write_text(contract(decision="vetoed"), encoding="utf-8")
        result = self.run_cli("finalize", str(self.path), "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "unmarked_expansion")


if __name__ == "__main__":
    unittest.main()

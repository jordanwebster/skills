from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from autopilot import acceptance


class AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inspection = self.root / "acceptance.json"
        self.workspace = self.root / "handoff"
        self.workspace.mkdir()
        acceptance.write(
            self.inspection,
            {
                "acceptance": {
                    "demonstrations": [
                        {"id": "streaming", "description": "Streaming updates are visible."},
                        {"id": "completion", "description": "The final result is visible."},
                    ]
                }
            },
        )

    def proof(self, demonstrations: list[dict[str, str]]) -> None:
        (self.workspace / "proof.json").write_text(
            json.dumps({"accepted_demonstrations": demonstrations}),
            encoding="utf-8",
        )

    def test_exact_confirmed_demonstrations_pass(self) -> None:
        self.proof(
            [
                {"id": "streaming", "description": "Streaming updates are visible."},
                {"id": "completion", "description": "The final result is visible."},
            ]
        )
        acceptance.verify_proof(self.inspection, self.workspace)

    def test_a_self_consistent_proof_cannot_drop_a_confirmed_demonstration(self) -> None:
        self.proof([{"id": "streaming", "description": "Streaming updates are visible."}])
        with self.assertRaisesRegex(acceptance.AcceptanceError, "missing: The final result is visible"):
            acceptance.verify_proof(self.inspection, self.workspace)

    def test_a_proof_cannot_rename_a_confirmed_demonstration(self) -> None:
        self.proof(
            [
                {"id": "streaming", "description": "Streaming appears eventually."},
                {"id": "completion", "description": "The final result is visible."},
            ]
        )
        with self.assertRaisesRegex(acceptance.AcceptanceError, "renamed: Streaming updates are visible"):
            acceptance.verify_proof(self.inspection, self.workspace)


if __name__ == "__main__":
    unittest.main()

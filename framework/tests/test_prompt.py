from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scaffold.prompt import assemble_prompt


class PromptTests(unittest.TestCase):
    def test_assembly_is_deterministic_and_preserves_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "first.md"
            second = root / "second.md"
            first.write_text("first durable decision\n", encoding="utf-8")
            second.write_text("second durable decision\n", encoding="utf-8")
            task = {"id": "task-1", "decisions": ["keep the boundary"]}

            left = assemble_prompt(task, (first, second))
            right = assemble_prompt(task, (first, second))

        self.assertEqual(left, right)
        self.assertLess(left.index("TASK RECORD"), left.index("first durable"))
        self.assertLess(left.index("first durable"), left.index("second durable"))
        self.assertIn("only the framework", left)


if __name__ == "__main__":
    unittest.main()

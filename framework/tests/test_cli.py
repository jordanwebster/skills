from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scaffold.__main__ import _init


class InitTests(unittest.TestCase):
    def test_rerun_repairs_config_missing_after_store_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            product = Path(temporary_directory) / "product"
            product.mkdir()
            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=product,
                check=True,
                timeout=30,
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, _init(product, "Recover init", "recover-init"))
            workspace = product / ".scaffolding" / "recover-init"
            (workspace / "config.json").unlink()

            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, _init(product, "Recover init", "recover-init"))

            config = json.loads(
                (workspace / "config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(str(product.resolve()), config["product_root"])
            self.assertEqual("Recover init", config["title"])
            self.assertEqual([], list(workspace.glob(".config.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()

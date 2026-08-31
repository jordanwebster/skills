from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from autopilot import gitops
from autopilot.loop import Driver
from autopilot.state import Flight

from helpers import git, make_repo


class GitOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.main = self.base / "main"
        self.main.mkdir()
        make_repo(self.main)

    def resolved_git_path(self, root: Path, name: str) -> Path:
        path = Path(git(root, "rev-parse", "--git-path", name).strip())
        return path if path.is_absolute() else root / path

    def assert_safe_checkpoint(self, root: Path, expected_exclude: Path) -> None:
        gitops.exclude(root, ".autopilot/")
        gitops.exclude(root, ".autopilot/")

        exclude_path = self.resolved_git_path(root, "info/exclude")
        self.assertEqual(exclude_path.resolve(), expected_exclude.resolve())
        self.assertEqual(
            exclude_path.read_text(encoding="utf-8").splitlines().count(".autopilot/"),
            1,
            "the shared exclude entry stays idempotent",
        )
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", ".autopilot/probe"],
            cwd=root,
            check=False,
        )
        self.assertEqual(ignored.returncode, 0)

        flight = Flight(root).create(
            "Safe checkpoint",
            gitops.current_branch(root),
            gitops.head(root),
        )
        flight.runtime_dir.mkdir(parents=True, exist_ok=True)
        (flight.runtime_dir / "driver.log").write_text(
            "private runtime state\n", encoding="utf-8"
        )
        (root / "product.txt").write_text("product change\n", encoding="utf-8")
        Driver(flight, None)._commit_leftovers("WIP: safe checkpoint")

        committed = git(root, "show", "--format=", "--name-only", "HEAD").splitlines()
        self.assertIn("product.txt", committed)
        self.assertFalse(
            any(path == ".autopilot" or path.startswith(".autopilot/") for path in committed)
        )
        self.assertEqual(git(root, "ls-files", ".autopilot").strip(), "")

    def test_main_checkout_uses_git_resolved_exclude_and_safe_checkpoint(self) -> None:
        self.assert_safe_checkpoint(self.main, self.main / ".git" / "info" / "exclude")

    def test_linked_worktree_uses_shared_exclude_and_safe_checkpoint(self) -> None:
        linked = self.base / "linked"
        git(self.main, "worktree", "add", "-q", "-b", "linked", str(linked))

        shared_exclude = self.main / ".git" / "info" / "exclude"
        self.assert_safe_checkpoint(linked, shared_exclude)

        worktree_git_dir = Path(git(linked, "rev-parse", "--git-dir").strip())
        inert_exclude = worktree_git_dir / "info" / "exclude"
        inert_text = inert_exclude.read_text(encoding="utf-8") if inert_exclude.exists() else ""
        self.assertNotIn(".autopilot/", inert_text.splitlines())

    def test_exclude_refuses_when_git_cannot_confirm_the_probe(self) -> None:
        probe = self.main / ".autopilot" / ".autopilot-ignore-probe"
        probe.parent.mkdir()
        probe.write_text("tracked\n", encoding="utf-8")
        git(self.main, "add", "-f", ".autopilot/.autopilot-ignore-probe")
        git(self.main, "commit", "-q", "-m", "Track the probe")

        with self.assertRaisesRegex(gitops.GitError, "refusing to use private flight state"):
            gitops.exclude(self.main, ".autopilot/")
        self.assertFalse(Flight(self.main).exists(), "failed verification creates no flight")

    def test_checkpoint_refuses_if_the_ignore_invariant_disappears(self) -> None:
        gitops.exclude(self.main, ".autopilot/")
        flight = Flight(self.main).create("Guard checkpoint", "main", gitops.head(self.main))
        exclude_path = self.resolved_git_path(self.main, "info/exclude")
        remaining = [
            line for line in exclude_path.read_text(encoding="utf-8").splitlines()
            if line != ".autopilot/"
        ]
        exclude_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        (self.main / "product.txt").write_text("must remain uncommitted\n", encoding="utf-8")

        with self.assertRaisesRegex(gitops.GitError, "does not ignore"):
            Driver(flight, None)._commit_leftovers("WIP: unsafe checkpoint")
        self.assertEqual(git(self.main, "rev-parse", "HEAD").strip(), flight.data["base"])
        self.assertEqual(git(self.main, "ls-files", ".autopilot").strip(), "")


if __name__ == "__main__":
    unittest.main()

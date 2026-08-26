"""Thin git helpers; every call is bounded and raises with git's own message."""

from __future__ import annotations

from pathlib import Path
import subprocess


class GitError(RuntimeError):
    pass


def git(root: Path, *arguments: str, timeout: float = 120, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GitError(f"git {' '.join(arguments)}: {detail}")
    return completed.stdout


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD").strip()


def current_branch(root: Path) -> str:
    return git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def is_dirty(root: Path) -> bool:
    return bool(git(root, "status", "--porcelain").strip())


def dirty_paths(root: Path) -> list[str]:
    lines = git(root, "status", "--porcelain").splitlines()
    return [line[3:] for line in lines if line.strip()]


def commit_all(root: Path, message: str) -> str | None:
    """Stage everything and commit; return the new commit, or None if clean."""

    git(root, "add", "-A")
    if not git(root, "diff", "--cached", "--name-only").strip():
        return None
    git(root, "commit", "-q", "-m", message)
    return head(root)


def ensure_branch(root: Path, branch: str) -> None:
    """Check the flight branch out, creating it from HEAD if it does not exist."""

    if current_branch(root) == branch:
        return
    exists = git(root, "rev-parse", "--verify", "--quiet", branch, check=False).strip()
    if exists:
        git(root, "checkout", "-q", branch)
    else:
        git(root, "checkout", "-q", "-b", branch)


def exclude(root: Path, pattern: str) -> None:
    """Add a pattern to the repository-local exclude file, once."""

    info = root / ".git" / "info"
    if not info.is_dir():
        git_dir = Path(git(root, "rev-parse", "--git-dir").strip())
        info = (root / git_dir if not git_dir.is_absolute() else git_dir) / "info"
    info.mkdir(parents=True, exist_ok=True)
    path = info / "exclude"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if pattern in existing.splitlines():
        return
    with path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(pattern + "\n")


def diff_stat(root: Path, base: str, target: str = "HEAD") -> str:
    return git(root, "diff", "--stat", f"{base}..{target}", check=False)


def changed_files(root: Path, base: str, target: str = "HEAD") -> list[str]:
    return [
        line
        for line in git(root, "diff", "--name-only", f"{base}..{target}", check=False).splitlines()
        if line.strip()
    ]


def log_oneline(root: Path, base: str, target: str = "HEAD", limit: int = 50) -> str:
    return git(root, "log", "--oneline", f"-{limit}", f"{base}..{target}", check=False)

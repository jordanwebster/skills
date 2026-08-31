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


def tracked_paths(root: Path, pathspec: str) -> list[str]:
    """Return tracked paths matching a repository-relative pathspec."""

    return [line for line in git(root, "ls-files", "--", pathspec).splitlines() if line]


def require_ignored(root: Path, path: str) -> None:
    """Raise unless Git confirms that a repository-relative path is ignored."""

    try:
        git(root, "check-ignore", "-q", "--", path)
    except GitError as error:
        raise GitError(
            f"Git does not ignore {path}; refusing to expose private flight state"
        ) from error


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
    """Add and verify a pattern in Git's repository-local exclude file."""

    resolved = Path(git(root, "rev-parse", "--git-path", "info/exclude").strip())
    path = resolved if resolved.is_absolute() else root / resolved
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if pattern not in existing.splitlines():
            with path.open("a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write(pattern + "\n")
    except OSError as error:
        raise GitError(f"cannot update Git exclude file {path}: {error}") from error

    probe = f"{pattern.rstrip('/')}/.autopilot-ignore-probe"
    try:
        require_ignored(root, probe)
    except GitError as error:
        raise GitError(
            f"Git did not ignore {probe} after updating {path}; refusing to use private flight state"
        ) from error


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

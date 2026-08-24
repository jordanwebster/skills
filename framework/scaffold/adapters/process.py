"""Shared safe process boundary for real CLI adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from typing import Any

from .base import DispatchResult
from ..store import SCHEMA_VERSION, Store, StoreError, validate_task_id


CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "claim": {"enum": ["passes", "ambiguity"]},
        "candidate_head": {
            "type": ["string", "null"],
            "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$",
        },
        "artifacts": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "reason": {"type": ["string", "null"]},
        "review": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "minLength": 1},
                            "severity": {
                                "enum": ["low", "medium", "high", "critical"]
                            },
                            "summary": {"type": "string", "minLength": 1},
                            "evidence": {"type": "string", "minLength": 1},
                        },
                        "required": ["id", "severity", "summary", "evidence"],
                    },
                }
            },
            "required": ["findings"],
        },
    },
    "required": ["claim", "candidate_head", "artifacts", "reason"],
}

_SECRET_ENV_NAME = re.compile(
    r"(?:api[_-]?key|auth|credential|passwd|password|secret|token)", re.IGNORECASE
)
_KNOWN_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)\S+"),
)
_INFRA_MARKERS = (
    "quota",
    "rate limit",
    "rate_limit",
    "overloaded",
    "capacity",
    "too many requests",
    "authentication",
    "not authenticated",
    "not logged in",
    "please log in",
    "network error",
    "connection refused",
    "connection reset",
    "could not resolve",
    "unexpected argument",
    "unknown option",
)


class ProcessAdapter(ABC):
    """Run a vendor CLI in a control-state-free clone and import its claim."""

    adapter_name: str
    auth_environment_names: frozenset[str] = frozenset()

    def __init__(self, store: Store, resolved_binding: Any):
        self.store = store
        self.binding = resolved_binding

    def dispatch(
        self,
        prompt: str,
        binding: Mapping[str, Any],
        sandbox: str,
        timeout: float,
    ) -> DispatchResult:
        if timeout <= 0:
            raise ValueError("dispatch timeout must be positive")
        task_id = validate_task_id(_required_text(binding, "task_id"))
        role = _required_text(binding, "role")
        expected_sandbox = "read-only" if role == "reviewer" else "workspace-write"
        if sandbox != expected_sandbox:
            raise ValueError(f"{role} tasks require the {expected_sandbox} sandbox")
        holder = _required_text(binding, "holder")
        lease_id = _required_text(binding, "lease_id")
        product_root = Path(_required_text(binding, "product_root")).resolve()
        base_head = _required_text(binding, "base_head")
        reservation = _required_positive_number(
            binding, "claim_reservation_seconds"
        )
        result_root = self.store.root / "adapter-results" / task_id
        result_root.mkdir(parents=True, exist_ok=True)
        transcript_path = result_root / "transcript.json"
        last_message_path = result_root / "last-message.json"

        transcript: dict[str, Any] = {
            "adapter": self.adapter_name,
            "task_id": task_id,
            "binding": self.binding.label,
            "role_fell_back_to_default": self.binding.used_default,
            "effort_fell_back_to_roster": self.binding.effort_fallback,
            "sandbox": sandbox,
            "prompt_bytes": len(prompt.encode("utf-8")),
        }
        raw_last_message = ""
        parent_environment = os.environ.copy()
        environment = _worker_environment(
            parent_environment, self.auth_environment_names
        )
        exit_class = "worker-error"
        failure_class = "infra"
        failure_reason: str | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="scaffold-worker-") as temporary:
                temporary_root = Path(temporary)
                checkout = temporary_root / "product"
                raw_stdout = temporary_root / "stdout"
                raw_stderr = temporary_root / "stderr"
                raw_last_path = temporary_root / "last-message.json"
                schema_path = temporary_root / "claim-schema.json"
                schema_path.write_text(
                    json.dumps(CLAIM_SCHEMA, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                _git(
                    product_root,
                    ("clone", "--quiet", "--local", "--no-hardlinks", ".", str(checkout)),
                    timeout=timeout,
                )
                _git(checkout, ("checkout", "--quiet", "--detach", base_head), timeout=timeout)
                _git(checkout, ("remote", "remove", "origin"), timeout=timeout)
                command = self.command(
                    checkout=checkout,
                    schema_path=schema_path,
                    raw_last_path=raw_last_path,
                    sandbox=sandbox,
                )
                transcript["command"] = command
                return_code, timed_out = _run_process(
                    command,
                    prompt=prompt,
                    cwd=checkout,
                    environment=environment,
                    stdout_path=raw_stdout,
                    stderr_path=raw_stderr,
                    timeout=timeout,
                )
                stdout = _read_output(raw_stdout)
                stderr = _read_output(raw_stderr)
                transcript["return_code"] = return_code
                transcript["stdout"] = _redact(stdout, environment)
                transcript["stderr"] = _redact(stderr, environment)
                if timed_out:
                    exit_class = "killed"
                    transcript["error"] = "worker exceeded dispatch timeout"
                elif return_code != 0:
                    combined = f"{stdout}\n{stderr}".casefold()
                    exit_class = (
                        "infra"
                        if any(marker in combined for marker in _INFRA_MARKERS)
                        else "worker-error"
                    )
                    transcript["error"] = f"worker exited {return_code}"
                    detail = stderr.strip() or stdout.strip()
                    failure_reason = _redact(
                        (
                            f"worker exited {return_code}: {detail[:500]}"
                            if detail
                            else f"worker exited {return_code}"
                        ),
                        parent_environment,
                    )
                else:
                    failure_class = "worker-error"
                    claim, raw_last_message = self.extract_claim(
                        stdout=stdout,
                        raw_last_path=raw_last_path,
                    )
                    normalized = _normalize_claim(
                        claim,
                        require_review=role == "reviewer",
                    )
                    if normalized["claim"] == "ambiguity":
                        failure_reason = _redact(
                            normalized["reason"], parent_environment
                        )
                        transcript["reason"] = failure_reason
                        exit_class = "ambiguity"
                    else:
                        candidate_head = normalized["candidate_head"]
                        observed_head = _git(
                            checkout, ("rev-parse", "HEAD"), timeout=timeout
                        ).strip()
                        if observed_head != candidate_head:
                            raise ValueError("structured claim does not name checkout HEAD")
                        if _git(checkout, ("status", "--porcelain"), timeout=timeout).strip():
                            raise ValueError("worker checkout is dirty after claimed commit")
                        if role == "reviewer" and candidate_head != base_head:
                            raise ValueError("reviewer cannot publish a product commit")
                        _reject_candidate_secrets(
                            checkout,
                            base_head,
                            candidate_head,
                            parent_environment,
                            timeout=timeout,
                        )
                        failure_class = "infra"
                        _publish_candidate(
                            product_root,
                            checkout,
                            base_head,
                            candidate_head,
                            timeout=timeout,
                        )
                        safe_claim = {
                            "schema_version": SCHEMA_VERSION,
                            "task_id": task_id,
                            "holder": holder,
                            "lease_id": lease_id,
                            "claim": "passes",
                            "candidate_head": candidate_head,
                            "artifacts": [
                                _redact(item, parent_environment)
                                for item in normalized["artifacts"]
                            ],
                        }
                        if normalized.get("review") is not None:
                            safe_claim["review"] = _redact_value(
                                normalized["review"], parent_environment
                            )
                        claim_path = result_root / "claim-source.json"
                        claim_path.write_text(
                            json.dumps(safe_claim, ensure_ascii=False, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        self.store.file_claim(
                            task_id,
                            claim_path,
                            reservation_seconds=reservation,
                        )
                        transcript["candidate_head"] = candidate_head
                        transcript["artifacts"] = safe_claim["artifacts"]
                        exit_class = "success"
        except FileNotFoundError as error:
            exit_class = "infra"
            transcript["error"] = f"cannot launch worker CLI: {error}"
        except (OSError, subprocess.SubprocessError, StoreError, ValueError) as error:
            exit_class = failure_class
            transcript["error"] = str(error)

        if exit_class != "success" and failure_reason is None:
            failure_reason = _redact(
                str(transcript.get("error", exit_class)), parent_environment
            )

        transcript["exit_class"] = exit_class
        transcript_path.write_text(
            json.dumps(
                _redact_value(transcript, parent_environment),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        retained_last = _redact(raw_last_message, parent_environment)
        if not retained_last:
            retained_last = _redact(
                json.dumps(
                    {"exit_class": exit_class, "error": transcript.get("error", "")},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                parent_environment,
            )
        last_message_path.write_text(retained_last.rstrip() + "\n", encoding="utf-8")
        return DispatchResult(
            exit_class,
            transcript_path,
            last_message_path,
            self.binding.label,
            failure_reason,
        )

    @abstractmethod
    def command(
        self,
        *,
        checkout: Path,
        schema_path: Path,
        raw_last_path: Path,
        sandbox: str,
    ) -> list[str]:
        """Return the complete vendor invocation for one isolated checkout."""

    @abstractmethod
    def extract_claim(
        self,
        *,
        stdout: str,
        raw_last_path: Path,
    ) -> tuple[Mapping[str, Any], str]:
        """Extract the typed final claim and its raw retained-message form."""


def _run_process(
    command: Sequence[str],
    *,
    prompt: str,
    cwd: Path,
    environment: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout: float,
) -> tuple[int, bool]:
    worker_environment = dict(environment)
    worker_directory = str(cwd.resolve())
    worker_environment["PWD"] = worker_directory
    worker_environment["OLDPWD"] = worker_directory
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=worker_environment,
            stdin=subprocess.PIPE,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )
        try:
            process.communicate(prompt.encode("utf-8"), timeout=timeout)
            return_code = process.returncode
            _terminate_process_group(process)
            return return_code, False
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            return process.returncode, True


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and _process_group_exists(process_group):
        time.sleep(0.01)
    if _process_group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.wait(timeout=5)


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except (PermissionError, ProcessLookupError):
        return False
    return True


def _publish_candidate(
    product: Path,
    checkout: Path,
    base_head: str,
    candidate_head: str,
    *,
    timeout: float,
) -> None:
    if _git(product, ("rev-parse", "HEAD"), timeout=timeout).strip() != base_head:
        raise ValueError("product HEAD changed while isolated worker ran")
    if _git(product, ("status", "--porcelain"), timeout=timeout).strip():
        raise ValueError("product worktree changed while isolated worker ran")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_head, candidate_head],
        cwd=checkout,
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if ancestor.returncode != 0:
        raise ValueError("claimed commit does not descend from dispatch base")
    _git(product, ("fetch", "--quiet", str(checkout), candidate_head), timeout=timeout)
    _git(product, ("merge", "--quiet", "--ff-only", "FETCH_HEAD"), timeout=timeout)
    if _git(product, ("rev-parse", "HEAD"), timeout=timeout).strip() != candidate_head:
        raise ValueError("product did not fast-forward to claimed commit")


def _reject_candidate_secrets(
    checkout: Path,
    base_head: str,
    candidate_head: str,
    environment: Mapping[str, str],
    *,
    timeout: float,
) -> None:
    commits = _git(
        checkout,
        ("rev-list", f"{base_head}..{candidate_head}"),
        timeout=timeout,
    ).splitlines()
    for commit in commits:
        changed_paths = _git_bytes(
            checkout,
            (
                "diff-tree",
                "--root",
                "-m",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                commit,
            ),
            timeout=timeout,
        ).split(b"\0")
        if any(
            path and _payload_contains_secret(path, environment)
            for path in changed_paths
        ):
            raise ValueError("candidate contains a sensitive value in a path")
    introduced_objects = _git_bytes(
        checkout,
        (
            "rev-list",
            "--objects",
            "--no-object-names",
            f"{base_head}..{candidate_head}",
        ),
        timeout=timeout,
    )
    for row in introduced_objects.splitlines():
        if not row:
            continue
        object_id = row.decode("ascii")
        object_type = _git(
            checkout,
            ("cat-file", "-t", object_id),
            timeout=timeout,
        ).strip()
        if object_type not in {"blob", "commit"}:
            continue
        payload = _git_bytes(
            checkout,
            ("cat-file", object_type, object_id),
            timeout=timeout,
        )
        if _payload_contains_secret(payload, environment):
            location = "commit metadata" if object_type == "commit" else "history"
            raise ValueError(f"candidate contains a sensitive value in {location}")


def _normalize_claim(
    value: Mapping[str, Any], *, require_review: bool = False
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("structured claim must be an object")
    if set(value) not in (
        {"claim", "candidate_head", "artifacts", "reason"},
        {"claim", "candidate_head", "artifacts", "reason", "review"},
    ):
        raise ValueError("structured claim has unexpected fields")
    if value["claim"] == "ambiguity":
        reason = value["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("structured ambiguity reason must be non-empty text")
        if (
            value["candidate_head"] is not None
            or value["artifacts"] != []
            or value.get("review") is not None
        ):
            raise ValueError(
                "structured ambiguity cannot name a candidate, artifacts, or findings"
            )
        return {"claim": "ambiguity", "reason": reason}
    if value["claim"] != "passes":
        raise ValueError("structured claim must say passes")
    if value["reason"] is not None:
        raise ValueError("passing structured claim cannot include a reason")
    candidate_head = value["candidate_head"]
    if not isinstance(candidate_head, str) or not re.fullmatch(
        r"(?:[0-9a-f]{40}|[0-9a-f]{64})", candidate_head
    ):
        raise ValueError("structured claim candidate_head is invalid")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list) or any(
        not isinstance(item, str) or not item for item in artifacts
    ):
        raise ValueError("structured claim artifacts must be non-empty strings")
    for artifact in artifacts:
        path = Path(artifact)
        if (
            path.is_absolute()
            or ".." in path.parts
            or any(part.casefold() == ".scaffolding" for part in path.parts)
        ):
            raise ValueError("structured claim artifacts must be safe relative paths")
    review = value.get("review")
    if require_review and review is None:
        raise ValueError("reviewer structured claim must contain findings")
    if not require_review and review is not None:
        raise ValueError("only reviewer structured claims may contain findings")
    normalized = {
        "claim": "passes",
        "candidate_head": candidate_head,
        "artifacts": list(artifacts),
        "reason": None,
    }
    if review is not None:
        normalized["review"] = _normalize_review(review)
    return normalized


def _normalize_review(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"findings"}:
        raise ValueError("structured review must contain only findings")
    findings = value["findings"]
    if not isinstance(findings, list):
        raise ValueError("structured review findings must be a list")
    normalized: list[dict[str, str]] = []
    ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {
            "id",
            "severity",
            "summary",
            "evidence",
        }:
            raise ValueError("structured review finding has the wrong fields")
        finding_id = validate_task_id(finding["id"])
        if finding_id in ids:
            raise ValueError("structured review finding ids must be unique")
        if finding["severity"] not in {"low", "medium", "high", "critical"}:
            raise ValueError("structured review severity is outside the closed enum")
        for field in ("summary", "evidence"):
            if not isinstance(finding[field], str) or not finding[field]:
                raise ValueError(f"structured review {field} must be non-empty text")
        ids.add(finding_id)
        normalized.append(dict(finding))
    return {"findings": normalized}


def _git(root: Path, arguments: Sequence[str], *, timeout: float) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _git_bytes(root: Path, arguments: Sequence[str], *, timeout: float) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _read_output(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def _redact(value: str, environment: Mapping[str, str]) -> str:
    redacted = value
    for secret in _sensitive_values(environment):
        redacted = redacted.replace(secret, "<redacted>")
    for pattern in _KNOWN_SECRET_PATTERNS:
        redacted = pattern.sub(
            lambda match: (
                f"{match.group(1)}<redacted>" if match.lastindex else "<redacted>"
            ),
            redacted,
        )
    return redacted


def _payload_contains_secret(payload: bytes, environment: Mapping[str, str]) -> bool:
    for secret in _sensitive_values(environment):
        if secret.encode("utf-8", errors="ignore") in payload:
            return True
    text = payload.decode("utf-8", errors="replace")
    return any(pattern.search(text) for pattern in _KNOWN_SECRET_PATTERNS)


def _sensitive_values(environment: Mapping[str, str]) -> list[str]:
    return sorted(
        {
            secret
            for name, secret in environment.items()
            if _SECRET_ENV_NAME.search(name) and len(secret) >= 6
        },
        key=len,
        reverse=True,
    )


def _worker_environment(
    environment: Mapping[str, str], allowed_secret_names: frozenset[str]
) -> dict[str, str]:
    return {
        name: value
        for name, value in environment.items()
        if not _SECRET_ENV_NAME.search(name) or name in allowed_secret_names
    }


def _redact_value(value: Any, environment: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _redact(value, environment)
    if isinstance(value, list):
        return [_redact_value(item, environment) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_value(item, environment) for key, item in value.items()
        }
    return value


def _required_text(value: Mapping[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError(f"{field} must be a non-empty string")
    return candidate


def _required_positive_number(value: Mapping[str, Any], field: str) -> float:
    candidate = value.get(field)
    if (
        isinstance(candidate, bool)
        or not isinstance(candidate, (int, float))
        or candidate <= 0
    ):
        raise ValueError(f"{field} must be positive")
    return float(candidate)

"""The Delegate command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from . import SCHEMA_VERSION
from .command import build, payload
from .roster import DelegateError, Roster


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delegate", description="Resolve and diagnose agent staffing.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("resolve", help="resolve a role to a mind and fallback command")
    command.add_argument("role")
    command.add_argument("--effort")
    command.add_argument("--json", action="store_true", help="print stable machine-readable output")
    command.set_defaults(handler=cmd_resolve)

    command = subparsers.add_parser("doctor", help="check roster and command shape locally")
    command.add_argument("--role")
    command.add_argument("--effort")
    command.add_argument("--json", action="store_true", help="print stable machine-readable output")
    command.set_defaults(handler=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except DelegateError as error:
        if getattr(args, "json", False):
            print(json.dumps(error_payload(error), sort_keys=True))
        else:
            print(f"delegate: {error}", file=sys.stderr)
            print(f"Recovery: {error.recovery}", file=sys.stderr)
        return 1


def cmd_resolve(args: argparse.Namespace) -> int:
    binding = Roster().resolve(args.role, args.effort)
    result = {"schema_version": SCHEMA_VERSION, "ok": True, "binding": payload(binding)}
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        command = build(binding)
        mind = result["binding"]["mind"]
        print(f"{binding.role}: {mind['family']}/{mind['model']}/{mind['effort'] or 'default'}")
        print("Fallback argv: " + json.dumps(command))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    if args.effort is not None and args.role is None:
        raise DelegateError(
            "invalid_roster",
            "--effort requires --role",
            "Name the role whose effort should be checked.",
        )
    roster = Roster()
    roles = (args.role,) if args.role else roster.roles
    checks: list[dict[str, object]] = []
    for role in roles:
        try:
            binding = roster.resolve(role, args.effort)
            command = build(binding)
            executable = shutil.which(binding.cli)
            if executable is None and Path(binding.cli).is_file() and os.access(binding.cli, os.X_OK):
                executable = str(Path(binding.cli).resolve())
            if executable is None:
                checks.append(
                    {
                        "role": role,
                        "ok": False,
                        "code": "missing_executable",
                        "message": f"{binding.cli!r} is not executable on PATH",
                        "recovery": f"Install {binding.cli!r} or correct the role's cli in the roster.",
                    }
                )
            else:
                checks.append(
                    {
                        "role": role,
                        "ok": True,
                        "executable": executable,
                        "command": command,
                        "mind": {"family": binding.family, "model": binding.model, "effort": binding.effort},
                    }
                )
        except DelegateError as error:
            checks.append(
                {
                    "role": role,
                    "ok": False,
                    "code": error.code,
                    "message": str(error),
                    "recovery": error.recovery,
                }
            )
    ok = all(bool(check["ok"]) for check in checks)
    result: dict[str, object] = {"schema_version": SCHEMA_VERSION, "ok": ok, "checks": checks}
    if not ok:
        result["error"] = {
            "code": "doctor_failed",
            "message": f"{sum(not bool(check['ok']) for check in checks)} delegate check(s) failed",
            "recovery": "Apply each failed check's recovery action, then run delegate doctor again.",
        }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for check in checks:
            mark = "ok" if check["ok"] else "FAIL"
            detail = check.get("executable") or check.get("message")
            print(f"{mark:4} {check['role']}: {detail}")
        if not ok:
            print("Recovery: apply the failed check's action, then run delegate doctor again.", file=sys.stderr)
    return 0 if ok else 1


def error_payload(error: DelegateError) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "error": {"code": error.code, "message": str(error), "recovery": error.recovery},
    }


if __name__ == "__main__":
    raise SystemExit(main())

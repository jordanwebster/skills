"""Command-line interface for the Intake skill's deterministic boundary."""

from __future__ import annotations

import argparse
import json
import sys

from . import SCHEMA_VERSION
from .contract import ContractError, finalize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="intake", description="Finalize a confirmed acceptance contract.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("finalize", help="validate a confirmed contract and record its receipt")
    command.add_argument("contract")
    command.add_argument("--json", action="store_true", help="print stable machine-readable output")
    command.set_defaults(handler=cmd_finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ContractError as error:
        if getattr(args, "json", False):
            print(json.dumps(error_payload(error), sort_keys=True))
        else:
            print(f"intake: {error}", file=sys.stderr)
            print(f"Recovery: {error.recovery}", file=sys.stderr)
        return 1


def cmd_finalize(args: argparse.Namespace) -> int:
    contract, receipt_path, receipt = finalize(args.contract)
    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "contract": str(contract.path),
        "receipt": str(receipt_path),
        **receipt,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"Acceptance confirmed: {contract.path}")
        print(f"Receipt: {receipt_path}")
        print(f"Digest: {contract.digest}")
    return 0


def error_payload(error: ContractError) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "error": {"code": error.code, "message": str(error), "recovery": error.recovery},
    }


if __name__ == "__main__":
    raise SystemExit(main())


"""Command-line entry point for the scaffold framework."""

from __future__ import annotations

import argparse

from . import __version__


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="scaffold",
        description="Run deterministic, file-backed build flights.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args()
    parser.error("no commands are implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())

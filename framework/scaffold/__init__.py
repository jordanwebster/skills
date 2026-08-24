"""Deterministic, file-backed build loop framework."""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    raise RuntimeError("scaffold requires Python 3.11 or newer")

__version__ = "0.0.0"

"""Dispatch adapters; vendor knowledge is confined to this package."""

from .base import DispatchResult
from .fake import FakeAdapter

__all__ = ["DispatchResult", "FakeAdapter"]

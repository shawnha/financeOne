"""Financial file parsers."""

from .base import ParsedTransaction
from .registry import detect_parser

__all__ = ["detect_parser", "ParsedTransaction"]

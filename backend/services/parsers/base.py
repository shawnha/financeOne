"""Base parser interface for financial file uploads."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ParsedTransaction:
    date: date
    amount: float
    currency: str
    type: str  # 'in' or 'out'
    description: str
    counterparty: str
    source_type: str
    member_name: Optional[str] = None
    is_check_card: bool = False  # for dedup marking


class BaseParser(ABC):
    """Abstract base for all file parsers."""

    @abstractmethod
    def detect(self, file_bytes: bytes, filename: str) -> bool:
        """Return True if this parser can handle the given file."""
        ...

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedTransaction]:
        """Parse the file and return a list of ParsedTransaction."""
        ...

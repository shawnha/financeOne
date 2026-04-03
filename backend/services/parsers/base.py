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
    card_number: Optional[str] = None  # 카드번호 (마스킹)
    is_check_card: bool = False  # for dedup marking
    is_cancel: bool = False  # 취소 건 (환불로 INSERT)
    raw_data: Optional[dict] = None  # 원본 Excel 행 데이터
    row_number: Optional[int] = None  # Excel 행 번호
    balance_after: Optional[float] = None  # 거래후잔액 (은행만)


@dataclass
class ParseResult:
    """파서 결과 — 거래 목록 + 메타데이터."""
    transactions: list[ParsedTransaction]
    opening_balance: Optional[float] = None  # 첫 행 잔액
    closing_balance: Optional[float] = None  # 마지막 행 잔액
    balance_date: Optional[date] = None  # 잔액 기준 날짜


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

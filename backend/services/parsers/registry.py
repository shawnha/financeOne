"""Parser registry -- auto-detect file type and return appropriate parser."""

from .base import BaseParser
from .lotte_card import LotteCardParser
from .woori_card import WooriCardParser
from .woori_bank import WooriBankParser
from .csv_parser import CSVParser


def detect_parser(file_bytes: bytes, filename: str) -> BaseParser | None:
    """Try each parser's detect() method and return the first match."""
    for parser in [LotteCardParser(), WooriCardParser(), WooriBankParser(), CSVParser()]:
        if parser.detect(file_bytes, filename):
            return parser
    return None

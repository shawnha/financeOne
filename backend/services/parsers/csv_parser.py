"""CSV parser -- migrated from upload.py."""

import csv
import io
from datetime import date
from typing import Optional

from .base import BaseParser, ParsedTransaction
from .utils import parse_date, parse_amount


class CSVParser(BaseParser):
    """Parse generic CSV transaction files."""

    def detect(self, file_bytes: bytes, filename: str) -> bool:
        return filename.lower().endswith(".csv")

    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedTransaction]:
        text = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        results: list[ParsedTransaction] = []
        for row in reader:
            d = parse_date(row.get("date", "").strip())
            amt = parse_amount(row.get("amount", "").strip())
            if d is None or amt is None:
                continue

            results.append(ParsedTransaction(
                date=d,
                amount=abs(amt),
                currency=row.get("currency", "KRW").strip() or "KRW",
                type=row.get("type", "").strip(),
                description=row.get("description", "").strip(),
                counterparty=row.get("counterparty", "").strip(),
                source_type=row.get("source_type", "csv_upload").strip() or "csv_upload",
            ))

        return results

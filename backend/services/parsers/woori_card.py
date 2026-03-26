"""우리카드 .xls parser."""

import io
import logging
import re
import xlrd
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

from .base import BaseParser, ParsedTransaction
from .utils import parse_amount


class WooriCardParser(BaseParser):
    """Parse 우리카드 승인 상세내역 .xls files."""

    def detect(self, file_bytes: bytes, filename: str) -> bool:
        if not filename.lower().endswith(".xls"):
            return False
        try:
            wb = xlrd.open_workbook(file_contents=file_bytes)
            sheet = wb.sheet_by_index(0)
            # Look for "승인 상세내역" in rows 1-17
            for r in range(min(18, sheet.nrows)):
                for c in range(min(5, sheet.ncols)):
                    val = str(sheet.cell_value(r, c)).strip()
                    if "승인 상세내역" in val or "승인상세내역" in val:
                        return True
            return False
        except Exception:
            return False

    def _extract_year(self, sheet: xlrd.sheet.Sheet) -> Optional[int]:
        """Extract year from metadata rows (row 2 typically has period)."""
        for r in range(min(18, sheet.nrows)):
            for c in range(sheet.ncols):
                val = str(sheet.cell_value(r, c)).strip()
                # Pattern: 2026.01.01 ~ 2026.01.31
                match = re.search(r"(\d{4})\.\d{2}\.\d{2}", val)
                if match:
                    return int(match.group(1))
        return None

    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedTransaction]:
        wb = xlrd.open_workbook(file_contents=file_bytes)
        sheet = wb.sheet_by_index(0)

        year = self._extract_year(sheet)
        if year is None:
            # Try to get year from filename
            match = re.search(r"(\d{4})", filename)
            year = int(match.group(1)) if match else date.today().year

        results: list[ParsedTransaction] = []

        # Data starts at row 19 (0-indexed), row 18 = headers
        for row_idx in range(19, sheet.nrows):
            try:
                # Col 18: 접수/취소
                cancel_flag = str(sheet.cell_value(row_idx, 18)).strip()
                is_cancel = cancel_flag == "취소"

                # Col 0: 이용일자 MM.DD HH:MM (no year)
                date_str = str(sheet.cell_value(row_idx, 0)).strip()
                if not date_str:
                    continue
                # Extract MM.DD from "MM.DD HH:MM"
                date_match = re.match(r"(\d{1,2})\.(\d{1,2})", date_str)
                if not date_match:
                    continue
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                tx_date = date(year, month, day)

                # Col 7: 이용가맹점명
                counterparty = str(sheet.cell_value(row_idx, 7)).strip()

                # Col 15: 승인금액
                raw_amount = sheet.cell_value(row_idx, 15)
                amount = parse_amount(str(raw_amount))
                if amount is None or amount == 0:
                    continue

                # Col 11: 매출구분 — check for 체크계좌
                sale_type = str(sheet.cell_value(row_idx, 11)).strip()
                is_check_card = sale_type == "체크계좌"

                results.append(ParsedTransaction(
                    date=tx_date,
                    amount=abs(amount),
                    currency="KRW",
                    type="in" if is_cancel else "out",
                    description=f"우리카드 {counterparty}" + (" (취소)" if is_cancel else ""),
                    counterparty=counterparty,
                    source_type="woori_card",
                    is_check_card=is_check_card,
                    is_cancel=is_cancel,
                ))
            except Exception as e:
                logger.warning("Parse row failed: %s", e)
                continue

        return results

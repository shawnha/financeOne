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

    def _find_header_row(self, sheet) -> int:
        """헤더 행 찾기 — '이용일자'가 있는 행."""
        for r in range(min(25, sheet.nrows)):
            if str(sheet.cell_value(r, 0)).strip() == "이용일자":
                return r
        return 18  # fallback

    def _map_columns(self, sheet, header_row: int) -> dict:
        """헤더 텍스트로 컬럼 인덱스를 동적 매핑."""
        col_map = {}
        for c in range(sheet.ncols):
            val = str(sheet.cell_value(header_row, c)).strip().replace("\n", "")
            if "이용일자" in val:
                col_map["date"] = c
            elif "이용가맹점" in val:
                col_map["counterparty"] = c
            elif "승인금액" in val and "USD" not in val and "해외" not in val:
                # "승인금액 /취소(원)" or "승인금액(취소)" — KRW 금액
                # "승인금액(USD)" 제외
                col_map["amount"] = c
            elif "매출구분" in val:
                col_map["sale_type"] = c
            elif "접수" in val and ("취소" in val or "구분" in val):
                col_map["status"] = c
        # Defaults for missing columns
        col_map.setdefault("date", 0)
        col_map.setdefault("counterparty", 7)
        col_map.setdefault("amount", 15)
        col_map.setdefault("sale_type", 11)
        col_map.setdefault("status", 18)
        return col_map

    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedTransaction]:
        wb = xlrd.open_workbook(file_contents=file_bytes)
        sheet = wb.sheet_by_index(0)

        year = self._extract_year(sheet)
        if year is None:
            # Try to get year from filename
            match = re.search(r"(\d{4})", filename)
            year = int(match.group(1)) if match else date.today().year

        header_row = self._find_header_row(sheet)
        col = self._map_columns(sheet, header_row)
        data_start = header_row + 1

        results: list[ParsedTransaction] = []

        for row_idx in range(data_start, sheet.nrows):
            try:
                # 접수/취소
                cancel_flag = str(sheet.cell_value(row_idx, col["status"])).strip()
                is_cancel = cancel_flag == "취소"

                # 이용일자 MM.DD HH:MM (no year)
                date_str = str(sheet.cell_value(row_idx, col["date"])).strip()
                if not date_str:
                    continue
                date_match = re.match(r"(\d{1,2})\.(\d{1,2})", date_str)
                if not date_match:
                    continue
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                tx_date = date(year, month, day)

                # 이용가맹점명
                counterparty = str(sheet.cell_value(row_idx, col["counterparty"])).strip()

                # 승인금액
                raw_amount = sheet.cell_value(row_idx, col["amount"])
                amount = parse_amount(str(raw_amount))
                if amount is None or amount == 0:
                    continue

                # 매출구분 — check for 체크계좌
                sale_type = str(sheet.cell_value(row_idx, col["sale_type"])).strip()
                is_check_card = sale_type == "체크계좌"

                results.append(ParsedTransaction(
                    date=tx_date,
                    amount=abs(amount),
                    currency="KRW",
                    type="in" if is_cancel else "out",
                    description=counterparty + (" (취소)" if is_cancel else ""),
                    counterparty=counterparty,
                    source_type="woori_card",
                    is_check_card=is_check_card,
                    is_cancel=is_cancel,
                ))
            except Exception as e:
                logger.warning("Parse row failed (row %d): %s", row_idx, e)
                continue

        return results

"""롯데카드 .xls parser."""

import io
import xlrd
from datetime import date
from typing import Optional

from .base import BaseParser, ParsedTransaction
from .utils import parse_amount


class LotteCardParser(BaseParser):
    """Parse 롯데카드 카드승인내역 .xls files."""

    def detect(self, file_bytes: bytes, filename: str) -> bool:
        if not filename.lower().endswith(".xls"):
            return False
        try:
            wb = xlrd.open_workbook(file_contents=file_bytes)
            sheet = wb.sheet_by_index(0)
            if sheet.nrows < 2:
                return False
            # Row 0 should contain "카드승인내역"
            cell_val = str(sheet.cell_value(0, 0)).strip()
            return "카드승인내역" in cell_val
        except Exception:
            return False

    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedTransaction]:
        wb = xlrd.open_workbook(file_contents=file_bytes)
        sheet = wb.sheet_by_index(0)

        results: list[ParsedTransaction] = []

        # Data rows start at row 2 (row 0 = title, row 1 = headers)
        for row_idx in range(2, sheet.nrows):
            try:
                # Col 11: 취소여부 — skip cancelled
                cancel_flag = str(sheet.cell_value(row_idx, 11)).strip()
                if cancel_flag == "Y":
                    continue

                # Col 5: 승인일자 YYYY.MM.DD
                date_str = str(sheet.cell_value(row_idx, 5)).strip()
                if not date_str:
                    continue
                parts = date_str.split(".")
                if len(parts) != 3:
                    continue
                tx_date = date(int(parts[0]), int(parts[1]), int(parts[2]))

                # Col 3: 회원명
                member_name = str(sheet.cell_value(row_idx, 3)).strip() or None

                # Col 7: 가맹점명 (counterparty)
                counterparty = str(sheet.cell_value(row_idx, 7)).strip()

                # Col 8: 승인금액(원화)
                raw_amount = sheet.cell_value(row_idx, 8)
                amount = parse_amount(str(raw_amount))
                if amount is None or amount == 0:
                    continue

                # Col 15: 화폐단위
                currency = str(sheet.cell_value(row_idx, 15)).strip() or "KRW"

                results.append(ParsedTransaction(
                    date=tx_date,
                    amount=abs(amount),
                    currency=currency,
                    type="out",
                    description=f"롯데카드 {counterparty}",
                    counterparty=counterparty,
                    source_type="lotte_card",
                    member_name=member_name,
                ))
            except Exception:
                # Skip malformed rows
                continue

        return results

"""롯데카드 .xls parser."""

import io
import logging
import xlrd
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

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
                # Col 11: 취소여부
                cancel_flag = str(sheet.cell_value(row_idx, 11)).strip()
                is_cancel = cancel_flag == "Y"

                # Col 5: 승인일자 YYYY.MM.DD
                date_str = str(sheet.cell_value(row_idx, 5)).strip()
                if not date_str:
                    continue
                parts = date_str.split(".")
                if len(parts) != 3:
                    continue
                tx_date = date(int(parts[0]), int(parts[1]), int(parts[2]))

                # Col 2: 카드번호
                raw_card = str(sheet.cell_value(row_idx, 2)).strip()
                card_number = raw_card if raw_card and raw_card != "0.0" else None
                # Mask card number: show last 4 digits only
                if card_number and len(card_number) >= 4:
                    card_number = f"****{card_number[-4:]}"

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

                # 원본 행 보존
                raw = {}
                for ci in range(sheet.ncols):
                    val = sheet.cell_value(row_idx, ci)
                    if val is not None and str(val).strip():
                        raw[f"col_{ci}"] = str(val).strip()

                results.append(ParsedTransaction(
                    date=tx_date,
                    amount=abs(amount),
                    currency=currency,
                    type="in" if is_cancel else "out",
                    description=counterparty + (" (취소)" if is_cancel else ""),
                    counterparty=counterparty,
                    source_type="lotte_card",
                    member_name=member_name,
                    card_number=card_number,
                    is_cancel=is_cancel,
                    raw_data=raw,
                    row_number=row_idx + 1,
                ))
            except Exception as e:
                # Skip malformed rows
                logger.warning("Parse row failed: %s", e)
                continue

        return results

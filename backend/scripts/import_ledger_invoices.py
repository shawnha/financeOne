"""회계법인 계정별원장 .xls → invoices 테이블 자동 import.

원장의 외상매출금 / 외상매입금 시트의 차변 행 = 발생 (invoice 새로 만듦).
대변 행 = 회수/결제 (이미 transactions 에 입금 거래로 들어 있으면 매칭, 아니면 skip).

전기이월 (r4) 은 import_opening_balances.py 가 별도 처리 — 이 스크립트는 무시.

사용:
    python -m backend.scripts.import_ledger_invoices \
        --entity 2 --file '/path/to/계정별원장.xls' --dry-run
    python -m backend.scripts.import_ledger_invoices \
        --entity 2 --file '/path/to/계정별원장.xls' --commit
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from decimal import Decimal

import psycopg2
import xlrd
from dotenv import load_dotenv

load_dotenv()

from backend.services.invoice_service import create_invoice


# 시트 이름 → (direction, std_code)
LEDGER_INVOICE_SHEETS = {
    "1_외상매출금(10800)": ("sales", "41200"),    # 서비스매출 default — 추후 적요로 분기
    "10_외상매입금(25100)": ("purchase", "82900"), # 사무용품비 default
    # 미수금/미지급비용 등은 별도 처리 (invoice 외 자산/부채)
}


def _parse_date(date_str: str, year: int) -> date | None:
    """원장 날짜 'MM-DD' → date(year, MM, DD)."""
    s = str(date_str).strip()
    if not s or "-" not in s:
        return None
    try:
        m, d = s.split("-")
        return date(year, int(m), int(d))
    except (ValueError, IndexError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, required=True)
    parser.add_argument("--file", required=True, help="계정별원장 .xls 경로")
    parser.add_argument("--year", type=int, required=True, help="원장 회계연도")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    wb = xlrd.open_workbook(args.file)

    print(f"\n=== 원장 invoice import (entity={args.entity}, year={args.year}) ===")
    print(f"  파일: {args.file}")
    print(f"  모드: {'DRY-RUN' if args.dry_run else 'COMMIT'}\n")

    conn = None
    if args.commit:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")
        # std_code → standard_account_id
        cur.execute("SELECT code, id FROM standard_accounts")
        code_to_id = dict(cur.fetchall())
        cur.close()

    total_created = 0
    total_skipped = 0

    for sheet_name in wb.sheet_names():
        if sheet_name not in LEDGER_INVOICE_SHEETS:
            continue
        direction, default_code = LEDGER_INVOICE_SHEETS[sheet_name]
        sheet = wb.sheet_by_name(sheet_name)
        print(f"--- {sheet_name} (direction={direction}, default_code={default_code}) ---")

        # r0~r3 헤더, r4 = 전기이월. r5~ 가 1월 거래.
        # column: 0=날짜, 1=적요, 2=코드, 3=거래처, 4=차변, 5=대변, 6=잔액
        invoice_count = 0
        skip_count = 0
        for r in range(5, sheet.nrows):
            date_str = str(sheet.cell_value(r, 0)).strip()
            # 월계/누계 행은 적요란 이 비어있고 차/대변 합산 — 'r1' 처리 X
            note = str(sheet.cell_value(r, 1)).strip()
            if "[ 월" in note or "[ 누" in note:
                continue
            if not date_str:
                continue
            counterparty = str(sheet.cell_value(r, 3)).strip()
            debit = sheet.cell_value(r, 4)
            credit = sheet.cell_value(r, 5)
            try:
                debit_v = Decimal(str(debit or 0))
                credit_v = Decimal(str(credit or 0))
            except Exception:
                continue

            issue_d = _parse_date(date_str, args.year)
            if not issue_d:
                continue

            # 발생 행: 차변 (sales), 대변 (purchase)
            if direction == "sales" and debit_v > 0:
                amount = debit_v
            elif direction == "purchase" and credit_v > 0:
                amount = credit_v
            else:
                # 회수/결제 행 — invoice 발행 X. 매칭은 별도 단계 (P3-7).
                skip_count += 1
                continue

            invoice_count += 1
            print(f"  [{direction}] {issue_d} {counterparty[:25]:25s} {float(amount):>12,.0f}  적요: {note[:30]}")

            if args.commit:
                try:
                    std_id = code_to_id.get(default_code)
                    create_invoice(
                        conn,
                        entity_id=args.entity,
                        direction=direction,
                        counterparty=counterparty or "(미상)",
                        issue_date=issue_d,
                        amount=amount,
                        # VAT 는 매출원장에는 별도 분리되지 않음 — 합산된 값.
                        # invoice 의 vat=0, total=amount 처리. 후속 부가세 정리 필요시 별도.
                        vat=Decimal("0"),
                        total=amount,
                        standard_account_id=std_id,
                        description=note[:200] if note else None,
                    )
                except Exception as e:
                    print(f"    ✗ 실패: {e}")

        print(f"  → 발생 {invoice_count} 건, skip(회수/결제) {skip_count} 건\n")
        total_created += invoice_count
        total_skipped += skip_count

    if conn:
        conn.commit()
        conn.close()

    print(f"=== 완료: 생성 {total_created} / skip {total_skipped} ===")
    if args.dry_run:
        print("  --commit 으로 실행하면 invoices INSERT (자동 발생주의 분개 포함).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""회계법인 계정별원장 .xls ↔ FinanceOne transactions 대조 리포트.

사용:
  python3 -m backend.scripts.reconcile_ledger \
    --ledger "/Users/admin/Documents/HanahOneAll/Finance/1. 가결산자료/26년/1월/계정별원장_(주)한아원코리아.xls" \
    --entity 2 --year 2026 --month 1

회계법인 원장의 각 계정(예: 80200 직원급여)에서 월별 차변/대변 합계를 뽑고,
FinanceOne의 같은 기간 transactions를 standard_account.code 기준으로 집계해 대조.

결과:
- 계정별 diff 테이블 (차변/대변/합계)
- 회계법인 있지만 FinanceOne에 없는 계정 → 누락
- FinanceOne 있지만 원장에 없는 계정 → 분류 오류 가능
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from decimal import Decimal

import psycopg2
import xlrd
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
load_dotenv()

SHEET_RE = re.compile(r"(\d+)_(.+?)\((\d+)\)")


def parse_ledger(path: str) -> dict:
    """각 시트에서 {acct_code: {name, debit, credit}} 추출."""
    wb = xlrd.open_workbook(path)
    out: dict[str, dict] = {}
    for idx in range(wb.nsheets):
        name = wb.sheet_names()[idx]
        m = SHEET_RE.match(name)
        if not m:
            continue
        acct_name, acct_code = m.group(2), m.group(3)
        sh = wb.sheet_by_index(idx)
        debit = Decimal(0)
        credit = Decimal(0)
        for r in range(4, sh.nrows):
            desc = str(sh.cell_value(r, 1)).strip() if sh.ncols > 1 else ""
            if desc in ("", "[월 계]", "[누   계]", "[누 계]"):
                continue
            if "이월" in desc:
                continue
            try:
                d = Decimal(str(sh.cell_value(r, 4))) if sh.cell_value(r, 4) not in ("", None) else Decimal(0)
            except Exception:
                d = Decimal(0)
            try:
                c = Decimal(str(sh.cell_value(r, 5))) if sh.cell_value(r, 5) not in ("", None) else Decimal(0)
            except Exception:
                c = Decimal(0)
            debit += d
            credit += c
        out[acct_code] = {"name": acct_name, "debit": debit, "credit": credit}
    return out


def fetch_financeone_by_code(conn, entity_id: int, year: int, month: int) -> dict:
    """FinanceOne의 해당 월 거래를 standard_account.code별 집계.
    {code: {name, in_sum, out_sum, count}}
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    start = f"{year}-{month:02d}-01"
    end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
    cur.execute(
        """
        SELECT sa.code, sa.name,
               SUM(CASE WHEN t.type='in'  AND NOT t.is_cancel THEN t.amount ELSE 0 END) AS in_sum,
               SUM(CASE WHEN t.type='out' AND NOT t.is_cancel THEN t.amount ELSE 0 END) AS out_sum,
               SUM(CASE WHEN t.type='in'  AND     t.is_cancel THEN t.amount ELSE 0 END) AS cancel_in,
               SUM(CASE WHEN t.type='out' AND     t.is_cancel THEN t.amount ELSE 0 END) AS cancel_out,
               COUNT(*) AS cnt
        FROM transactions t
        JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE t.entity_id = %s
          AND t.date >= %s::date AND t.date < %s::date
        GROUP BY sa.code, sa.name
        """,
        [entity_id, start, end],
    )
    out = {}
    for r in cur.fetchall():
        code, name, in_sum, out_sum, cin, cout, cnt = r
        # net 기준: 승인(type=out) - 취소(type=in + is_cancel) = 실제 지출
        #          또는 반대로 수익은 in - cancel
        out[code] = {
            "name": name,
            "in": Decimal(str(in_sum or 0)),
            "out": Decimal(str(out_sum or 0)),
            "cancel_in": Decimal(str(cin or 0)),
            "cancel_out": Decimal(str(cout or 0)),
            "count": cnt,
        }
    cur.close()
    return out


def report(ledger: dict, fo: dict) -> None:
    all_codes = sorted(set(ledger) | set(fo), key=lambda c: (int(c) if c.isdigit() else 99999, c))

    print("=" * 100)
    print(f"{'code':<8}{'계정명':<26}{'원장차변':>14}{'원장대변':>14}"
          f"{'FO in':>14}{'FO out':>14}{'diff':>14}")
    print("=" * 100)

    missing_in_fo = []
    missing_in_ledger = []
    mismatches = []

    for code in all_codes:
        le = ledger.get(code)
        f = fo.get(code)

        le_debit = le["debit"] if le else Decimal(0)
        le_credit = le["credit"] if le else Decimal(0)
        fo_in = f["in"] if f else Decimal(0)
        fo_out = f["out"] if f else Decimal(0)

        # normal_side 판정: code 앞자리로 — 1xxxx,5-8xxxx = debit-normal, 2,3,4,9xxxx = credit-normal
        first = code[0] if code and code[0].isdigit() else "0"
        is_debit_normal = first in ("1", "5", "6", "7", "8")
        if is_debit_normal:
            le_net = le_debit - le_credit
            fo_net = fo_out - fo_in
        else:
            le_net = le_credit - le_debit
            fo_net = fo_in - fo_out

        diff = le_net - fo_net
        name = (le["name"] if le else (f["name"] if f else ""))[:24]

        mark = ""
        if not le and f and (fo_in or fo_out):
            mark = "← FO만"
            missing_in_ledger.append(code)
        elif le and not f and (le_debit or le_credit):
            mark = "← 원장만"
            missing_in_fo.append(code)
        elif diff != 0 and (le_net != 0 or fo_net != 0):
            pct = float(abs(diff) / max(abs(le_net), abs(fo_net), 1)) * 100
            if pct > 5:
                mark = f"⚠ {pct:.1f}%"
                mismatches.append((code, name, le_net, fo_net, diff))

        print(f"{code:<8}{name:<26}{int(le_debit):>14,}{int(le_credit):>14,}"
              f"{int(fo_in):>14,}{int(fo_out):>14,}{int(diff):>+14,}  {mark}")

    print()
    print(f"원장만 ({len(missing_in_fo)}건): {missing_in_fo}")
    print(f"FO만 ({len(missing_in_ledger)}건): {missing_in_ledger}")
    print(f"5% 이상 차이 ({len(mismatches)}건):")
    for c, n, le, f, d in mismatches:
        print(f"  {c} {n}: 원장 {int(le):,} ↔ FO {int(f):,} (diff {int(d):+,})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--entity", type=int, required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    args = ap.parse_args()

    ledger = parse_ledger(args.ledger)
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        fo = fetch_financeone_by_code(conn, args.entity, args.year, args.month)
    finally:
        conn.close()
    print(f"회계법인 원장 계정 {len(ledger)}개 / FinanceOne 계정 {len(fo)}개")
    report(ledger, fo)


if __name__ == "__main__":
    main()

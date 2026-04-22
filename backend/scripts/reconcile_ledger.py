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
    {code: {name, category, subcategory, in_sum, out_sum, count}}
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    start = f"{year}-{month:02d}-01"
    end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
    cur.execute(
        """
        SELECT sa.code, sa.name, sa.category, sa.subcategory,
               SUM(CASE WHEN t.type='in'  AND NOT t.is_cancel THEN t.amount ELSE 0 END) AS in_sum,
               SUM(CASE WHEN t.type='out' AND NOT t.is_cancel THEN t.amount ELSE 0 END) AS out_sum,
               SUM(CASE WHEN t.type='in'  AND     t.is_cancel THEN t.amount ELSE 0 END) AS cancel_in,
               SUM(CASE WHEN t.type='out' AND     t.is_cancel THEN t.amount ELSE 0 END) AS cancel_out,
               COUNT(*) AS cnt
        FROM transactions t
        JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE t.entity_id = %s
          AND t.date >= %s::date AND t.date < %s::date
        GROUP BY sa.code, sa.name, sa.category, sa.subcategory
        """,
        [entity_id, start, end],
    )
    out = {}
    for r in cur.fetchall():
        code, name, category, subcategory, in_sum, out_sum, cin, cout, cnt = r
        out[code] = {
            "name": name,
            "category": category,
            "subcategory": subcategory,
            "in": Decimal(str(in_sum or 0)),
            "out": Decimal(str(out_sum or 0)),
            "cancel_in": Decimal(str(cin or 0)),
            "cancel_out": Decimal(str(cout or 0)),
            "count": cnt,
        }
    cur.close()
    return out


def load_code_subcategory_map(conn) -> dict[str, tuple[str, str]]:
    """standard_accounts의 code → (category, subcategory) 매핑. 원장 쪽 bucket용."""
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    cur.execute("SELECT code, category, COALESCE(subcategory, '') FROM standard_accounts")
    m = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    cur.close()
    return m


# ── K-GAAP 공시 그룹 정의 (BS/IS 집계 로직과 동기화) ──
DISCLOSURE_GROUPS: list[tuple[str, str, list[str]]] = [
    # (카테고리, 공시 라벨, [sub_category 후보])
    ("자산", "유동자산 > 당좌자산", ["당좌자산"]),
    ("자산", "유동자산 > 재고자산", ["재고자산"]),
    ("자산", "유동자산 > 기타유동", ["유동자산"]),
    ("자산", "비유동자산 > 투자자산", ["투자자산"]),
    ("자산", "비유동자산 > 유형자산", ["유형자산"]),
    ("자산", "비유동자산 > 기타비유동", ["기타비유동", "기타비유동자산", "비유동자산"]),
    ("부채", "유동부채", ["유동부채"]),
    ("부채", "비유동부채", ["비유동부채"]),
    ("자본", "자본금", ["자본금"]),
    ("자본", "자본잉여금", ["자본잉여금"]),
    ("자본", "이익잉여금", ["이익잉여금"]),
    ("수익", "매출", ["매출", "영업수익"]),
    ("수익", "영업외수익", ["영업외수익"]),
    ("비용", "매출원가", ["매출원가"]),
    ("비용", "판매비와관리비", ["판매관리비", "판매비와관리비"]),
    ("비용", "영업외비용", ["영업외비용"]),
    ("비용", "법인세등", ["법인세비용", "법인세", "법인세등"]),
]


def aggregate_by_disclosure(
    ledger: dict, fo: dict, code_meta: dict[str, tuple[str, str]]
) -> list[dict]:
    """ledger + fo를 공시 그룹별로 집계. 매칭 안 되는 code는 '기타'."""
    buckets: dict[str, dict] = {g[1]: {
        "category": g[0], "label": g[1],
        "ledger_debit": Decimal(0), "ledger_credit": Decimal(0),
        "fo_in": Decimal(0), "fo_out": Decimal(0),
        "codes": set(),
    } for g in DISCLOSURE_GROUPS}
    buckets["기타 (미분류)"] = {
        "category": "?", "label": "기타 (미분류)",
        "ledger_debit": Decimal(0), "ledger_credit": Decimal(0),
        "fo_in": Decimal(0), "fo_out": Decimal(0),
        "codes": set(),
    }

    def find_bucket(code: str) -> str:
        meta = code_meta.get(code)
        if not meta:
            return "기타 (미분류)"
        cat, sub = meta
        for g_cat, g_label, subs in DISCLOSURE_GROUPS:
            if cat == g_cat and sub in subs:
                return g_label
        return "기타 (미분류)"

    for code, le in ledger.items():
        b = buckets[find_bucket(code)]
        b["ledger_debit"] += le["debit"]
        b["ledger_credit"] += le["credit"]
        b["codes"].add(code)

    for code, f in fo.items():
        b = buckets[find_bucket(code)]
        b["fo_in"] += f["in"]
        b["fo_out"] += f["out"]
        b["codes"].add(code)

    return list(buckets.values())


def report_disclosure(buckets: list[dict]) -> None:
    print()
    print("=" * 110)
    print("공시 그룹(K-GAAP sub_category) 단위 집계 ────────────────────────────────────")
    print("=" * 110)
    print(f"{'공시 항목':<28}{'원장차변':>14}{'원장대변':>14}{'원장순액':>14}"
          f"{'FO in':>12}{'FO out':>12}{'FO순액':>14}{'diff':>14}")
    print("-" * 110)

    order = {g[1]: i for i, g in enumerate(DISCLOSURE_GROUPS)}
    order["기타 (미분류)"] = len(DISCLOSURE_GROUPS)
    for b in sorted(buckets, key=lambda x: order.get(x["label"], 999)):
        if (b["ledger_debit"] == 0 and b["ledger_credit"] == 0 and
                b["fo_in"] == 0 and b["fo_out"] == 0):
            continue
        cat = b["category"]
        # debit-normal인 category
        if cat in ("자산", "비용", "?"):
            le_net = b["ledger_debit"] - b["ledger_credit"]
            fo_net = b["fo_out"] - b["fo_in"]
        else:
            le_net = b["ledger_credit"] - b["ledger_debit"]
            fo_net = b["fo_in"] - b["fo_out"]
        diff = le_net - fo_net
        print(f"{b['label']:<28}"
              f"{int(b['ledger_debit']):>14,}{int(b['ledger_credit']):>14,}{int(le_net):>+14,}"
              f"{int(b['fo_in']):>12,}{int(b['fo_out']):>12,}{int(fo_net):>+14,}"
              f"{int(diff):>+14,}")


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
        code_meta = load_code_subcategory_map(conn)
    finally:
        conn.close()
    print(f"회계법인 원장 계정 {len(ledger)}개 / FinanceOne 계정 {len(fo)}개")
    report(ledger, fo)
    buckets = aggregate_by_disclosure(ledger, fo, code_meta)
    report_disclosure(buckets)


if __name__ == "__main__":
    main()

"""회계법인 25년 결산자료 vs 현재 시스템 BS 잔액 비교 (P3-3 검증).

사용:
    python -m backend.scripts.verify_bs_against_ledger --entity 2 --as-of 2025-12-31

회계법인 PDF 의 BS 잔액을 hardcoded expected 로 두고, 현재 시스템의
get_all_account_balances() 결과와 코드별 비교 + 차이 % 표시.

P3-1/P3-2 변경 후 — 마이그레이션이 필요한지 판단용 진단 도구.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from backend.services.bookkeeping_engine import get_all_account_balances


# ── 회계법인 PDF 25년 12-31 한아원코리아 BS 잔액 ──
# 출처: [주식회사 한아원코리아]_25년귀속 재무제표 (2).pdf
EXPECTED_BS_HANAH_KOREA_2025 = {
    "10100": ("현금",          0),
    "10300": ("보통예금",      161_065_312),
    "10800": ("외상매출금",    246_164_180),
    "12000": ("미수금",         50_648_785),
    "13100": ("선급금",         11_892_712),  # PDF: 선급금 11.89M (선납세금 아님 — 정정)
    "13400": ("가지급금",                 0),
    "13600": ("선납세금",            40_620),
    "14600": ("상품",            35_696_395),
    "17900": ("장기대여금",               0),
    "21200": ("비품",            36_436_365),
    "21900": ("시설장치",        80_000_000),
    "25100": ("외상매입금",      54_253_934),
    "25400": ("예수금",           4_069_170),
    "26200": ("미지급비용",      42_600_887),
    "30300": ("주임종 장기차입금", 130_000_000),
    "31500": ("조건부지분인수계약부채", 550_000_000),
    "33100": ("자본금",          303_602_000),
    "34100": ("주식발행초과금",  761_393_660),
    "37800": ("미처리결손금", -1_123_775_282),
    # 합계: 자산 722,144,369 / 부채 780,923,991 / 자본 -58,779,622
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, default=2, help="entity_id (한아원코리아=2)")
    parser.add_argument("--as-of", default="2025-12-31", help="YYYY-MM-DD")
    parser.add_argument("--threshold-pct", type=float, default=5.0,
                        help="차이가 이 % 이내면 PASS (기본 5%)")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    balances = get_all_account_balances(conn, args.entity, to_date=as_of)
    seen = {b["code"]: b for b in balances if b.get("code")}

    print(f"\n=== 한아원코리아(entity={args.entity}) {as_of} 잔액 검증 ===")
    print(f"분개 잔액 != 0 계정 수: {len(balances)}")
    print(f"PDF 비교 대상: {len(EXPECTED_BS_HANAH_KOREA_2025)} 계정\n")

    pass_count = 0
    fail_count = 0
    soft_count = 0  # |diff| > 1000 but |pct| < threshold

    print(f"  {'코드':>5}  {'계정명':12s}  {'PDF':>15}  {'시스템':>15}  {'차이':>16}  결과")
    print("  " + "-" * 78)
    for code, (name, exp) in EXPECTED_BS_HANAH_KOREA_2025.items():
        cur_val = float(seen.get(code, {}).get("balance", 0))
        diff = cur_val - exp
        pct = (diff / exp * 100) if exp else (0 if diff == 0 else 100)

        if abs(diff) < 1000:
            flag = "✓ PASS"
            pass_count += 1
        elif abs(pct) < args.threshold_pct:
            flag = "△ SOFT"
            soft_count += 1
        else:
            flag = "✗ FAIL"
            fail_count += 1
        print(f"  {code:>5}  {name:12s}  {exp:>15,}  {int(cur_val):>15,}  {int(diff):>+16,}  {flag} ({pct:+.1f}%)")

    total = pass_count + soft_count + fail_count
    print("\n" + "=" * 80)
    print(f"PASS: {pass_count}/{total} | SOFT: {soft_count}/{total} | FAIL: {fail_count}/{total}")

    # 분개/거래 통계
    cur.execute("SELECT COUNT(*) FROM journal_entries WHERE entity_id = %s", [args.entity])
    je = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM transactions WHERE entity_id = %s", [args.entity])
    tx = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM invoices WHERE entity_id = %s AND status != 'cancelled'", [args.entity])
    inv = cur.fetchone()[0]
    print(f"\n시스템 데이터: journal_entries={je}, transactions={tx}, invoices(active)={inv}")

    if fail_count > 0:
        print("\n원인 분석:")
        if inv == 0:
            print("  ⚠ invoices 비어있음 → 외상매출금/외상매입금/부가세대급금 분개 자체가 없음")
            print("    → 회계법인 원장의 외상매출/매입 데이터를 invoices 테이블에 입력 필요")
        if seen.get("26200", {}).get("balance", 0) == 0 and tx > 0:
            print("  ⚠ 미지급비용 0 → 카드 거래 분개가 P3-1 발생주의 패턴 미적용")
            print("    → migrate_journal_entries_to_accrual.py 실행 필요 (기존 분개 재생성)")
        if seen.get("10300", {}).get("balance", 0) == 0:
            print("  ⚠ 보통예금 0 → 모든 cash 분개가 10100(현금)에 잡힘")
            print("    → bookkeeping_engine cash_account_id 를 10300 으로 변경하거나")
            print("       source_type 별 cash 분개 매핑 (woori_bank → 10300, ibk → 10300 등)")

    cur.close()
    conn.close()
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

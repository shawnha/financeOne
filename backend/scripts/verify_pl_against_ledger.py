"""회계법인 1월 P&L vs 시스템 분개 손익 비교 (P3-13).

회계법인 원장 P&L 시트 합계 (월별) 와 시스템의 1월 손익 분개 합계 비교.
BS 가 PASS 했더라도 (결손금 한 항목으로 흡수) P&L 항목별 정합성 확인.

사용:
    python -m backend.scripts.verify_pl_against_ledger --entity 2 --year 2026 --month 1
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

load_dotenv()


# ── 회계법인 1월 P&L (한아원코리아 entity=2) ──
# 출처: 25.12.31.기준 가결산자료 → 26년/1월/계정별원장 P&L 시트 합계
EXPECTED_PL_HANAH_KOREA: dict[str, dict[str, tuple[str, int]]] = {
    "2026-01": {
        # 매출
        "40100": ("상품매출",      38_584_662),
        "41200": ("서비스매출",    29_090_909),
        # 비용
        "81100": ("복리후생비",    10_920_930),
        "81200": ("여비교통비",     2_637_521),
        "81900": ("지급임차료",     9_240_584),
        "82100": ("보험료",         1_723_820),
        "82400": ("운반비",           880_985),
        "83000": ("소모품비",      17_659_643),
        "83100": ("지급수수료",    27_249_974),
        "83300": ("광고선전비",    48_264_015),
        "96000": ("잡손실",            12_530),
    },
}


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, default=2)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=1)
    parser.add_argument("--threshold-pct", type=float, default=5.0)
    args = parser.parse_args()

    key = f"{args.year}-{args.month:02d}"
    if key not in EXPECTED_PL_HANAH_KOREA:
        print(f"⚠ {key} 의 회계법인 PDF P&L 이 hardcoded 안 됨.")
        print(f"  지원: {list(EXPECTED_PL_HANAH_KOREA.keys())}")
        return 2

    expected = EXPECTED_PL_HANAH_KOREA[key]
    start, end = _month_range(args.year, args.month)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # 시스템 손익 분개 — 항목별
    cur.execute(
        """
        SELECT sa.code, sa.name, sa.category,
               COALESCE(SUM(jel.debit_amount), 0) AS dr,
               COALESCE(SUM(jel.credit_amount), 0) AS cr
        FROM journal_entries je
        JOIN journal_entry_lines jel ON jel.journal_entry_id = je.id
        JOIN standard_accounts sa ON sa.id = jel.standard_account_id
        WHERE je.entity_id = %s
          AND je.entry_date BETWEEN %s AND %s
          AND sa.category IN ('수익','비용')
        GROUP BY sa.code, sa.name, sa.category
        """,
        [args.entity, start, end],
    )
    seen: dict[str, dict] = {}
    for code, name, cat, dr, cr in cur.fetchall():
        dr = float(dr); cr = float(cr)
        net = (cr - dr) if cat == "수익" else (dr - cr)
        seen[code] = {"name": name, "category": cat, "net": net}

    print(f"\n=== 한아원코리아(entity={args.entity}) {key} P&L 검증 ===")
    print(f"  비교 대상: {len(expected)} 항목\n")

    perfect = pass_count = soft = fail = 0
    total_abs_diff = 0.0
    pct_abs_sum = 0.0
    pct_abs_n = 0

    print(f"  {'코드':>5}  {'계정명':14s}  {'PDF':>14}  {'시스템':>14}  {'차이':>14}  결과")
    print("  " + "-" * 78)
    for code, (name, exp) in expected.items():
        cur_val = seen.get(code, {}).get("net", 0)
        diff = cur_val - exp
        pct = (diff / exp * 100) if exp else (0 if diff == 0 else 100)
        total_abs_diff += abs(diff)
        if exp != 0:
            pct_abs_sum += abs(pct); pct_abs_n += 1

        if abs(diff) < 1000:
            flag = "✓✓ PERFECT"; perfect += 1
        elif abs(pct) <= 1.0:
            flag = "✓  PASS  "; pass_count += 1
        elif abs(pct) <= args.threshold_pct:
            flag = "△  SOFT  "; soft += 1
        else:
            flag = "✗  FAIL  "; fail += 1
        print(f"  {code:>5}  {name:14s}  {exp:>14,}  {int(cur_val):>14,}  {int(diff):>+14,}  {flag} ({pct:+.2f}%)")

    total = perfect + pass_count + soft + fail
    avg_pct = (pct_abs_sum / pct_abs_n) if pct_abs_n else 0
    print("\n" + "=" * 80)
    print(f"PERFECT: {perfect}/{total} | PASS: {pass_count}/{total} | "
          f"SOFT: {soft}/{total} | FAIL: {fail}/{total}")
    print(f"진척도: 차이 합계 {int(total_abs_diff):,} | 평균 |%| = {avg_pct:.1f}%")

    # 시스템 합계 (참고)
    sys_rev = sum(s["net"] for s in seen.values() if s["category"] == "수익")
    sys_exp = sum(s["net"] for s in seen.values() if s["category"] == "비용")
    print(f"\n시스템 {key} 손익: 매출 {sys_rev:,.0f}, 비용 {sys_exp:,.0f}, 손익 {sys_rev - sys_exp:,.0f}")

    # PDF 합계
    pdf_rev = sum(exp for code, (_, exp) in expected.items() if code in ("40100","41200","90100","91100","91200","96100"))
    pdf_exp = sum(exp for code, (_, exp) in expected.items() if code not in ("40100","41200","90100","91100","91200","96100"))
    print(f"PDF    {key} 손익: 매출 {pdf_rev:,.0f}, 비용 {pdf_exp:,.0f}, 손익 {pdf_rev - pdf_exp:,.0f}")

    # 시스템에만 있는 손익 계정 (PDF 미정의)
    extra = {c: s for c, s in seen.items() if c not in expected and abs(s["net"]) > 1000}
    if extra:
        print(f"\n시스템에만 있는 손익 계정 (PDF 미정의):")
        for code, s in sorted(extra.items()):
            print(f"  {code}  {s['name']:14s}  net={s['net']:+,.0f}")

    cur.close()
    conn.close()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""25년 12월말 BS 잔액을 26-01-01 자 일괄 분개로 등록 (opening balance).

회계법인 25년 결산 PDF 의 모든 BS 계정 잔액을 한 번의 compound journal entry 로
입력. 26년 1월 부터 누적 잔액이 정확해짐.

검증: 차변(자산 + 결손금) = 대변(부채 + 자본금 + 주식발행초과금)

사용:
    python -m backend.scripts.import_opening_balances --entity 2 --dry-run
    python -m backend.scripts.import_opening_balances --entity 2 --commit
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

from backend.services.bookkeeping_engine import create_journal_entry


# ── 한아원코리아 25년 12-31 BS 잔액 (PDF 출처) ──
# (code, name, normal_side, amount).
# normal_side='debit'  = 자산 + 결손금 (차변에 기재)
# normal_side='credit' = 부채 + 자본금/잉여금 (대변에 기재)
HOI_OPENING_2026 = [
    # 자산 (USD)
    ("10300", "Mercury Checking",      "debit",  Decimal("144362.71")),
    ("12000", "Channel Clearing",      "debit",  Decimal("2732.36")),  # Amazon/Shopify/PayPal/TikTok 합산
    ("14600", "Inventory",             "debit",  Decimal("141825.18")),
    ("96200", "Industrious Security",  "debit",  Decimal("2472.00")),
    ("18400", "Investment in Subsidiary", "debit", Decimal("134180.00")),
    # 부채 (USD)
    ("25500", "Shopify Sales Tax",     "credit", Decimal("93.86")),
    ("30300", "Loan from HOCL",        "credit", Decimal("125305.50")),
    # 자본 (USD)
    ("33100", "Capital Stock",         "credit", Decimal("134180.00")),
    ("34100", "Additional Paid-In Capital", "credit", Decimal("219000.00")),
    ("37800", "Net Income (year 1 결손)", "debit", Decimal("53007.11")),
]


HANAH_KOREA_OPENING_2026 = [
    # 자산 — 722,144,369
    ("10300", "보통예금",       "debit",   161_065_312),
    ("10800", "외상매출금",     "debit",   246_164_180),
    ("12000", "미수금",          "debit",    50_648_785),
    ("13100", "선급금",          "debit",    11_892_712),
    ("13600", "선납세금",        "debit",        40_620),
    ("14600", "상품",             "debit",    35_696_395),
    ("21200", "비품",             "debit",    36_436_365),
    ("21900", "시설장치",         "debit",    80_000_000),
    ("96200", "임차보증금",       "debit",   100_200_000),
    # 부채 — 780,923,991
    ("25100", "외상매입금",      "credit",   54_253_934),
    ("25400", "예수금",          "credit",    4_069_170),
    ("26200", "미지급비용",      "credit",   42_600_887),
    ("30300", "주임종 장기차입금", "credit",  130_000_000),
    ("31500", "조건부지분인수계약부채", "credit", 550_000_000),
    # 자본 — -58,779,622 (= 303,602,000 + 761,393,660 - 1,123,775,282)
    ("33100", "자본금",           "credit",  303_602_000),
    ("34100", "주식발행초과금",   "credit",  761_393_660),
    ("37800", "미처리결손금",     "debit", 1_123_775_282),  # 결손금은 자본 차감 → 차변
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, required=True)
    parser.add_argument("--as-of", default="2026-01-01",
                        help="opening balance 일자 (기본 26-01-01)")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    if args.entity == 2:
        opening = HANAH_KOREA_OPENING_2026
        entity_name = "한아원코리아"
    elif args.entity == 1:
        opening = HOI_OPENING_2026
        entity_name = "HOI Inc. (USD)"
    else:
        print(f"⚠ entity={args.entity} 데이터 미정의. (지원: 1=HOI, 2=한아원코리아)")
        return 2

    as_of = date.fromisoformat(args.as_of)

    # 검증
    debit_total = sum(amt for _, _, side, amt in opening if side == "debit")
    credit_total = sum(amt for _, _, side, amt in opening if side == "credit")
    print(f"\n=== opening balance 26-01-01 (entity={args.entity} {entity_name}) ===")
    print(f"  계정 수: {len(opening)}")
    print(f"  차변 합계: {debit_total:>15,} (자산 + 결손금)")
    print(f"  대변 합계: {credit_total:>15,} (부채 + 자본금/잉여금)")
    print(f"  차이:      {debit_total - credit_total:>15,}")
    if debit_total != credit_total:
        print(f"  ✗ 차변 ≠ 대변 — 분개 불가능")
        return 1
    print(f"  ✓ 차변 = 대변 (분개 검증 통과)")

    if args.dry_run:
        print("\n  --commit 으로 실행하면 위 계정들을 일괄 분개로 등록.")
        return 0

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # 기존 opening balance 분개가 있는지 확인 (description 으로 식별)
    cur.execute("""
        SELECT id FROM journal_entries
        WHERE entity_id = %s AND description = '전기이월 (opening balance)'
    """, [args.entity])
    existing = cur.fetchall()
    if existing:
        print(f"\n  ⚠ 기존 opening balance 분개 {len(existing)} 건 발견. 삭제 후 재생성.")
        for (je_id,) in existing:
            cur.execute("DELETE FROM journal_entry_lines WHERE journal_entry_id = %s", [je_id])
            cur.execute("DELETE FROM journal_entries WHERE id = %s", [je_id])

    # 코드 → standard_account_id 매핑
    cur.execute("SELECT code, id FROM standard_accounts")
    code_to_id = dict(cur.fetchall())

    lines = []
    missing = []
    for code, name, side, amount in opening:
        sa_id = code_to_id.get(code)
        if not sa_id:
            missing.append((code, name))
            continue
        if side == "debit":
            lines.append({
                "standard_account_id": sa_id,
                "debit_amount": Decimal(str(amount)),
                "credit_amount": Decimal("0"),
            })
        else:
            lines.append({
                "standard_account_id": sa_id,
                "debit_amount": Decimal("0"),
                "credit_amount": Decimal(str(amount)),
            })

    if missing:
        print(f"\n  ✗ standard_account 미존재 {len(missing)} 건:")
        for code, name in missing:
            print(f"    {code} {name}")
        return 1

    cur.close()
    je_id = create_journal_entry(
        conn=conn,
        entity_id=args.entity,
        lines=lines,
        entry_date=as_of,
        description="전기이월 (opening balance)",
    )
    conn.commit()
    print(f"\n  ✓ 분개 생성 완료: journal_entry_id={je_id}, 라인 {len(lines)} 개")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

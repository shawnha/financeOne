"""기존 confirmed transactions 의 분개 → P3-1/P3-4 발생주의 패턴으로 재생성.

기존 분개 패턴 (현금주의):
    out: (차) 비용/std / (대) 현금(10100)
    in:  (차) 현금(10100) / (대) 수익/std

새 패턴 (발생주의):
    카드 사용 out:    (차) 비용/std / (대) 미지급비용(26200)
    카드 환불 in:     (차) 미지급비용 / (대) 비용/std
    은행 카드결제 out:(차) 미지급비용 / (대) 보통예금(10300)
    은행 일반 out:    (차) 비용/std / (대) 보통예금(10300)
    은행 일반 in:     (차) 보통예금 / (대) 수익/std

사용:
    # 미리보기 (변경 안 함)
    python -m backend.scripts.migrate_journal_entries_to_accrual --entity 2 --year 2026 --month 1 --dry-run

    # 실행 (entity / 기간 필터 권장)
    python -m backend.scripts.migrate_journal_entries_to_accrual --entity 2 --year 2026 --month 1 --commit

전략: invoice 와 매칭된 transactions (invoice_payments 에 등록됨) 는 건드리지 않음 —
이미 invoice_service 가 발생주의 분개 만들었기 때문.
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

from backend.services.bookkeeping_engine import create_journal_from_transaction


def _date_range(year: int | None, month: int | None) -> tuple[date | None, date | None]:
    if year is None:
        return None, None
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return date(year, month, 1), end


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, required=True)
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)
    parser.add_argument("--source", help="source_type 필터 (예: codef_lotte_card)")
    parser.add_argument("--limit", type=int, default=0, help="0 = 전체")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    start, end = _date_range(args.year, args.month)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # 대상 transactions 조회 — confirmed + 매핑됨 + invoice 매칭 X.
    where = ["t.entity_id = %s", "t.is_confirmed = true",
             "(t.is_cancel IS NOT TRUE)", "t.is_duplicate = false",
             "t.standard_account_id IS NOT NULL",
             "t.id NOT IN (SELECT transaction_id FROM invoice_payments)"]
    params: list = [args.entity]
    if start:
        where.append("t.date >= %s")
        params.append(start)
    if end:
        where.append("t.date <= %s")
        params.append(end)
    if args.source:
        where.append("t.source_type = %s")
        params.append(args.source)

    cur.execute(
        f"""
        SELECT t.id, t.date, t.source_type, t.type, t.amount, t.counterparty
        FROM transactions t
        WHERE {' AND '.join(where)}
        ORDER BY t.date, t.id
        {('LIMIT ' + str(args.limit)) if args.limit else ''}
        """,
        params,
    )
    targets = cur.fetchall()
    print(f"\n=== 마이그레이션 대상: {len(targets)} 건 ===")
    print(f"  entity={args.entity}, period={start}~{end}, source={args.source or 'all'}")
    print(f"  mode={'DRY-RUN' if args.dry_run else 'COMMIT'}")

    by_source: dict[str, int] = {}
    for _, _, src, _, _, _ in targets:
        by_source[src] = by_source.get(src, 0) + 1
    print("\n  source_type 분포:")
    for src, cnt in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {src:30s} {cnt:5d}")

    if args.dry_run:
        # 첫 5 건 샘플만 미리보기 — 실제 분개는 안 만듦.
        print("\n  샘플 (처음 5 건):")
        for tx_id, dt, src, ttype, amt, party in targets[:5]:
            print(f"    tx={tx_id} {dt} {ttype} {float(amt):>12,.0f} {src:25s} {party or '-'}")
        print("\n  --commit 으로 실행하면 위 거래의 기존 분개 삭제 후 발생주의 패턴 재생성.")
        cur.close()
        conn.close()
        return 0

    # COMMIT 모드 — 분개 삭제 + 재생성
    deleted = 0
    created = 0
    failed: list[tuple[int, str]] = []

    for tx_id, _, _, _, _, _ in targets:
        try:
            # 기존 분개 + line 삭제
            cur.execute("SELECT id FROM journal_entries WHERE transaction_id = %s", [tx_id])
            je_ids = [r[0] for r in cur.fetchall()]
            for je_id in je_ids:
                cur.execute("DELETE FROM journal_entry_lines WHERE journal_entry_id = %s", [je_id])
                cur.execute("DELETE FROM journal_entries WHERE id = %s", [je_id])
                deleted += 1
            # 새 분개 생성
            new_je_id = create_journal_from_transaction(conn, tx_id)
            if new_je_id:
                created += 1
        except Exception as e:
            failed.append((tx_id, f"{type(e).__name__}: {e}"))

    if failed:
        print(f"\n  ✗ 실패 {len(failed)} 건 — rollback")
        for tx_id, msg in failed[:10]:
            print(f"    tx={tx_id}: {msg}")
        conn.rollback()
        cur.close()
        conn.close()
        return 1

    conn.commit()
    print(f"\n  ✓ 마이그레이션 완료: 삭제 {deleted} / 재생성 {created}")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

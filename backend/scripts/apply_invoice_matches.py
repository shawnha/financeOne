"""invoice ↔ transaction auto_match 후보 자동 적용 (P3-7).

회계적 정합성:
1. transaction 의 기존 journal_entry 삭제 (마이그레이션이 (차)보통예금/(대)매출
   로 만든 분개 — 발생주의에서는 invoice 가 (차)외상매출금/(대)매출 분개를
   이미 만든 상태이므로 transaction 분개는 매출 이중계상 발생).
2. invoice_service.match_invoice_payment() 호출 → 매칭 분개 자동 생성:
   - sales 회수: (차) 보통예금 / (대) 외상매출금 — 외상매출금 차감
   - purchase 결제: (차) 외상매입금 / (대) 보통예금 — 외상매입금 차감
3. invoice_payments 테이블에 매칭 이력 보존.

사용:
    python -m backend.scripts.apply_invoice_matches \\
        --entity 2 --min-score 80 --dry-run
    python -m backend.scripts.apply_invoice_matches \\
        --entity 2 --min-score 80 --commit
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from backend.services.invoice_service import (
    auto_match_candidates,
    match_invoice_payment,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, required=True)
    parser.add_argument("--days-window", type=int, default=14)
    parser.add_argument("--min-score", type=int, default=80,
                        help="이 score 이상만 자동 적용 (기본 80)")
    parser.add_argument("--limit", type=int, default=200)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    cands = auto_match_candidates(
        conn, entity_id=args.entity,
        days_window=args.days_window, limit=args.limit,
    )
    eligible = [c for c in cands if c["score"] >= args.min_score]

    print(f"\n=== auto_match 후보 적용 (entity={args.entity}) ===")
    print(f"  전체 후보: {len(cands)}건")
    print(f"  score≥{args.min_score} 자동 적용 대상: {len(eligible)}건")
    print(f"  모드: {'DRY-RUN' if args.dry_run else 'COMMIT'}\n")

    applied = 0
    skipped = 0
    failed: list[tuple[int, int, str]] = []

    for c in eligible:
        inv_id = c["invoice_id"]
        tx_id = c["transaction_id"]
        amount = c["amount"]
        score = c["score"]
        inv_party = c["invoice_counterparty"]
        tx_party = c["transaction_counterparty"]

        print(f"  [score={score}] inv #{inv_id:5d} {inv_party[:25]:25s} ↔ tx #{tx_id:5d} {tx_party[:25]:25s} {amount:>12,.0f}")

        if args.dry_run:
            applied += 1
            continue

        # transaction 의 기존 분개 삭제 (매칭 분개로 대체)
        try:
            cur.execute("SELECT id FROM journal_entries WHERE transaction_id = %s", [tx_id])
            tx_je_ids = [r[0] for r in cur.fetchall()]
            for je_id in tx_je_ids:
                cur.execute("DELETE FROM journal_entry_lines WHERE journal_entry_id = %s", [je_id])
                cur.execute("DELETE FROM journal_entries WHERE id = %s", [je_id])
            # match_invoice_payment 호출 — invoice_service 가 (차)현금/(대)외상매출금 또는
            # (차)외상매입금/(대)현금 매칭 분개 자동 생성.
            match_invoice_payment(
                conn, invoice_id=inv_id, transaction_id=tx_id,
                matched_by="auto",
                note=f"auto-match score={score}",
            )
            applied += 1
        except Exception as e:
            failed.append((inv_id, tx_id, f"{type(e).__name__}: {e}"))
            conn.rollback()
            continue

    if args.commit:
        if failed:
            print(f"\n  ✗ 실패 {len(failed)} 건:")
            for iid, tid, msg in failed[:10]:
                print(f"    inv {iid} ↔ tx {tid}: {msg}")
        conn.commit()
        print(f"\n  ✓ 매칭 적용 완료: {applied}건 (실패 {len(failed)})")
    else:
        print(f"\n  --commit 으로 실행하면 위 {applied}건 자동 적용.")

    cur.close()
    conn.close()
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())

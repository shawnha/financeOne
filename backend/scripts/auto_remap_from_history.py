"""거래처별 std_account_id 매핑 학습 → 미매핑 거래에 자동 적용.

1월의 confirmed + std 매핑된 거래에서 거래처별 std 빈도 통계 학습.
같은 거래처의 미매핑(std=NULL) 거래에 가장 빈도 높은 std 자동 적용.

거래처 정규화: 은행 prefix 제거 + 핵심 토큰 추출.

사용:
    # 미리보기 (적용 안 함)
    python -m backend.scripts.auto_remap_from_history \\
        --entity 2 --learn-from 2026-01-01:2026-01-31 \\
        --apply-to 2026-02-01:2026-02-28 --dry-run

    # 적용
    python -m backend.scripts.auto_remap_from_history \\
        --entity 2 --learn-from 2026-01-01:2026-01-31 \\
        --apply-to 2026-02-01:2026-02-28 --commit
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from datetime import date

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def _normalize_counterparty(name: str) -> str:
    s = str(name or "").strip()
    s = re.sub(r"^(국민|기업|하나|신한|우리|F/B\s?출금|F/B\s?입금|인터넷|모바일|펌뱅킹|"
               r"대체입금|대체지급|지로자동|관세납부|S1)\s*", "", s)
    s = re.sub(r"\(주\)|㈜|주식회사|유한회사", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[\s\u3000\u00a0]+", "", s)
    return s


def _parse_range(s: str) -> tuple[date, date]:
    a, b = s.split(":")
    return date.fromisoformat(a), date.fromisoformat(b)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, required=True)
    parser.add_argument("--learn-from", required=True, help="YYYY-MM-DD:YYYY-MM-DD")
    parser.add_argument("--apply-to", required=True, help="YYYY-MM-DD:YYYY-MM-DD")
    parser.add_argument("--min-confidence", type=float, default=0.6,
                        help="해당 거래처에서 이 비율 이상으로 매핑된 std 만 적용")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    learn_start, learn_end = _parse_range(args.learn_from)
    apply_start, apply_end = _parse_range(args.apply_to)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # 1) 학습: 거래처별 std 빈도 + 금액 통계
    cur.execute(
        """
        SELECT t.counterparty, t.description, sa.code, sa.id, t.amount
        FROM transactions t
        JOIN standard_accounts sa ON sa.id = t.standard_account_id
        WHERE t.entity_id = %s
          AND t.date BETWEEN %s AND %s
          AND t.is_confirmed = true
          AND (t.is_cancel IS NOT TRUE) AND t.is_duplicate = false
          AND t.standard_account_id IS NOT NULL
        """,
        [args.entity, learn_start, learn_end],
    )
    # key = normalized counterparty, value = Counter of (std_code, std_id)
    party_to_std: dict[str, Counter] = {}
    for cp, desc, code, sa_id, amt in cur.fetchall():
        key = _normalize_counterparty(cp or desc or "")
        if not key:
            continue
        party_to_std.setdefault(key, Counter())[(code, sa_id)] += 1

    print(f"\n=== 학습 ({learn_start} ~ {learn_end}) ===")
    print(f"  거래처 수: {len(party_to_std)}")

    # 2) 적용 대상: std=NULL 거래
    cur.execute(
        """
        SELECT id, date, type, counterparty, description, amount, source_type
        FROM transactions
        WHERE entity_id = %s
          AND date BETWEEN %s AND %s
          AND standard_account_id IS NULL
          AND (is_cancel IS NOT TRUE) AND is_duplicate = false
        ORDER BY amount DESC
        """,
        [args.entity, apply_start, apply_end],
    )
    targets = cur.fetchall()
    print(f"\n=== 적용 대상 ({apply_start} ~ {apply_end}) ===")
    print(f"  미매핑 거래: {len(targets)}건\n")

    matched: list[tuple[int, str, int, str, str, int, float]] = []
    unmatched: list[tuple] = []

    for tx_id, dt, ttype, cp, desc, amt, src in targets:
        key = _normalize_counterparty(cp or desc or "")
        std_counter = party_to_std.get(key)
        if not std_counter:
            unmatched.append((tx_id, dt, cp, amt, src))
            continue
        # 가장 빈도 높은 std + confidence
        total = sum(std_counter.values())
        (top_code, top_id), top_cnt = std_counter.most_common(1)[0]
        confidence = top_cnt / total
        if confidence < args.min_confidence:
            unmatched.append((tx_id, dt, cp, amt, src))
            continue
        matched.append((tx_id, dt, top_id, top_code, cp or desc, amt, confidence))

    print(f"--- matched {len(matched)}건 (confidence ≥ {args.min_confidence}) ---")
    matched_total = sum(float(m[5]) for m in matched)
    print(f"  합계 금액: {matched_total:,.0f}\n")
    for tx_id, dt, sa_id, code, party, amt, conf in matched[:30]:
        print(f"  tx#{tx_id:5d} {dt} {(party or '')[:25]:25s} {float(amt):>12,.0f} → {code} (conf={conf:.0%})")
    if len(matched) > 30:
        print(f"  ... +{len(matched)-30}건")

    print(f"\n--- unmatched {len(unmatched)}건 (학습 데이터 없음 또는 confidence 낮음) ---")
    unmatched_total = sum(float(u[3]) for u in unmatched)
    print(f"  합계 금액: {unmatched_total:,.0f}\n")
    for tx_id, dt, cp, amt, src in unmatched[:20]:
        print(f"  tx#{tx_id:5d} {dt} {(cp or '')[:25]:25s} {float(amt):>12,.0f} src={src}")
    if len(unmatched) > 20:
        print(f"  ... +{len(unmatched)-20}건")

    if args.dry_run:
        print(f"\n--commit 으로 실행하면 matched {len(matched)}건의 std 매핑.")
        cur.close(); conn.close()
        return 0

    # 3) COMMIT
    for tx_id, _, sa_id, _, _, _, _ in matched:
        cur.execute(
            "UPDATE transactions SET standard_account_id = %s, mapping_source = 'auto', "
            "mapping_confidence = NULL, updated_at = NOW() WHERE id = %s",
            [sa_id, tx_id],
        )
    conn.commit()
    print(f"\n  ✓ 적용 완료: {len(matched)}건")
    print(f"  다음 단계: migrate_journal_entries_to_accrual --month {apply_start.month} --commit")
    cur.close(); conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

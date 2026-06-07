# 계정 트리 재설계 M6a — 코리아(2) 잎 표준교정 + drift 정렬(2026 열림분). 재무 영향 有.
"""
정식설계 docs/account-tree-redesign-design.md §3.4, 메커니즘 §3·§14-C1. 불변식 #1(잎 먼저).
결산 reconciliation + drift 성격분류(BS다리 KEEP vs P&L drift ALIGN) 기반.

처리:
A. 명시 잎교정 5종 (결산 확정) — 잎 std 교정 + 그 잎의 2026 거래 std + JEL std라인 in-place.
   카테고리 넘는 교정도 명시 처리(BS휴리스틱 KEEP 우회).
   - 차입금이자비용+이자지급3(1818/1819/1820/1821) 30300→93100 이자비용
   - 카드대금 정식/선결제(447/446) 25200→26200 미지급비용
   - 통신비 dedup(복합기렌탈357/기타통신비464) 82800→81400
   - 관리비(356) 84000→81500 수도광열비
   - 퇴직금(352) 80500→80800 퇴직급여(dedup)
B. 휴리스틱 ALIGN — 위 외 2026 거래 중 tx.std≠잎.std:
   - KEEP(불변식#1): tx.std=BS(자산/부채) & 잎.std=P&L → 복식부기 다른 다리(수금/지급/발생), 안 건드림.
   - ALIGN: 그 외(P&L drift, NULL, 둘다BS) → tx.std=잎.std + JEL in-place.
2025 잠김분(18)·split 거래·대여금 dup·차입금→잡이익 엣지 = 제외(별도).

JEL: confirmed 거래의 비-조정/마감 분개에서 std=old 라인 1개만 new로 교체(금액·side 보존, §2.4).
     라인이 0 or 2+면 그 거래 SKIP+flag(엉뚱교체 방지, §7.3-#6). 비-std 라인 불변.
게이트: 영향 JE 전부 debit==credit 유지. 매출(상품매출40100) 합계 비증가(가짜매출 비탐지).
멱등 성격. 기본 dry-run(BEGIN…ROLLBACK), --apply COMMIT(+명시승인).
"""
import os
import sys
import psycopg2
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

KOREA = 2
OPEN_FROM = "2026-01-01"  # 2026 열림분만(2025 잠김 제외)

# A. 명시 잎교정: (leaf_ids, new_std_code, label)
EXPLICIT = [
    ([1818, 1819, 1820, 1821], "93100", "차입금이자→이자비용"),
    ([447, 446], "26200", "카드대금→미지급비용"),
    ([357, 464], "81400", "통신비 dedup"),
    ([356], "81500", "관리비 dedup"),
    ([352], "80800", "퇴직금 dedup"),
]
BS = ("자산", "부채", "자본")


def std_id(cur, code):
    cur.execute("SELECT id FROM standard_accounts WHERE code=%s AND gaap_type='K_GAAP'", (code,))
    return cur.fetchone()[0]


def repost_jel(cur, tx_id, old_std_id, new_std_id, flags):
    """confirmed 거래의 비-조정/마감 분개에서 std=old 라인 1개만 new로 in-place 교체."""
    # 이미 new_std 라인 보유 = JEL이 이미 정답(재전기 불필요, 가짜경보 아님)
    cur.execute(
        """SELECT 1 FROM journal_entry_lines jel JOIN journal_entries je ON je.id=jel.journal_entry_id
            WHERE je.transaction_id=%s AND jel.standard_account_id=%s LIMIT 1""",
        (tx_id, new_std_id),
    )
    if cur.fetchone():
        return
    cur.execute(
        """SELECT jel.id FROM journal_entry_lines jel
             JOIN journal_entries je ON je.id=jel.journal_entry_id
            WHERE je.transaction_id=%s AND NOT je.is_adjusting AND NOT je.is_closing
              AND jel.standard_account_id=%s""",
        (tx_id, old_std_id),
    )
    lines = [r[0] for r in cur.fetchall()]
    if len(lines) == 0:
        # old/new 둘 다 없음 — BS-only 분개(손익 라인 없음)면 손익 무영향. 분개 보유시 flag(수동).
        cur.execute(
            """SELECT count(*) FROM journal_entry_lines jel JOIN journal_entries je ON je.id=jel.journal_entry_id
                 JOIN standard_accounts sa ON sa.id=jel.standard_account_id
                WHERE je.transaction_id=%s AND sa.category IN ('비용','수익','매출','매출원가')""",
            (tx_id,),
        )
        pl_lines = cur.fetchone()[0]
        cur.execute("SELECT 1 FROM journal_entries WHERE transaction_id=%s LIMIT 1", (tx_id,))
        if cur.fetchone():
            flags.append((tx_id, "BS-only분개(손익무영향)" if pl_lines == 0 else "JEL손익라인≠old/new"))
        return
    if len(lines) > 1:
        flags.append((tx_id, f"JEL std라인 {len(lines)}개(모호)"))
        return
    cur.execute("UPDATE journal_entry_lines SET standard_account_id=%s WHERE id=%s", (new_std_id, lines[0]))


def main(apply: bool) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    print(f"=== M6a 코리아 잎교정+drift 정렬 ({'APPLY/COMMIT' if apply else 'DRY-RUN/ROLLBACK'}) ===\n")

    # 사전: 매출(상품매출 40100) 합계 baseline (가짜매출 게이트)
    rev_id = std_id(cur, "40100")
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=%s",
        (KOREA, rev_id),
    )
    rev_before = cur.fetchone()[0]

    flags = []
    moved = defaultdict(lambda: [0, 0])  # new_std_code → [거래수, JEL수]

    # ── A. 명시 잎교정 + 거래/JEL 정렬 ──
    print("[A] 명시 잎교정 5종 (잎 + 2026 거래 + JEL)")
    for leaf_ids, new_code, label in EXPLICIT:
        new_id = std_id(cur, new_code)
        # 잎 std 교정
        cur.execute(
            "UPDATE internal_accounts SET standard_account_id=%s WHERE id=ANY(%s) AND entity_id=%s",
            (new_id, leaf_ids, KOREA),
        )
        nleaf = cur.rowcount
        # 그 잎의 2026 거래 중 std≠new → tx.std=new + JEL in-place
        cur.execute(
            """SELECT t.id, t.standard_account_id FROM transactions t
                WHERE t.entity_id=%s AND t.internal_account_id=ANY(%s)
                  AND t.date >= %s
                  AND (t.standard_account_id IS DISTINCT FROM %s)
                  AND NOT EXISTS(SELECT 1 FROM transaction_splits s WHERE s.transaction_id=t.id)""",
            (KOREA, leaf_ids, OPEN_FROM, new_id),
        )
        txs = cur.fetchall()
        for tx_id, old_std in txs:
            cur.execute("UPDATE transactions SET standard_account_id=%s WHERE id=%s", (new_id, tx_id))
            if old_std is not None:
                repost_jel(cur, tx_id, old_std, new_id, flags)
            moved[new_code][0] += 1
        print(f"    {label:22} 잎{nleaf} + 거래 {len(txs)} 정렬")

    # ── B. 휴리스틱 ALIGN (P&L drift, KEEP=BS다리 제외) ──
    print("\n[B] 휴리스틱 ALIGN (P&L drift → 잎, KEEP=BS다리 유지)")
    cur.execute(
        """SELECT t.id, t.standard_account_id, ia.standard_account_id AS leaf_std,
                  sa_t.category AS tcat, sa_l.category AS lcat, sa_l.code AS lcode
             FROM transactions t
             JOIN internal_accounts ia ON ia.id=t.internal_account_id
             JOIN standard_accounts sa_l ON sa_l.id=ia.standard_account_id
             LEFT JOIN standard_accounts sa_t ON sa_t.id=t.standard_account_id
            WHERE t.entity_id=%s AND t.date >= %s
              AND ia.standard_account_id IS NOT NULL
              AND t.standard_account_id IS DISTINCT FROM ia.standard_account_id
              AND NOT EXISTS(SELECT 1 FROM transaction_splits s WHERE s.transaction_id=t.id)""",
        (KOREA, OPEN_FROM),
    )
    cand = cur.fetchall()
    keep_n = align_n = 0
    for tx_id, old_std, leaf_std, tcat, lcat, lcode in cand:
        # KEEP: 거래std=BS & 잎=P&L (불변식#1, 복식부기 BS 다리)
        if tcat in BS and lcat not in BS:
            keep_n += 1
            continue
        # ALIGN: tx.std=잎.std + JEL
        cur.execute("UPDATE transactions SET standard_account_id=%s WHERE id=%s", (leaf_std, tx_id))
        if old_std is not None:
            repost_jel(cur, tx_id, old_std, leaf_std, flags)
        moved[lcode][0] += 1
        align_n += 1
    print(f"    ALIGN {align_n}건 정렬 / KEEP {keep_n}건 유지(BS다리)")

    # ── 게이트 검증 ──
    print("\n[게이트]")
    # 1) 매출 비증가(가짜매출)
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=%s",
        (KOREA, rev_id),
    )
    rev_after = cur.fetchone()[0]
    print(f"  상품매출(40100) 합계 {rev_before} → {rev_after} (증가 0이어야)")
    # 2) 영향 JE debit==credit
    cur.execute(
        """SELECT count(*) FROM (
              SELECT je.id, SUM(jel.debit_amount) d, SUM(jel.credit_amount) c
                FROM journal_entries je JOIN journal_entry_lines jel ON jel.journal_entry_id=je.id
               WHERE je.entity_id=%s GROUP BY je.id HAVING SUM(jel.debit_amount)<>SUM(jel.credit_amount)
           ) x""",
        (KOREA,),
    )
    unbal = cur.fetchone()[0]
    print(f"  코리아 분개 debit≠credit: {unbal} (0이어야)")
    # 3) 잔여 drift(KEEP 제외)
    cur.execute(
        """SELECT count(*) FROM transactions t JOIN internal_accounts ia ON ia.id=t.internal_account_id
             JOIN standard_accounts sa_l ON sa_l.id=ia.standard_account_id
             LEFT JOIN standard_accounts sa_t ON sa_t.id=t.standard_account_id
            WHERE t.entity_id=%s AND t.date>=%s AND ia.standard_account_id IS NOT NULL
              AND t.standard_account_id IS DISTINCT FROM ia.standard_account_id
              AND NOT EXISTS(SELECT 1 FROM transaction_splits s WHERE s.transaction_id=t.id)
              AND NOT (sa_t.category=ANY(%s) AND sa_l.category<>ALL(%s))""",
        (KOREA, OPEN_FROM, list(BS), list(BS)),
    )
    resid = cur.fetchone()[0]

    print("\n[이동 요약] (표준코드 → 정렬 거래수)")
    for code, (n, _) in sorted(moved.items()):
        print(f"  → {code}: {n}건")
    print(f"\n잔여 drift(KEEP 제외, 2026): {resid} (0 기대)")
    if flags:
        print(f"⚠️ JEL flag {len(flags)}건(수동 검토): " + ", ".join(f"tx{t}({m})" for t, m in flags[:10]))

    abort = (rev_after != rev_before) or (unbal != 0) or (resid != 0)
    if abort:
        print("\n❌ 게이트 실패 → ROLLBACK")
        conn.rollback(); conn.close(); sys.exit(1)

    if apply:
        conn.commit()
        print("\n✅ COMMIT — 코리아 잎교정+drift 정렬 반영됨.")
    else:
        conn.rollback()
        print("\n↩️  ROLLBACK — prod 무변경 (dry-run). 적용하려면 --apply.")
    conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

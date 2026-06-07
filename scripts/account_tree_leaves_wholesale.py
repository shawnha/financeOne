# 계정 트리 롤아웃 — 홀세일(13) 잎 표준교정 + 거래 정렬(결산 대조). GL=0 → JEL 재전기 없음.
"""
결산 24/25/26 계정별원장(주)한아원홀세일 union 을 거래처·금액·계정시트로 대조한 결과만 적용.
홀세일 패턴 = 코리아 반대: 잎이 틀리고 거래std가 이미 맞는 경우 다수 → 잎을 결산기준으로 교정하면
그 잎의 거래(이미 정답)가 drift 해소됨. 자체판단 금지(feedback_classification_always_settlement).

결산 grounding (계정시트로 확인):
  - 이자비용=93100 / 전력비=81600 / 보험료=82100 / 통신비=81400 / 미지급금(카드대금)=25300
  - 대출이자 잎=소모품비(오), 거래=이자비용(정) → 잎 93100 으로 교정
  - 정식결제/선결제 = 신한카드법인 월결제 → 25300 미지급금(개별매입 1443건 별도 존재 = 월결제 83100 은 이중계상)
  - 주차/주유 잎=여비교통비(정), 일부 거래=51300(레거시) → 81200 align

불변식#1: BS다리 KEEP — 외상매출금 수금 313건(거래=자산 ↔ 잎=상품매출/수익)은 안 건드림(가짜매출 방지).
보류(손대지 않음): 차입금(1214)·차입금상환(1229) = 법인간 거액(한아원/도팜인/김유리) 가지급금vs차입금 미결정
  (project_how_unjajagum_pending) / 기타 catch-all(1236/1828) 혼합 → 리포트에 표기, 거래std 유지.
홀세일 GL=0(분개 0건) → JEL 재전기 없음, transactions 만 갱신.
게이트: 상품매출(40100) 비증가(가짜매출), debit≠credit 0.
기본 dry-run, --apply COMMIT.
"""
import os
import sys
import psycopg2
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(".env")
W = 13
OPEN_FROM = "2026-01-01"
BS = ("자산", "부채", "자본")

# EXPLICIT 잎교정 (결산 확정): (leaf_id, 새코드, 라벨)
EXPLICIT = [
    (1802, "93100", "대출이자→이자비용"),
    (1807, "81600", "전력비"),
    (1805, "82100", "기타보험→보험료"),
    (1268, "81400", "통신비 dedup"),
    (1226, "25300", "정식결제 카드대금→미지급금"),
    (1217, "25300", "선결제 카드대금→미지급금"),
    (1277, "81200", "주차/주유 여비교통비(거래 51300 align)"),
]


def sid(cur, code):
    cur.execute("SELECT id FROM standard_accounts WHERE code=%s AND gaap_type='K_GAAP'", (code,))
    return cur.fetchone()[0]


def main(apply: bool) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"]); conn.autocommit = False
    cur = conn.cursor(); cur.execute("SET search_path TO financeone, public")
    print(f"=== 홀세일 잎교정 ({'APPLY' if apply else 'DRY-RUN'}) ===\n")

    rev = sid(cur, "40100")
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=%s", (W, rev))
    rev_before = cur.fetchone()[0]
    moved = defaultdict(int)
    keep_bs = 0

    print("[EXPLICIT 잎교정 + 거래 정렬 (BS다리 KEEP)]")
    for leaf_id, code, label in EXPLICIT:
        new = sid(cur, code)
        cur.execute("UPDATE internal_accounts SET standard_account_id=%s WHERE id=%s AND entity_id=%s", (new, leaf_id, W))
        nleaf = cur.rowcount
        newcat = None
        cur.execute("SELECT category FROM standard_accounts WHERE id=%s", (new,)); newcat = cur.fetchone()[0]
        cur.execute("""SELECT t.id, st.category FROM transactions t
            LEFT JOIN standard_accounts st ON st.id=t.standard_account_id
            WHERE t.entity_id=%s AND t.internal_account_id=%s AND t.date>=%s
              AND t.standard_account_id IS DISTINCT FROM %s
              AND NOT EXISTS(SELECT 1 FROM transaction_splits s WHERE s.transaction_id=t.id)""",
            (W, leaf_id, OPEN_FROM, new))
        rows = cur.fetchall()
        aligned = kept = 0
        for tx_id, tcat in rows:
            if tcat in BS and newcat not in BS:  # 불변식#1 BS다리 KEEP
                kept += 1; keep_bs += 1; continue
            cur.execute("UPDATE transactions SET standard_account_id=%s WHERE id=%s", (new, tx_id))
            aligned += 1; moved[code] += 1
        print(f"  {label:32} 잎{nleaf} · 거래 align {aligned} · KEEP {kept}")

    # 게이트
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=%s", (W, rev))
    rev_after = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM (SELECT je.id FROM journal_entries je JOIN journal_entry_lines jel ON jel.journal_entry_id=je.id
                   WHERE je.entity_id=%s GROUP BY je.id HAVING SUM(jel.debit_amount)<>SUM(jel.credit_amount)) x""", (W,))
    unbal = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM transactions t WHERE t.entity_id=%s AND
        (t.standard_account_id IS NULL OR EXISTS(SELECT 1 FROM internal_accounts ia WHERE ia.id=t.internal_account_id AND ia.standard_account_id IS NULL))""", (W,))
    flagged = cur.fetchone()[0]
    # 잔여 외상매출금 수금 KEEP 확인(자산↔수익 drift 유지되어야)
    cur.execute("""SELECT count(*) FROM transactions t JOIN internal_accounts ia ON ia.id=t.internal_account_id
        JOIN standard_accounts sl ON sl.id=ia.standard_account_id LEFT JOIN standard_accounts st ON st.id=t.standard_account_id
        WHERE t.entity_id=%s AND t.date>=%s AND st.category='자산' AND sl.category='수익'""", (W, OPEN_FROM))
    bs_collect = cur.fetchone()[0]
    print(f"\n[이동] " + " · ".join(f"{c}:{n}" for c,n in sorted(moved.items())))
    print(f"[게이트] 상품매출 {rev_before}→{rev_after}(불변) · debit≠credit {unbal}(0) · BS다리KEEP {keep_bs} · 외상매출금수금 잔존 {bs_collect}(313 유지) · 표준미지정 거래 {flagged}")
    if rev_after != rev_before or unbal != 0:
        print("❌ 게이트 실패 → ROLLBACK"); conn.rollback(); conn.close(); sys.exit(1)
    if apply:
        conn.commit(); print("\n✅ COMMIT")
    else:
        conn.rollback(); print("\n↩️ ROLLBACK (dry-run)")
    conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

# 계정 트리 M6c — 코리아(2) 미분류 잎 결산 기준 매핑 + 거래 정렬(2026). 재무 영향 有.
"""
결산 계정별원장 거래처 대조 결과로 미분류(std NULL) 잎에 표준 부여 + 2026 거래 std 정렬 + JEL in-place.
결산 grounding(거래처→비용계정): 청호나이스·에스원=지급수수료83100 / 에스앤엘(노트북)=소모품비83000 / 스마트스토어 리뷰=83100.
기타 캐치올(481·493)=잡손실/잡이익(사장님 OK, 거래별 분해는 생략). 인프라구축비=외상매출금(수금, 매출은 invoices가 인식).
자기자금이체(1817)=법인간이라 미분류 유지(별도 인터컴퍼니 대사).

JEL: M6a와 동일(confirmed 거래의 비-조정/마감 분개에서 std라인 1개 in-place, 이미 정답이면 no-op).
게이트: 상품매출(40100) 비증가(가짜매출), debit==credit. 2026 열림분만(2025 잠김 skip).
기본 dry-run, --apply COMMIT.
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()
KOREA = 2
OPEN_FROM = "2026-01-01"

# leaf_id → 새 표준코드 (결산 grounding)
LEAF_MAP = {
    454: "83100", 455: "83100", 482: "83100",  # 제작 외주 → 지급수수료
    462: "83000",                                # 노트북 구매 → 소모품비
    456: "83100",                                # 스마트스토어 리뷰 → 지급수수료
    492: "83100",                                # 정수기 렌탈(청호나이스) → 지급수수료(결산)
    465: "83100",                                # 에스원 → 지급수수료(결산)
    489: "81100",                                # 상여금 → 복리후생비(KW)
    426: "10800",                                # 인프라 구축비 → 외상매출금(수금)
    481: "96000",                                # 기타비용>기타 → 잡손실
    493: "93000",                                # 기타입금>기타 → 잡이익
}
BS = ("자산", "부채", "자본")
# 기타 캐치올 잎: NULL-std 거래만 잡손익 배정(이미 분류된 매출/비용은 유지 — 채효리 매출 보호)
CATCHALL = {481, 493}


def std_id(cur, code):
    cur.execute("SELECT id FROM standard_accounts WHERE code=%s AND gaap_type='K_GAAP'", (code,))
    return cur.fetchone()[0]


def repost_jel(cur, tx_id, old_std, new_std, flags):
    cur.execute("""SELECT 1 FROM journal_entry_lines jel JOIN journal_entries je ON je.id=jel.journal_entry_id
                   WHERE je.transaction_id=%s AND jel.standard_account_id=%s LIMIT 1""", (tx_id, new_std))
    if cur.fetchone():
        return
    cur.execute("""SELECT jel.id FROM journal_entry_lines jel JOIN journal_entries je ON je.id=jel.journal_entry_id
                   WHERE je.transaction_id=%s AND NOT je.is_adjusting AND NOT je.is_closing AND jel.standard_account_id=%s""",
                (tx_id, old_std))
    lines = [r[0] for r in cur.fetchall()]
    if len(lines) == 1:
        cur.execute("UPDATE journal_entry_lines SET standard_account_id=%s WHERE id=%s", (new_std, lines[0]))
    elif lines:
        flags.append(tx_id)


def main(apply: bool) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"]); conn.autocommit = False
    cur = conn.cursor(); cur.execute("SET search_path TO financeone, public")
    print(f"=== M6c 코리아 미분류 잎 매핑 ({'APPLY' if apply else 'DRY-RUN'}) ===\n")
    rev = std_id(cur, "40100")
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=%s", (KOREA, rev))
    rev_before = cur.fetchone()[0]
    flags = []
    for leaf_id, code in LEAF_MAP.items():
        new = std_id(cur, code)
        cur.execute("UPDATE internal_accounts SET standard_account_id=%s WHERE id=%s AND entity_id=%s AND standard_account_id IS NULL",
                    (new, leaf_id, KOREA))
        nleaf = cur.rowcount
        # 2026 거래 정렬: BS다리(거래std=BS & 새표준=P&L)는 KEEP, 그 외 tx.std=new
        cur.execute("""SELECT t.id, t.standard_account_id, st.category FROM transactions t
                       LEFT JOIN standard_accounts st ON st.id=t.standard_account_id
                       WHERE t.entity_id=%s AND t.internal_account_id=%s AND t.date>=%s
                         AND NOT EXISTS(SELECT 1 FROM transaction_splits s WHERE s.transaction_id=t.id)""",
                    (KOREA, leaf_id, OPEN_FROM))
        newcat = None
        cur2 = conn.cursor(); cur2.execute("SELECT category FROM standard_accounts WHERE id=%s", (new,)); newcat = cur2.fetchone()[0]; cur2.close()
        aligned = kept = 0
        is_catchall = leaf_id in CATCHALL
        for tx_id, old_std, tcat in cur.fetchall():
            if old_std == new:
                continue
            if tcat in BS and newcat not in BS:  # 불변식#1 BS다리 KEEP
                kept += 1; continue
            if is_catchall and old_std is not None:  # 기타 캐치올=기존 분류 유지(매출 등 보호)
                kept += 1; continue
            cur.execute("UPDATE transactions SET standard_account_id=%s WHERE id=%s", (new, tx_id))
            if old_std is not None:
                repost_jel(cur, tx_id, old_std, new, flags)
            aligned += 1
        print(f"  잎{leaf_id} → {code}: 잎{nleaf} · 거래정렬{aligned} · KEEP{kept}")

    cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=%s", (KOREA, rev))
    rev_after = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM (SELECT je.id FROM journal_entries je JOIN journal_entry_lines jel ON jel.journal_entry_id=je.id
                   WHERE je.entity_id=%s GROUP BY je.id HAVING SUM(jel.debit_amount)<>SUM(jel.credit_amount)) x""", (KOREA,))
    unbal = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM internal_accounts WHERE entity_id=%s AND is_active AND standard_account_id IS NULL", (KOREA,))
    still_null = cur.fetchone()[0]
    print(f"\n[게이트] 상품매출 {rev_before}→{rev_after}(불변) · debit≠credit {unbal}(0) · 잔여 미분류잎 {still_null}(자기자금이체 등)")
    if flags: print(f"  JEL flag {len(flags)}(이미정답/BS-only): {flags[:8]}")
    if rev_after != rev_before or unbal != 0:
        print("❌ 게이트 실패 → ROLLBACK"); conn.rollback(); conn.close(); sys.exit(1)
    if apply:
        conn.commit(); print("\n✅ COMMIT")
    else:
        conn.rollback(); print("\n↩️ ROLLBACK (dry-run)")
    conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

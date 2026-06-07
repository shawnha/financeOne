# 계정 트리 롤아웃 — 리테일(3) 잎 표준교정 + 거래 정렬(결산 대조). 재무 영향 有.
"""
결산 [최종]26.4.30 계정별원장(주)한아원리테일 을 거래처·금액으로 직접 대조한 결과만 적용.
자체판단·키워드 금지(feedback_classification_always_settlement). 결산 기간 밖(5월)은 flag(NULL).

결산 grounding (거래처 → 계정):
  - 우리/롯데 카드대금 → 26200 미지급비용 (결산 26200 시트에 우리카드9224·롯데카드5381 누적)
  - 주식회사 티소스(유니폼제작) → 25100 외상매입금 (결산: 보통예금 결제 ↔ 외상매입금 차변, BS 결제다리)
  - 킨코스코리아 → 83100 지급수수료 (결산 83100 시트)
  - 농협차현정(노무) → 83100 지급수수료 (결산: 증빙불비 300,000 지급수수료 차변)
  - 알원/류재권·에코모·박갑숙(제작외주 5월)·이프린팅(5월) → 결산 4.30 기준 밖 미발견 → flag(NULL)

잎 교정(결산 확정): 정식결제·선결제 25200→26200 / 노무사비용 NULL→83100.
거래 9건 전부 JEL 없음(검증) → tx.std 만 갱신, 분개 재전기 불필요.
게이트: 매출(41200/40100/40000) 비증가(가짜매출), debit≠credit 0.
기본 dry-run, --apply COMMIT.
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv(".env")
RETAIL = 3

# 잎 표준교정: (leaf_id, 새코드)
LEAF_FIX = [(1510, "26200"), (1503, "26200"), (1823, "83100")]
# 거래 표준 = 결산 확정: tx_id → 코드
TX_FIX = {11491: "26200", 22224: "26200", 22611: "26200",  # 카드대금
          11488: "25100",                                    # 티소스 외상매입금
          12261: "83100", 11507: "83100"}                    # 킨코스·노무사 지급수수료
# 결산 기간 밖(5월) → flag(NULL)
TX_FLAG = [22742, 22741, 22740, 22936]


def sid(cur, code):
    cur.execute("SELECT id FROM standard_accounts WHERE code=%s AND gaap_type='K_GAAP'", (code,))
    return cur.fetchone()[0]


def main(apply: bool) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"]); conn.autocommit = False
    cur = conn.cursor(); cur.execute("SET search_path TO financeone, public")
    print(f"=== 리테일 잎교정 ({'APPLY' if apply else 'DRY-RUN'}) ===\n")

    rev = [sid(cur, c) for c in ("41200", "40100", "40000")]
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=ANY(%s)", (RETAIL, rev))
    rev_before = cur.fetchone()[0]

    print("[잎 교정]")
    for leaf_id, code in LEAF_FIX:
        new = sid(cur, code)
        cur.execute("UPDATE internal_accounts SET standard_account_id=%s WHERE id=%s AND entity_id=%s", (new, leaf_id, RETAIL))
        print(f"  잎{leaf_id} → {code}  rowcount={cur.rowcount}")

    print("\n[거래 결산확정 정렬]")
    for tx_id, code in TX_FIX.items():
        new = sid(cur, code)
        cur.execute("UPDATE transactions SET standard_account_id=%s WHERE id=%s AND entity_id=%s", (new, tx_id, RETAIL))
        print(f"  tx{tx_id} → {code}  rowcount={cur.rowcount}")

    print("\n[거래 flag (5월·결산밖 → NULL)]")
    cur.execute("UPDATE transactions SET standard_account_id=NULL WHERE id=ANY(%s) AND entity_id=%s", (TX_FLAG, RETAIL))
    print(f"  flag {cur.rowcount}건 (tx {TX_FLAG})")

    # 게이트
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE entity_id=%s AND standard_account_id=ANY(%s)", (RETAIL, rev))
    rev_after = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM (SELECT je.id FROM journal_entries je JOIN journal_entry_lines jel ON jel.journal_entry_id=je.id
                   WHERE je.entity_id=%s GROUP BY je.id HAVING SUM(jel.debit_amount)<>SUM(jel.credit_amount)) x""", (RETAIL,))
    unbal = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM transactions t WHERE t.entity_id=%s AND (t.standard_account_id IS NULL OR EXISTS(SELECT 1 FROM internal_accounts ia WHERE ia.id=t.internal_account_id AND ia.standard_account_id IS NULL))", (RETAIL,))
    flagged = cur.fetchone()[0]
    print(f"\n[게이트] 매출 {rev_before}→{rev_after}(불변) · debit≠credit {unbal}(0) · 표준미지정 거래 {flagged}")
    if rev_after != rev_before or unbal != 0:
        print("❌ 게이트 실패 → ROLLBACK"); conn.rollback(); conn.close(); sys.exit(1)
    if apply:
        conn.commit(); print("\n✅ COMMIT")
    else:
        conn.rollback(); print("\n↩️ ROLLBACK (dry-run)")
    conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

# 계정 트리 재설계 M2 — 코리아(2) 2025 회계기간 마감 잠금 등록 스크립트.
"""
정식설계 docs/account-tree-redesign-design.md §2.3·§5.1-step2, 메커니즘 §1. 스코프 A'(경량 historical 가드).
- 코리아(2) 2025-01 ~ 2025-12 (12개월) fiscal_period_locks 등록, basis='both'.
  25년귀속 회계법인 신고완료 → 2025 동결(불변 박제). 2026은 전부 열림(가결산 대조·정렬 가능).
  활동월=2025-11/12(892건)지만 백데이트 방지로 연 전체 잠금(트리거는 정확월 매칭, §1.2).
- 트리거 바인딩(trg_fiscal_period_lock_guard ENABLE)은 별도 Alembic(n0o1p2q3r4s5). 이 스크립트는 lock 행만.

⚠️ 잠긴 기간 정정은 직접 UPDATE 금지 → 열린 일자의 재분류분개(is_adjusting) 또는
   financeone.allow_locked_write=on 세션(통제된 마이그/재전기)에서만.

멱등: ON CONFLICT(entity_id, period, basis) DO NOTHING. 기본 dry-run, --apply로 COMMIT.
"""
import os
import sys
import datetime
import psycopg2
from dotenv import load_dotenv

load_dotenv()

KOREA_ENTITY_ID = 2
LOCK_MONTHS = [datetime.date(2025, m, 1) for m in range(1, 13)]  # 2025-01 .. 2025-12


def main(apply: bool) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    print(f"=== M2 코리아 마감 잠금 ({'APPLY/COMMIT' if apply else 'DRY-RUN/ROLLBACK'}) ===\n")

    for period in LOCK_MONTHS:
        cur.execute(
            """INSERT INTO fiscal_period_locks (entity_id, period, basis, note)
               VALUES (%s, %s, 'both', '25년귀속 회계법인 신고완료 동결 (계정트리 M2)')
               ON CONFLICT (entity_id, period, basis) DO NOTHING""",
            (KOREA_ENTITY_ID, period),
        )

    cur.execute(
        "SELECT count(*), min(period), max(period) FROM fiscal_period_locks WHERE entity_id=%s AND basis='both'",
        (KOREA_ENTITY_ID,),
    )
    cnt, mn, mx = cur.fetchone()
    print(f"코리아 잠금 행: {cnt}개 ({mn} ~ {mx})  (기대 12)")

    # 안전 확인 — 2026(열린 기간)은 잠그지 않았는지
    cur.execute(
        "SELECT count(*) FROM fiscal_period_locks WHERE entity_id=%s AND period >= DATE '2026-01-01'",
        (KOREA_ENTITY_ID,),
    )
    open_locked = cur.fetchone()[0]
    print(f"2026 이상 잠긴 월: {open_locked}  (기대 0 — 2026은 열림)")

    if cnt != 12 or open_locked != 0:
        print("  ⚠️ 기대와 불일치 → ROLLBACK, 중단")
        conn.rollback()
        conn.close()
        sys.exit(1)

    if apply:
        conn.commit()
        print("\n✅ COMMIT — 코리아 2025 잠금 등록됨. (트리거 바인딩은 Alembic n0o1p2q3r4s5)")
    else:
        conn.rollback()
        print("\n↩️  ROLLBACK — prod 무변경 (dry-run). 적용하려면 --apply.")
    conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

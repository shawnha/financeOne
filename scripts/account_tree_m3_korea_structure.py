# 계정 트리 재설계 M3 — 코리아(2) 내부계정 구조 정리(평탄화·잡탕 리네임). 재무 영향 0.
"""
정식설계 docs/account-tree-redesign-design.md §3.1·§3.2, 메커니즘 §6. 스코프 = 코리아 PoC.

standard_account_id·거래·분개를 전혀 안 건드림 → 재무 net 0. parent_id/name/is_active만.
잠금 트리거는 transactions/JEL/splits에만 걸려 internal_accounts 변경엔 무관.

① 평탄화 (그룹≈표준, 자식을 그룹의 부모로 올림):
   - 빈 그룹 6 (직접거래 0) → 자식 재부모 + 그룹 is_active=false.
   - 이중역할 2 (직접거래 보유: 교통10·세금공과23) → 자식 재부모 + 노드는 살려 "기타 X" 리네임(catch-all 잎).
② 잡탕 리네임 5 (P&L 잎이름==표준이름 → "기타 X"). 이름만.
③ 죽은시드 0 (코리아는 시드 원본, 후보 전부 backbone 표준이라 KEEP).

각 작업은 대상 행의 (entity, name, 거래수)를 사전 단언 — 예상과 다르면 ROLLBACK·중단(엉뚱한 행 방지).
멱등: 재실행 시 이미 비활성/리네임된 건 no-op. 기본 dry-run, --apply로 COMMIT.
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

KOREA = 2

# (id, 예상이름) — 자식 위로 + 그룹 비활성. 직접거래 0 단언.
FLATTEN_EMPTY = [
    (345, "매출"), (346, "서비스매출"), (350, "인건비"),
    (358, "복리후생"), (425, "임차료"), (376, "수수료"),
]
# (id, 예상이름, 새이름) — 자식 위로 + 노드 유지 + 리네임. 직접거래 보유.
FLATTEN_DUAL = [
    (362, "교통", "기타 여비교통비"),
    (380, "세금/공과", "기타 세금과공과금"),
]
# (id, 예상이름, 새이름) — 이름만.
JAPTANG_RENAME = [
    (355, "임차료", "기타 지급임차료"),
    (490, "사무용품", "기타 사무용품비"),
    (347, "이자수익", "기타 이자수익"),
    (464, "통신비", "기타 통신비"),
    (382, "법인세", "기타 법인세등"),
]


def assert_ia(cur, iid, expect_name, expect_zero_tx=None):
    cur.execute(
        """SELECT name, entity_id, is_active, parent_id,
                  (SELECT count(*) FROM transactions t WHERE t.internal_account_id=%s),
                  (SELECT count(*) FROM mapping_rules m WHERE m.internal_account_id=%s)
             FROM internal_accounts WHERE id=%s""",
        (iid, iid, iid),
    )
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"❌ IA {iid} 없음")
    name, ent, active, parent, tx, mr = row
    if ent != KOREA:
        raise SystemExit(f"❌ IA {iid} entity={ent} (코리아 아님)")
    if name != expect_name and not name.startswith("기타 "):
        raise SystemExit(f"❌ IA {iid} 이름 '{name}' != 예상 '{expect_name}'")
    if expect_zero_tx and tx != 0:
        raise SystemExit(f"❌ IA {iid} '{name}' 직접거래 {tx}건 (0 기대) — 평탄화 비활성 불가")
    if expect_zero_tx and mr != 0:
        raise SystemExit(f"❌ IA {iid} '{name}' mapping_rules {mr}건 — 비활성 시 고아 위험, 중단")
    return name, parent, tx


def main(apply: bool) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    print(f"=== M3 코리아 구조 정리 ({'APPLY/COMMIT' if apply else 'DRY-RUN/ROLLBACK'}) ===\n")

    # baseline: M3 전 기존 고아 거래(이미 비활성 IA 가리킴) 수 — 내 변경 전후 증가 0이어야
    cur.execute(
        """SELECT count(*) FROM transactions t JOIN internal_accounts ia ON ia.id=t.internal_account_id
            WHERE t.entity_id=%s AND ia.is_active=false""",
        (KOREA,),
    )
    base_orphan = cur.fetchone()[0]
    print(f"[baseline] M3 전 기존 고아 거래 {base_orphan}건 (M3와 무관, 증가 0이어야)\n")

    # ── ① 평탄화: 빈 그룹 6 ──
    print("[①-a] 빈 그룹 평탄화 (자식 위로 + 비활성)")
    for iid, ename in FLATTEN_EMPTY:
        name, parent, _ = assert_ia(cur, iid, ename, expect_zero_tx=True)
        cur.execute(
            "UPDATE internal_accounts SET parent_id=%s WHERE parent_id=%s AND is_active=true",
            (parent, iid),
        )
        moved = cur.rowcount
        cur.execute("UPDATE internal_accounts SET is_active=false WHERE id=%s", (iid,))
        print(f"    {iid} '{name}' → 자식 {moved}개 부모({parent})로, 그룹 비활성")

    # ── ① 평탄화: 이중역할 2 ──
    print("\n[①-b] 이중역할 그룹 평탄화 (자식 위로 + '기타 X' 리네임, 노드 유지)")
    for iid, ename, newname in FLATTEN_DUAL:
        name, parent, tx = assert_ia(cur, iid, ename)
        cur.execute(
            "UPDATE internal_accounts SET parent_id=%s WHERE parent_id=%s AND is_active=true",
            (parent, iid),
        )
        moved = cur.rowcount
        cur.execute("UPDATE internal_accounts SET name=%s WHERE id=%s", (newname, iid))
        print(f"    {iid} '{name}'(직접거래{tx}) → 자식 {moved}개 위로, '{newname}'로 리네임(유지)")

    # ── ② 잡탕 리네임 5 ──
    print("\n[②] 잡탕 리네임 (이름만)")
    for iid, ename, newname in JAPTANG_RENAME:
        name, _, tx = assert_ia(cur, iid, ename)
        cur.execute("UPDATE internal_accounts SET name=%s WHERE id=%s", (newname, iid))
        print(f"    {iid} '{name}'(거래{tx}) → '{newname}'")

    # ── 검증: 재무 불변(거래·분개·표준매핑 카운트 불변) ──
    cur.execute("SELECT count(*) FROM transactions WHERE entity_id=%s", (KOREA,))
    print(f"\n[검증] 코리아 transactions {cur.fetchone()[0]} (불변)")
    cur.execute("SELECT count(*) FROM internal_accounts WHERE entity_id=%s AND is_active=true", (KOREA,))
    print(f"[검증] 코리아 활성 내부계정 {cur.fetchone()[0]} (123 → 117 기대: 빈그룹6 비활성)")
    # 고아 거래 없음(비활성 IA를 가리키는 거래 0)
    cur.execute(
        """SELECT count(*) FROM transactions t JOIN internal_accounts ia ON ia.id=t.internal_account_id
            WHERE t.entity_id=%s AND ia.is_active=false""",
        (KOREA,),
    )
    orphan = cur.fetchone()[0]
    print(f"[검증] 비활성 IA 가리키는 거래(고아) {orphan} (baseline {base_orphan} 유지 기대 — 증가 0)")
    if orphan != base_orphan:
        print("  ⚠️ M3로 새 고아 거래 발생 → ROLLBACK, 중단")
        conn.rollback(); conn.close(); sys.exit(1)

    if apply:
        conn.commit()
        print("\n✅ COMMIT — 코리아 구조 정리 반영됨.")
    else:
        conn.rollback()
        print("\n↩️  ROLLBACK — prod 무변경 (dry-run). 적용하려면 --apply.")
    conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

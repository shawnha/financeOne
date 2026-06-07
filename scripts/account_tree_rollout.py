# 계정 트리 롤아웃 — 리테일(3)·홀세일(13)·HOI(1) 기계적 단계(신규표준+ESA 골격+2025 잠금).
"""
코리아 PoC(M4/M1b/M2)를 다른 법인으로 일반화. 결산 계정별원장 union 으로 도출한 법인별 골격을
entity_standard_accounts 에 등록 + 2025 회계기간 잠금(전역 트리거 이미 바인딩됨).

이 스크립트는 **기계적·저위험** 단계만:
  1. new_standards — 결산에 있으나 DB 미존재 코드 추가(홀세일 25700 가수금). 형제 미러링.
  2. ESA 골격 — 결산 union 코드를 code+gaap → id 해소 후 entity_standard_accounts INSERT. 빈 표준도 유지.
  3. 2025 잠금 — fiscal_period_locks 12행(basis=both). 2026 은 열림(가결산 대조·정렬).

재무 net 0 (ESA·잠금은 거래/분개/표준매핑 불변, new_standards 는 행 추가만).
잎 표준교정·drift 정렬(재무 영향 有)은 별도 스크립트(account_tree_leaves_*.py)에서 결산 대조로.

멱등: 전부 ON CONFLICT DO NOTHING. 기본 dry-run(BEGIN…ROLLBACK), --apply COMMIT.
사용: python3 scripts/account_tree_rollout.py --entity 3 [--apply]
"""
import os
import sys
import datetime
import psycopg2
from dotenv import load_dotenv

load_dotenv(".env")

# 결산 union 골격 (시트명 코드 추출, _chart_extract.py). 빈 표준도 골격으로 유지.
RETAIL_BACKBONE = [
    "10300", "10800", "13500", "14600", "23100", "25100", "25300", "25400", "25500",
    "26000", "26100", "26200", "27500", "33100", "37600", "37800", "40000", "41200",
    "80200", "81100", "81200", "81700", "82100", "83100", "90100", "93000",
]
WHOLESALE_BACKBONE = [
    "10300", "10800", "11400", "11600", "12000", "13100", "13300", "13400", "13500",
    "13600", "14600", "20800", "21200", "21900", "25100", "25300", "25400", "25500",
    "25700", "25900", "26000", "26200", "29300", "33100", "37600", "37800", "40000",
    "40100", "45100", "80200", "80500", "81100", "81200", "81300", "81400", "81500",
    "81600", "81700", "81900", "82000", "82100", "82200", "82400", "82500", "82600",
    "82900", "83000", "83100", "83300", "83700", "84800", "90100", "93000", "93100",
    "96000", "96200",
]

CONFIG = {
    3: {
        "label": "리테일",
        "gaap": "K_GAAP",
        "new_standards": [],  # 26 골격 전부 DB 존재
        "backbone": RETAIL_BACKBONE,
    },
    13: {
        "label": "홀세일",
        "gaap": "K_GAAP",
        # 25700 가수금: 결산엔 있으나 DB 미존재. 형제 미러링(↔25900 선수금=유동부채/credit).
        "new_standards": [("25700", "가수금", "부채", "유동부채", "credit", False)],
        "backbone": WHOLESALE_BACKBONE,
    },
    1: {
        "label": "HOI",
        "gaap": "US_GAAP",
        "new_standards": [],
        # HOI 골격 = QBO US GAAP 85 전부(DB의 활성 US_GAAP 표준). 결산=QuickBooks.
        "backbone": None,  # main 에서 US_GAAP 활성 코드 동적 로드
    },
}
LOCK_MONTHS = [datetime.date(2025, m, 1) for m in range(1, 13)]


def main(entity_id: int, apply: bool) -> None:
    cfg = CONFIG[entity_id]
    gaap = cfg["gaap"]
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    print(f"=== 롤아웃 {cfg['label']}({entity_id}) {gaap} ({'APPLY/COMMIT' if apply else 'DRY-RUN/ROLLBACK'}) ===\n")

    # ── 1. 신규 표준 INSERT (멱등) ──
    print("[1] 신규 표준")
    for code, name, catv, sub, side, vat in cfg["new_standards"]:
        cur.execute(
            """INSERT INTO standard_accounts (code, name, category, subcategory, normal_side, gaap_type, is_vat_taxable, is_active)
               VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE) ON CONFLICT (code, gaap_type) DO NOTHING""",
            (code, name, catv, sub, side, gaap, vat),
        )
        print(f"    {code} {name} ({catv}/{sub}/{side})  rowcount={cur.rowcount}")
    if not cfg["new_standards"]:
        print("    (없음)")

    # ── backbone 코드 확정 ──
    if cfg["backbone"] is None:  # HOI: US_GAAP 활성 전부
        cur.execute("SELECT code FROM standard_accounts WHERE gaap_type=%s AND is_active ORDER BY code", (gaap,))
        backbone = [r[0] for r in cur.fetchall()]
    else:
        backbone = cfg["backbone"]

    # ── 2. ESA 골격: code+gaap → id 해소 후 INSERT ──
    cur.execute(
        "SELECT code, count(*) FROM standard_accounts WHERE code=ANY(%s) AND gaap_type=%s GROUP BY code",
        (backbone, gaap),
    )
    resolved = dict(cur.fetchall())
    missing = [c for c in backbone if c not in resolved]
    ambiguous = [c for c, n in resolved.items() if n > 1]
    print(f"\n[2] ESA 골격 {len(backbone)}코드: 해소 {len(resolved)} 누락={missing or '없음'} 모호={ambiguous or '없음'}")
    if missing or ambiguous:
        print("  ⚠️ 해소 실패 → ROLLBACK"); conn.rollback(); conn.close(); sys.exit(1)
    cur.execute(
        """INSERT INTO entity_standard_accounts (entity_id, standard_account_id, is_backbone, source)
           SELECT %s, sa.id, TRUE, 'settlement' FROM standard_accounts sa
            WHERE sa.code=ANY(%s) AND sa.gaap_type=%s
           ON CONFLICT (entity_id, standard_account_id) DO NOTHING""",
        (entity_id, backbone, gaap),
    )
    ins = cur.rowcount
    cur.execute("SELECT count(*) FROM entity_standard_accounts WHERE entity_id=%s", (entity_id,))
    esa_total = cur.fetchone()[0]
    print(f"    INSERT {ins} → ESA 총 {esa_total} (기대 {len(backbone)})")
    if esa_total != len(backbone):
        print("  ⚠️ ESA 골격 수 불일치 → ROLLBACK"); conn.rollback(); conn.close(); sys.exit(1)

    # ── 3. 2025 잠금 ──
    for period in LOCK_MONTHS:
        cur.execute(
            """INSERT INTO fiscal_period_locks (entity_id, period, basis, note)
               VALUES (%s,%s,'both','2025 동결 (계정트리 롤아웃)')
               ON CONFLICT (entity_id, period, basis) DO NOTHING""",
            (entity_id, period),
        )
    cur.execute("SELECT count(*) FROM fiscal_period_locks WHERE entity_id=%s AND basis='both'", (entity_id,))
    lock_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM fiscal_period_locks WHERE entity_id=%s AND period>=DATE '2026-01-01'", (entity_id,))
    open_locked = cur.fetchone()[0]
    print(f"\n[3] 잠금 {lock_cnt}행 (기대 12) · 2026 잠긴월 {open_locked} (기대 0)")
    if lock_cnt != 12 or open_locked != 0:
        print("  ⚠️ 잠금 불일치 → ROLLBACK"); conn.rollback(); conn.close(); sys.exit(1)

    # ── 검증: 재무 불변 ──
    cur.execute("SELECT count(*) FROM transactions WHERE entity_id=%s", (entity_id,))
    print(f"\n[검증] {cfg['label']} 거래 {cur.fetchone()[0]} (불변)")

    if apply:
        conn.commit(); print("\n✅ COMMIT — 골격+잠금 반영됨.")
    else:
        conn.rollback(); print("\n↩️  ROLLBACK — prod 무변경 (dry-run). --apply 로 적용.")
    conn.close()


if __name__ == "__main__":
    eid = next((int(a) for a in sys.argv if a.isdigit()), None)
    if eid not in CONFIG:
        print("사용: python3 scripts/account_tree_rollout.py --entity {3|13|1} [--apply]"); sys.exit(1)
    main(eid, apply="--apply" in sys.argv)

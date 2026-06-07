# 계정 트리 재설계 M4(표준6 추가·18400 명칭) + M1b(코리아 51 표준 골격 ESA 등록) 적용 스크립트.
"""
정식설계 docs/account-tree-redesign-design.md §3.5·§3.6 (M4) + §1.1·§5.1-step1 (M1b).
codex fix(§7.3): M1b는 표준 +6 INSERT(M4) 뒤 — 코리아 51 중 80800/83101/92200 FK 필요.

- M4 표준 추가 6 (전부 형제 계정 미러링, 자체판단 아님 — read-only 대조 결과):
    80800 퇴직급여(↔80200)·83101 지급수수료구매대행(↔83100)·92200 사업양도이익(↔92900)
    81500 수도광열비(↔81600)·23100 영업권(↔23200)·26100 미지급세금(세금성격↔81700)
  + 18400 명칭 '회사설정계정과목' → '종속기업투자주식' (코드 고정, 순수 재라벨).
- M1b 코리아(2) 51 표준 골격 → entity_standard_accounts INSERT (source='settlement').
  결산 26년 1분기 가결산 계정별원장 union. 빈 표준도 골격으로 유지(롤업 영향 0).

멱등: 표준 INSERT ON CONFLICT(code,gaap_type) DO NOTHING, ESA INSERT ON CONFLICT(entity,std) DO NOTHING.
기본 dry-run(BEGIN…ROLLBACK). 실제 prod 반영은 --apply 플래그(COMMIT) + 명시승인 후에만.

사용:
  python3 scripts/account_tree_m4_m1b_korea.py            # dry-run (prod 무변경)
  python3 scripts/account_tree_m4_m1b_korea.py --apply    # prod COMMIT
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

KOREA_ENTITY_ID = 2

# M4 — 신규 표준 6 (code, name, category, subcategory, normal_side, is_vat_taxable). 전부 K_GAAP.
NEW_STANDARDS = [
    ("80800", "퇴직급여",          "비용", "판매관리비", "debit",  False),  # ↔ 80200 직원급여
    ("83101", "지급수수료(구매대행)", "비용", "판매관리비", "debit",  True),   # ↔ 83100 지급수수료
    ("92200", "사업양도이익",        "수익", "영업외수익", "credit", True),   # ↔ 92900 국고보조금수익
    ("81500", "수도광열비",          "비용", "판매관리비", "debit",  True),   # ↔ 81600 전력비
    ("23100", "영업권",            "자산", "기타비유동", "debit",  True),   # ↔ 23200 임차보증금
    ("26100", "미지급세금",          "부채", "유동부채",  "credit", False),  # ↔ 81700 세금과공과금(세금성격)
]

# M4 — 18400 명칭 정정 (코드 고정, FK 무영향)
RENAME_18400 = ("18400", "회사설정계정과목", "종속기업투자주식")

# M1b — 코리아(2) 51 표준 골격 코드 (26 Q1 가결산 계정별원장 union, read-only 추출)
KOREA_BACKBONE_51 = [
    # 자산 9
    "10300", "10800", "12000", "13100", "13500", "13600", "14600", "17900", "18400",
    # 부채 8
    "21200", "21900", "25100", "25400", "25500", "25900", "26200", "27500",
    # 자본 6
    "30300", "31500", "33100", "34100", "37600", "37800",
    # 매출 5
    "40000", "40100", "40200", "41200", "45100",
    # 판관비 17
    "80200", "80800", "81100", "81200", "81300", "81600", "81700", "81900",
    "82100", "82400", "82600", "82900", "83000", "83100", "83101", "83300", "83900",
    # 영업외/기타 6
    "90100", "92200", "92900", "93000", "96000", "96200",
]


def main(apply: bool) -> None:
    assert len(KOREA_BACKBONE_51) == 51, f"backbone 코드 수 {len(KOREA_BACKBONE_51)} != 51"
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    print(f"=== 계정 트리 M4+M1b ({'APPLY/COMMIT' if apply else 'DRY-RUN/ROLLBACK'}) ===\n")

    # ── M4-a: 신규 표준 6 INSERT (멱등) ──
    print("[M4-a] 신규 표준 6 INSERT")
    for code, name, cat, sub, side, vat in NEW_STANDARDS:
        cur.execute(
            """INSERT INTO standard_accounts
                   (code, name, category, subcategory, normal_side, gaap_type, is_vat_taxable, is_active)
               VALUES (%s, %s, %s, %s, %s, 'K_GAAP', %s, TRUE)
               ON CONFLICT (code, gaap_type) DO NOTHING""",
            (code, name, cat, sub, side, vat),
        )
        print(f"    {code} {name:18} {cat}/{sub}/{side}/vat={vat}  (rowcount={cur.rowcount})")

    # ── M4-b: 18400 명칭 정정 ──
    code, old, new = RENAME_18400
    cur.execute(
        "UPDATE standard_accounts SET name=%s WHERE code=%s AND gaap_type='K_GAAP' AND name=%s",
        (new, code, old),
    )
    print(f"\n[M4-b] {code} 명칭 '{old}' → '{new}'  (rowcount={cur.rowcount})")

    # ── 검증: 코리아 51 코드가 전부 단일 K_GAAP 표준으로 해소되는가 ──
    cur.execute(
        """SELECT code, count(*) FROM standard_accounts
            WHERE code = ANY(%s) AND gaap_type='K_GAAP'
            GROUP BY code""",
        (KOREA_BACKBONE_51,),
    )
    resolved = dict(cur.fetchall())
    missing = [c for c in KOREA_BACKBONE_51 if c not in resolved]
    ambiguous = [c for c, n in resolved.items() if n > 1]
    print(f"\n[검증] 코리아 51 해소: {len(resolved)}/51, 누락={missing or '없음'}, 모호={ambiguous or '없음'}")
    if missing or ambiguous:
        print("  ⚠️ 해소 실패 → ROLLBACK, 중단")
        conn.rollback()
        conn.close()
        sys.exit(1)

    # ── M1b: 코리아 51 골격 → entity_standard_accounts INSERT (멱등) ──
    cur.execute(
        """INSERT INTO entity_standard_accounts (entity_id, standard_account_id, is_backbone, source)
           SELECT %s, sa.id, TRUE, 'settlement'
             FROM standard_accounts sa
            WHERE sa.code = ANY(%s) AND sa.gaap_type='K_GAAP'
           ON CONFLICT (entity_id, standard_account_id) DO NOTHING""",
        (KOREA_ENTITY_ID, KOREA_BACKBONE_51),
    )
    print(f"\n[M1b] 코리아({KOREA_ENTITY_ID}) ESA INSERT  (rowcount={cur.rowcount})")
    cur.execute(
        "SELECT count(*) FROM entity_standard_accounts WHERE entity_id=%s",
        (KOREA_ENTITY_ID,),
    )
    esa_total = cur.fetchone()[0]
    print(f"      코리아 ESA 총 골격 행 = {esa_total} (기대 51)")

    if esa_total != 51:
        print("  ⚠️ ESA 골격 행 != 51 → ROLLBACK, 중단")
        conn.rollback()
        conn.close()
        sys.exit(1)

    # ── 마무리 ──
    if apply:
        conn.commit()
        print("\n✅ COMMIT 완료 — prod 반영됨.")
    else:
        conn.rollback()
        print("\n↩️  ROLLBACK — prod 무변경 (dry-run). 적용하려면 --apply.")
    conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

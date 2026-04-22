"""K-GAAP 표준계정 seed를 standard_accounts에 UPSERT.

- 충돌하는 code(12건, 모두 IA=0 TX=0 미사용): name/name_en/category 덮어쓰기
- 신규 code(57건): INSERT
- 기존 code 중 seed에 없는 38건 미사용: 그대로 유지 (나중에 별도 정리)
- 기존 사용 중 17건(EX: 50200 급여 등): 새 K-GAAP code와 code 충돌 없음 → 유지
  (internal_accounts 재매핑은 별도 스크립트 apply_kgaap_remap.py)

normal_side 자동 산출:
- 자산/비용 → debit
- 부채/자본/수익 → credit

사용: python3 -m backend.database.seeds.apply_kgaap_seed
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
load_dotenv()

from backend.database.seeds.standard_accounts_kgaap import KGAAP_SEED


NORMAL_SIDE = {"자산": "debit", "비용": "debit", "부채": "credit", "자본": "credit", "수익": "credit"}

SUBCATEGORY_MAP = {
    "당좌자산": "당좌자산",
    "재고자산": "재고자산",
    "투자자산": "투자자산",
    "유형자산": "유형자산",
    "기타비유동자산": "기타비유동",
    "유동부채": "유동부채",
    "비유동부채": "비유동부채",
    "자본금": "자본금",
    "자본잉여금": "자본잉여금",
    "이익잉여금": "이익잉여금",
    "매출": "매출",
    "매출원가": "매출원가",
    "판매관리비": "판매관리비",
    "영업외수익": "영업외수익",
    "영업외비용": "영업외비용",
    "법인세비용": "법인세비용",
    "결산": "결산",
}


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    inserted = 0
    updated = 0
    for i, row in enumerate(KGAAP_SEED):
        code = row["code"]
        name = row["name"]
        name_en = row.get("name_en")
        category = row["category"]
        subcategory = SUBCATEGORY_MAP.get(row.get("sub_category", ""), row.get("sub_category"))
        normal = NORMAL_SIDE.get(category, "debit")
        sort_order = int(code) if code.isdigit() else i * 10

        cur.execute(
            """
            INSERT INTO standard_accounts
                (code, name, name_en, category, subcategory, normal_side, sort_order, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                name_en = EXCLUDED.name_en,
                category = EXCLUDED.category,
                subcategory = EXCLUDED.subcategory,
                normal_side = EXCLUDED.normal_side,
                sort_order = EXCLUDED.sort_order,
                is_active = TRUE
            RETURNING xmax = 0 AS inserted
            """,
            [code, name, name_en, category, subcategory, normal, sort_order],
        )
        was_insert = cur.fetchone()[0]
        if was_insert:
            inserted += 1
        else:
            updated += 1

    conn.commit()
    print(f"✓ INSERT: {inserted}")
    print(f"✓ UPDATE: {updated}")

    # 결과 요약
    cur.execute("""
        SELECT category, COUNT(*) FROM standard_accounts
        WHERE is_active = TRUE GROUP BY category ORDER BY category
    """)
    print("\nstandard_accounts 현황 (is_active=TRUE):")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")
    cur.execute("SELECT COUNT(*) FROM standard_accounts WHERE name_en IS NOT NULL")
    print(f"  name_en 매핑됨: {cur.fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()

"""HOI 2025 확정 BS/PL 기반 US-GAAP standard_accounts 갱신.

기존 generic US-GAAP 61개(gaap_mapping 추출)는 placeholder 였음. HOI 실제 운영
계정(QBO 양식)으로 교체. parent_code 트리는 application-level 로 보존.

Usage:
    python -m backend.scripts.import_hoi_finalized_coa            # dry-run
    python -m backend.scripts.import_hoi_finalized_coa --apply    # 실제 적용
    python -m backend.scripts.import_hoi_finalized_coa --apply --replace-generic
        # 기존 generic US-GAAP rows 비활성화 (is_active=false)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.database.connection import init_pool, get_db
from backend.scripts.seed_data.hoi_coa_2025 import HOI_COA


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제 INSERT/UPDATE 실행")
    parser.add_argument("--replace-generic", action="store_true",
                        help="기존 generic US-GAAP rows (HOI- prefix 가 아닌) 비활성화")
    args = parser.parse_args()

    asyncio.run(init_pool())
    cur = next(get_db()).cursor()
    cur.execute("SET search_path TO financeone, public")

    # 현재 US-GAAP 상태
    cur.execute("SELECT COUNT(*) FROM standard_accounts WHERE gaap_type='US_GAAP'")
    us_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM standard_accounts WHERE gaap_type='US_GAAP' AND code LIKE 'HOI-%'")
    hoi_existing = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM standard_accounts WHERE gaap_type='US_GAAP' AND code NOT LIKE 'HOI-%'")
    generic_existing = cur.fetchone()[0]

    print("=" * 70)
    print("HOI Finalized COA Import")
    print("=" * 70)
    print(f"Source: BS_123125_Finalized_032026.pdf + PL_123125_Finalized_031926.pdf")
    print(f"Target: standard_accounts WHERE gaap_type='US_GAAP'")
    print()
    print(f"현재 US_GAAP rows: {us_total}")
    print(f"  HOI-* (이미 import 됨): {hoi_existing}")
    print(f"  generic (기존 placeholder): {generic_existing}")
    print()
    print(f"Plan: insert/update {len(HOI_COA)} HOI rows")
    print(f"  --replace-generic: {'YES' if args.replace_generic else 'no — generic 그대로 유지'}")
    print()

    # 카테고리/계층 통계
    by_cat: dict[str, int] = {}
    leaf = 0
    parent = 0
    for code, name, cat, side, pcode, sort_o in HOI_COA:
        by_cat[cat] = by_cat.get(cat, 0) + 1
        if pcode is None or any(c[4] == code for c in HOI_COA):
            parent += 1
        else:
            leaf += 1
    print("By category:")
    for c, n in sorted(by_cat.items()):
        print(f"  {c:14s} {n}")
    print(f"  (parent 계정 {parent} / leaf 계정 {leaf})")
    print()
    print("Sample new rows:")
    for code, name, cat, side, pcode, sort_o in HOI_COA[:5]:
        print(f"  {code:14s} {name:50s}  parent={pcode}")
    print(f"  ... ({len(HOI_COA)-5} more)")
    print()

    if not args.apply:
        print("DRY-RUN — to apply: rerun with --apply")
        cur.close()
        return 0

    inserted = 0
    updated = 0
    for code, name, cat, side, pcode, sort_o in HOI_COA:
        cur.execute(
            """
            INSERT INTO standard_accounts (code, name, category, normal_side, parent_code, sort_order, gaap_type, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 'US_GAAP', true)
            ON CONFLICT (code, gaap_type) DO UPDATE
                SET name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    normal_side = EXCLUDED.normal_side,
                    parent_code = EXCLUDED.parent_code,
                    sort_order = EXCLUDED.sort_order,
                    is_active = true
            RETURNING (xmax = 0) AS inserted
            """,
            [code, name, cat, side, pcode, sort_o],
        )
        was_insert = cur.fetchone()[0]
        if was_insert:
            inserted += 1
        else:
            updated += 1

    deactivated = 0
    if args.replace_generic:
        cur.execute(
            """
            UPDATE standard_accounts
               SET is_active = false
             WHERE gaap_type = 'US_GAAP' AND code NOT LIKE 'HOI-%'
            """
        )
        deactivated = cur.rowcount or 0

    cur.connection.commit()
    cur.close()

    print(f"DONE — inserted: {inserted}, updated: {updated}, deactivated (generic): {deactivated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

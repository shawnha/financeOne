"""도팜인 25년 계정별원장 시트명 → HOW(한아원홀세일) internal_accounts seed.

도팜인이 한아원홀세일로 사명변경. 기존 53시트 = 운영 중인 53개 계정.
시트명 '29_복리후생비(81100)' → internal_account(name='복리후생비', code='81100',
standard_account_id=lookup(81100)) 자동 생성.

Usage:
    python -m backend.scripts.seed_how_from_dopamin_25            # dry-run
    python -m backend.scripts.seed_how_from_dopamin_25 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

import xlrd

from backend.database.connection import init_pool, get_db


LEDGER_PATH = "/Users/admin/Documents/HanahOneAll/도팜인/재무자료/25년 계정별원장.xls"
SHEET_RE = re.compile(r"^(\d+)_(.+)\((\d{5})\)$")  # '29_복리후생비(81100)'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--entity-code", default="HOW", help="대상 entity code (default: HOW)")
    args = parser.parse_args()

    print("=" * 70)
    print(f"HOW internal_accounts seed (from 도팜인 25년 ledger)")
    print("=" * 70)

    wb = xlrd.open_workbook(LEDGER_PATH, on_demand=True)
    accounts: list[tuple[int, str, str]] = []  # (sort_order, name, std_code)
    for n in wb.sheet_names():
        m = SHEET_RE.match(n)
        if not m:
            continue
        sort_o, name, std_code = int(m.group(1)), m.group(2), m.group(3)
        accounts.append((sort_o, name, std_code))

    print(f"Source: {LEDGER_PATH}")
    print(f"Found: {len(accounts)} accounts in sheet names")
    print()

    asyncio.run(init_pool())
    cur = next(get_db()).cursor()
    cur.execute("SET search_path TO financeone, public")

    # entity 검증
    cur.execute("SELECT id, name FROM entities WHERE code = %s AND is_active = true", [args.entity_code])
    row = cur.fetchone()
    if not row:
        print(f"ERROR: entity {args.entity_code} not found / inactive")
        cur.close()
        return 1
    entity_id, entity_name = row
    print(f"Target entity: {args.entity_code} (id={entity_id}, {entity_name})")

    # 기존 internal_accounts 확인
    cur.execute(
        "SELECT COUNT(*) FROM internal_accounts WHERE entity_id = %s AND is_active = true",
        [entity_id],
    )
    existing = cur.fetchone()[0]
    print(f"Existing active internal_accounts: {existing}")
    print()

    # std_code → standard_account_id (K-GAAP)
    cur.execute("SELECT id, code FROM standard_accounts WHERE gaap_type='K_GAAP'")
    std_id_by_code = {code: sid for sid, code in cur.fetchall()}

    plan = []
    missing_std = []
    for sort_o, name, std_code in accounts:
        std_id = std_id_by_code.get(std_code)
        if std_id is None:
            missing_std.append((name, std_code))
            continue
        plan.append((sort_o, name, std_code, std_id))

    print(f"Plan: insert {len(plan)} internal_accounts (missing std_code: {len(missing_std)})")
    if missing_std:
        print("  Missing standard codes (skip):")
        for n, c in missing_std:
            print(f"    {c}  {n}")
    print()
    print("Sample (first 8):")
    for sort_o, name, std_code, std_id in plan[:8]:
        print(f"  sort={sort_o:3d}  code={std_code}  name={name:25s}  std_id={std_id}")
    print()

    if not args.apply:
        print("DRY-RUN — to apply: rerun with --apply")
        cur.close()
        return 0

    inserted = 0
    skipped = 0
    for sort_o, name, std_code, std_id in plan:
        # internal code = std_code (same convention as seed.py / 다른 법인)
        cur.execute(
            """
            INSERT INTO internal_accounts
                (entity_id, code, name, standard_account_id, parent_id, sort_order, is_active)
            VALUES (%s, %s, %s, %s, NULL, %s, true)
            ON CONFLICT (entity_id, code) DO NOTHING
            RETURNING id
            """,
            [entity_id, std_code, name, std_id, sort_o],
        )
        if cur.fetchone():
            inserted += 1
        else:
            skipped += 1

    cur.connection.commit()
    cur.close()
    print(f"DONE — inserted: {inserted}, skipped(conflict): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

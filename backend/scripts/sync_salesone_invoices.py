"""salesone.orders → financeone.invoices 자동 동기화 CLI.

사용:
    python -m backend.scripts.sync_salesone_invoices --entity 2 \
        --start 2026-01-01 --end 2026-01-31 --dry-run

    python -m backend.scripts.sync_salesone_invoices --entity 2 \
        --start 2026-01-01 --end 2026-01-31 --commit
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--platforms", nargs="*", help="external_source 필터 (NAVER/SHOPIFY/...)")
    parser.add_argument("--keep-existing", action="store_true",
                        help="기존 회계법인 원장 import NAVER invoices 유지 (중복 가능)")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    from backend.services.integrations.salesone import sync_orders_to_invoices

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        result = sync_orders_to_invoices(
            conn,
            entity_id=args.entity,
            start_date=start, end_date=end,
            platforms=args.platforms,
            skip_existing_naver=not args.keep_existing,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()

    print(f"\n=== salesone → invoices sync (entity={args.entity}) ===")
    print(f"  company_id: {result['company_id']}")
    print(f"  period: {result['period']}")
    print(f"  모드: {'DRY-RUN' if args.dry_run else 'COMMIT'}\n")
    print(f"  fetched orders:        {result['fetched']:>5}")
    print(f"  invoices created:      {result['created']:>5}")
    print(f"  skipped (duplicate):   {result['skipped_dup']:>5}")
    print(f"  skipped (no decision): {result['skipped_no_decision']:>5}")
    print(f"  old invoices deleted:  {result['deleted_old']:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

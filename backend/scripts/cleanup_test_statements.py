"""중복/테스트 statement 정리.

삭제 대상 (사용자 승인 2026-04-29):
- id 2: 한아원코리아 2026 1-1월 (단월 테스트)
- id 3: 한아원코리아 2025 1-12월 (결산자료 import 후 재생성 예정)
- id 5: HOI 2026 1-3월 (12 가 1-4월 최신)
- id 11: HOI consolidated 2026 1-3월 (13 가 1-4월 최신)
- id 14: HOI 2026 1-12월 (4월까지만 데이터)
- id 15: HOI 2026 1-1월 (단월 테스트)

CASCADE: financial_statement_line_items 도 함께 삭제됨 (FK ON DELETE CASCADE).
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DELETE_IDS = [2, 3, 5, 11, 14, 15]


def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")

        # Pre-check
        cur.execute(
            """
            SELECT fs.id, e.name, fs.fiscal_year, fs.start_month, fs.end_month, fs.is_consolidated
            FROM financial_statements fs
            LEFT JOIN entities e ON fs.entity_id = e.id
            WHERE fs.id = ANY(%s)
            ORDER BY fs.id
            """,
            [DELETE_IDS],
        )
        rows = cur.fetchall()
        print(f"삭제 예정 ({len(rows)}/{len(DELETE_IDS)} 건):")
        for r in rows:
            print(f"  - id={r[0]} {r[1]} {r[2]}년 {r[3]}-{r[4]}월 consolidated={r[5]}")

        # Line items count
        cur.execute(
            "SELECT statement_id, COUNT(*) FROM financial_statement_line_items WHERE statement_id = ANY(%s) GROUP BY statement_id",
            [DELETE_IDS],
        )
        line_counts = dict(cur.fetchall())
        for sid in DELETE_IDS:
            print(f"  - line_items for id={sid}: {line_counts.get(sid, 0)} rows")

        # Delete line items first (explicit, FK CASCADE 작동 확인 어려운 경우 대비)
        cur.execute(
            "DELETE FROM financial_statement_line_items WHERE statement_id = ANY(%s)",
            [DELETE_IDS],
        )
        line_deleted = cur.rowcount

        # Delete statements
        cur.execute(
            "DELETE FROM financial_statements WHERE id = ANY(%s)",
            [DELETE_IDS],
        )
        stmt_deleted = cur.rowcount

        conn.commit()
        cur.close()

        print(f"\n✓ {stmt_deleted} statements + {line_deleted} line_items 삭제 완료")
    except Exception as e:
        conn.rollback()
        print(f"✗ 실패: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

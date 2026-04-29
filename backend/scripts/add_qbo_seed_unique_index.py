"""mapping_rules 에 qbo_seed 용 partial unique index 추가.

QBO seed_mapping_rules 의 ON CONFLICT (entity_id, counterparty_pattern)
WHERE source = 'qbo_seed' 가 작동하려면 정확히 matching 하는 partial unique
index 필요.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_mapping_rules_qbo_seed_unique
ON financeone.mapping_rules (entity_id, counterparty_pattern)
WHERE source = 'qbo_seed'
"""


def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")
        cur.execute(SQL)
        conn.commit()
        cur.close()
        print("✓ idx_mapping_rules_qbo_seed_unique created (or already exists)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

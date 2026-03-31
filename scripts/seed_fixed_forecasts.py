"""한아원코리아(entity_id=2) 2026년 1월 고정비 seed.

모두 is_recurring=true, payment_method='bank', expected_day 지정.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
import psycopg2

load_dotenv()

FIXED_EXPENSES = [
    {"category": "급여", "amount": 29_263_090, "day": 24},
    {"category": "임차료", "subcategory": "스파크플러스", "amount": 891_000, "day": 2},
    {"category": "임차료", "subcategory": "기업정인자산", "amount": 8_816_940, "day": 24},
    {"category": "4대보험", "amount": 4_282_720, "day": 10},
    {"category": "원천세", "amount": 1_004_270, "day": 3},
    {"category": "사무실 청소", "amount": 386_800, "day": 24},
]

ENTITY_ID = 2
YEAR = 2026
MONTH = 1


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    inserted = 0
    for item in FIXED_EXPENSES:
        cur.execute(
            """
            INSERT INTO forecasts
                (entity_id, year, month, category, subcategory, type,
                 forecast_amount, is_recurring, expected_day, payment_method)
            VALUES (%s, %s, %s, %s, %s, 'out', %s, true, %s, 'bank')
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            [ENTITY_ID, YEAR, MONTH,
             item["category"], item.get("subcategory"),
             item["amount"], item["day"]],
        )
        row = cur.fetchone()
        if row:
            inserted += 1
            print(f"  + {item['category']}: {item['amount']:,.0f}원 ({item['day']}일)")
        else:
            print(f"  = {item['category']}: already exists")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone: {inserted} inserted, {len(FIXED_EXPENSES) - inserted} skipped")


if __name__ == "__main__":
    main()

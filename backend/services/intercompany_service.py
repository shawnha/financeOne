"""내부거래 감지 + 상계 서비스

자동 감지: (entity_a, entity_b, amount, date±1일, 반대 타입) 매칭
확인 후 transactions.is_intercompany 설정
"""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection


def detect_intercompany(
    conn: PgConnection,
    entity_ids: list[int],
    start_date: date,
    end_date: date,
    date_tolerance_days: int = 1,
) -> list[dict]:
    """내부거래 자동 감지. 이미 매칭된 거래는 제외.

    Returns: [{"transaction_a_id", "transaction_b_id", "entity_a_id",
               "entity_b_id", "amount", "match_date", "description"}]
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t1.id AS tx_a, t2.id AS tx_b,
               t1.entity_id AS entity_a, t2.entity_id AS entity_b,
               t1.amount, t1.date AS match_date,
               t1.counterparty AS desc_a, t2.counterparty AS desc_b
        FROM transactions t1
        JOIN transactions t2
          ON t1.entity_id != t2.entity_id
          AND t1.amount = t2.amount
          AND t1.type != t2.type
          AND ABS(t1.date - t2.date) <= %s
          AND t1.id < t2.id
        WHERE t1.entity_id = ANY(%s) AND t2.entity_id = ANY(%s)
          AND t1.date >= %s AND t1.date <= %s
          AND t1.is_intercompany = FALSE
          AND t2.is_intercompany = FALSE
        ORDER BY t1.date DESC, t1.amount DESC
        """,
        [date_tolerance_days, entity_ids, entity_ids, start_date, end_date],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    # intercompany_pairs 테이블에 저장
    results = []
    inner_cur = conn.cursor()
    for row in rows:
        # 이미 pair에 존재하는지 확인
        inner_cur.execute(
            """
            SELECT id FROM intercompany_pairs
            WHERE (transaction_a_id = %s AND transaction_b_id = %s)
               OR (transaction_a_id = %s AND transaction_b_id = %s)
            """,
            [row["tx_a"], row["tx_b"], row["tx_b"], row["tx_a"]],
        )
        if inner_cur.fetchone():
            continue

        inner_cur.execute(
            """
            INSERT INTO intercompany_pairs
                (entity_a_id, entity_b_id, transaction_a_id, transaction_b_id,
                 amount, currency, match_date, match_method, description)
            VALUES (%s, %s, %s, %s, %s, 'KRW', %s, 'auto', %s)
            RETURNING id
            """,
            [
                row["entity_a"], row["entity_b"],
                row["tx_a"], row["tx_b"],
                float(row["amount"]), row["match_date"],
                f"{row['desc_a']} ↔ {row['desc_b']}",
            ],
        )
        pair_id = inner_cur.fetchone()[0]
        results.append({**row, "pair_id": pair_id})

    inner_cur.close()
    return results


def confirm_pair(conn: PgConnection, pair_id: int) -> dict:
    """내부거래 쌍 확인. transactions에 is_intercompany 설정."""
    cur = conn.cursor()

    cur.execute(
        "SELECT transaction_a_id, transaction_b_id FROM intercompany_pairs WHERE id = %s",
        [pair_id],
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise ValueError(f"Pair {pair_id} not found")

    tx_a, tx_b = row

    cur.execute(
        "UPDATE intercompany_pairs SET is_confirmed = TRUE WHERE id = %s",
        [pair_id],
    )

    if tx_a:
        cur.execute(
            "UPDATE transactions SET is_intercompany = TRUE, intercompany_pair_id = %s WHERE id = %s",
            [pair_id, tx_a],
        )
    if tx_b:
        cur.execute(
            "UPDATE transactions SET is_intercompany = TRUE, intercompany_pair_id = %s WHERE id = %s",
            [pair_id, tx_b],
        )

    cur.close()
    return {"pair_id": pair_id, "confirmed": True}


def get_eliminations(
    conn: PgConnection,
    entity_ids: list[int],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """확정된 내부거래 상계 항목 조회."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ip.id, ip.entity_a_id, ip.entity_b_id,
               ip.transaction_a_id, ip.transaction_b_id,
               ip.amount, ip.currency, ip.match_date, ip.description
        FROM intercompany_pairs ip
        WHERE ip.is_confirmed = TRUE
          AND ip.entity_a_id = ANY(%s) AND ip.entity_b_id = ANY(%s)
          AND ip.match_date >= %s AND ip.match_date <= %s
        ORDER BY ip.match_date
        """,
        [entity_ids, entity_ids, start_date, end_date],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows

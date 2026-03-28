"""거래 ↔ 내부계정 매핑 서비스 — 자동 매핑 + 학습"""


def auto_map_transaction(cur, *, entity_id: int, counterparty: str | None) -> dict | None:
    """counterparty로 mapping_rules 정확 일치 조회. 매칭 시 dict 반환, 미매칭 시 None."""
    if not counterparty:
        return None

    cur.execute(
        """
        SELECT internal_account_id, standard_account_id, confidence
        FROM mapping_rules
        WHERE entity_id = %s AND counterparty_pattern = %s AND confidence >= 0.8
        ORDER BY confidence DESC, hit_count DESC
        LIMIT 1
        """,
        [entity_id, counterparty],
    )
    row = cur.fetchone()
    if not row:
        return None

    return {
        "internal_account_id": row[0],
        "standard_account_id": row[1],
        "confidence": float(row[2]),
    }

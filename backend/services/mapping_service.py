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


def learn_mapping_rule(cur, *, entity_id: int, counterparty: str | None, internal_account_id: int) -> None:
    """사용자의 계정 선택을 mapping_rules에 UPSERT."""
    if not counterparty:
        return

    cur.execute(
        """
        SELECT id, internal_account_id, confidence, hit_count
        FROM mapping_rules
        WHERE entity_id = %s AND counterparty_pattern = %s
        LIMIT 1
        """,
        [entity_id, counterparty],
    )
    existing = cur.fetchone()

    if existing:
        rule_id, existing_account_id, confidence, hit_count = existing
        if existing_account_id == internal_account_id:
            new_confidence = min(1.0, float(confidence) + 0.05)
            cur.execute(
                "UPDATE mapping_rules SET hit_count = %s, confidence = %s, updated_at = NOW() WHERE id = %s",
                [hit_count + 1, new_confidence, rule_id],
            )
        else:
            cur.execute(
                "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
                [internal_account_id],
            )
            std_row = cur.fetchone()
            std_id = std_row[0] if std_row else None

            cur.execute(
                """
                UPDATE mapping_rules
                SET internal_account_id = %s, standard_account_id = %s,
                    confidence = 0.8, hit_count = 1, updated_at = NOW()
                WHERE id = %s
                """,
                [internal_account_id, std_id, rule_id],
            )
    else:
        cur.execute(
            "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
            [internal_account_id],
        )
        std_row = cur.fetchone()
        std_id = std_row[0] if std_row else None

        cur.execute(
            """
            INSERT INTO mapping_rules (entity_id, counterparty_pattern, internal_account_id, standard_account_id, confidence, hit_count)
            VALUES (%s, %s, %s, %s, 0.8, 1)
            """,
            [entity_id, counterparty, internal_account_id, std_id],
        )

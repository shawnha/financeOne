"""내부계정 재매핑 배치 서비스 — CQ-1 배치 최적화 + ARCH-4 Slack fallback."""

from psycopg2.extensions import connection as PgConnection
from backend.utils.db import fetch_all


def load_all_mapping_rules(cur, entity_id: int) -> dict:
    """mapping_rules 일괄 로드 → {counterparty_pattern: {internal_account_id, standard_account_id, confidence}}"""
    cur.execute(
        """
        SELECT counterparty_pattern, internal_account_id, standard_account_id, confidence
        FROM mapping_rules
        WHERE entity_id = %s
        ORDER BY confidence DESC, hit_count DESC
        """,
        [entity_id],
    )
    rules = {}
    for row in cur.fetchall():
        pattern = row[0].strip().lower()
        if pattern not in rules:  # highest confidence first
            rules[pattern] = {
                "internal_account_id": row[1],
                "standard_account_id": row[2],
                "confidence": float(row[3]),
            }
    return rules


def query_remap_candidates(cur, entity_id: int) -> list[dict]:
    """재매핑 대상 거래 조회 (manual/confirmed 제외, 중복 제외)."""
    cur.execute(
        """
        SELECT id, counterparty, internal_account_id, mapping_source
        FROM transactions
        WHERE entity_id = %s
          AND counterparty IS NOT NULL
          AND counterparty != ''
          AND is_duplicate = false
          AND (mapping_source IS NULL OR mapping_source NOT IN ('manual', 'confirmed'))
        ORDER BY date, id
        """,
        [entity_id],
    )
    return fetch_all(cur)


def slack_fallback_mapping(cur, tx_id: int, entity_id: int) -> dict | None:
    """Slack 매칭 테이블에서 내부계정 추론 (ARCH-4)."""
    cur.execute(
        """
        SELECT sm.parsed_structured
        FROM transaction_slack_match tsm
        JOIN slack_messages sm ON tsm.slack_message_id = sm.id
        WHERE tsm.transaction_id = %s
          AND tsm.is_confirmed = true
        ORDER BY tsm.match_confidence DESC
        LIMIT 1
        """,
        [tx_id],
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return None

    parsed = row[0] if isinstance(row[0], dict) else {}
    item_desc = parsed.get("item_description", "")
    if not item_desc:
        return None

    # Try to find a mapping_rule matching the item description
    cur.execute(
        """
        SELECT internal_account_id, standard_account_id, confidence
        FROM mapping_rules
        WHERE entity_id = %s AND counterparty_pattern ILIKE %s
        ORDER BY confidence DESC, hit_count DESC
        LIMIT 1
        """,
        [entity_id, f"%{item_desc}%"],
    )
    rule = cur.fetchone()
    if rule:
        return {
            "internal_account_id": rule[0],
            "standard_account_id": rule[1],
            "confidence": float(rule[2]),
        }
    return None


def remap_transactions(conn: PgConnection, entity_id: int, dry_run: bool = False) -> dict:
    """내부계정 재매핑 배치 실행."""
    cur = conn.cursor()

    # 1. mapping_rules 일괄 로드 (CQ-1)
    rules = load_all_mapping_rules(cur, entity_id)

    # 2. 재매핑 대상 조회
    candidates = query_remap_candidates(cur, entity_id)

    mapped = 0
    skipped = 0
    details = []

    for tx in candidates:
        counterparty = (tx["counterparty"] or "").strip().lower()
        current_ia = tx["internal_account_id"]

        # Priority 1: mapping_rules (in-memory)
        mapping = rules.get(counterparty)

        # Priority 2: Slack fallback (ARCH-4)
        if not mapping:
            mapping = slack_fallback_mapping(cur, tx["id"], entity_id)

        if not mapping:
            skipped += 1
            continue

        new_ia = mapping["internal_account_id"]
        if new_ia == current_ia:
            skipped += 1
            continue

        if not dry_run:
            cur.execute(
                """
                UPDATE transactions
                SET internal_account_id = %s,
                    standard_account_id = %s,
                    mapping_confidence = %s,
                    mapping_source = 'rule',
                    updated_at = NOW()
                WHERE id = %s
                """,
                [new_ia, mapping["standard_account_id"], mapping["confidence"], tx["id"]],
            )

        mapped += 1
        details.append({
            "tx_id": tx["id"],
            "counterparty": tx["counterparty"],
            "old_internal_account_id": current_ia,
            "new_internal_account_id": new_ia,
            "confidence": mapping["confidence"],
        })

    if not dry_run:
        conn.commit()

    cur.close()

    return {
        "total_candidates": len(candidates),
        "mapped": mapped,
        "skipped": skipped,
        "dry_run": dry_run,
        "details": details,
    }

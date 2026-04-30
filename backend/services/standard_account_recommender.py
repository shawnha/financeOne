"""표준계정 자동 추천 — 내부계정 생성 시 표준계정 매핑 추천.

처리 흐름: 상위계정 상속 → 동일 법인 유사계정 → 일상어 사전 → (향후 AI)
"""

import logging

logger = logging.getLogger(__name__)


def recommend_standard_account(
    cur,
    *,
    entity_id: int,
    account_name: str,
    parent_id: int | None = None,
) -> dict | None:
    """내부계정 이름으로 표준계정 추천. 매칭 시 {standard_account_id, confidence, source} 반환."""

    # 1. 상위계정 상속
    if parent_id:
        cur.execute(
            "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
            [parent_id],
        )
        row = cur.fetchone()
        if row and row[0]:
            return {
                "standard_account_id": row[0],
                "confidence": 0.9,
                "source": "parent_inherit",
            }

    # 2. 동일 법인 유사 이름 계정 참조
    cur.execute(
        """
        SELECT standard_account_id, name,
               similarity(name, %s) AS sim
        FROM internal_accounts
        WHERE entity_id = %s
          AND standard_account_id IS NOT NULL
          AND similarity(name, %s) >= 0.3
        ORDER BY sim DESC
        LIMIT 1
        """,
        [account_name, entity_id, account_name],
    )
    row = cur.fetchone()
    if row:
        return {
            "standard_account_id": row[0],
            "confidence": round(float(row[2]) * 0.85, 2),
            "source": "similar_account",
            "matched_name": row[1],
        }

    # 3. 일상어 사전 (standard_account_keywords) — K-GAAP 키워드만 등록되어 있어
    # US_CORP entity (HOI) 에는 적용하지 않는다 (잘못된 K-GAAP id 추천 방지).
    cur.execute("SELECT type FROM entities WHERE id = %s", [entity_id])
    ent = cur.fetchone()
    if ent and ent[0] == "US_CORP":
        return None
    cur.execute(
        """
        SELECT sak.standard_account_id, sak.confidence, sak.keyword
        FROM standard_account_keywords sak
        WHERE %s ILIKE '%%' || sak.keyword || '%%'
        ORDER BY length(sak.keyword) DESC, sak.confidence DESC
        LIMIT 1
        """,
        [account_name],
    )
    row = cur.fetchone()
    if row:
        return {
            "standard_account_id": row[0],
            "confidence": float(row[1]),
            "source": "keyword_dict",
            "matched_keyword": row[2],
        }

    return None

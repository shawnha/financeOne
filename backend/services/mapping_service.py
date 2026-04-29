"""거래 ↔ 내부계정 매핑 서비스 — 5단계 캐스케이드 자동 매핑 + 학습"""

import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

SIMILAR_THRESHOLD = 0.3
AI_MODEL = "claude-haiku-4-5-20251001"


# ── 1. 정확 일치 ──────────────────────────────────────────────


def exact_match(cur, *, entity_id: int, counterparty: str | None, description: str | None = None) -> dict | None:
    """counterparty로 mapping_rules 정확 일치 조회.

    Slack 컨텍스트(description_pattern)가 있는 규칙을 우선 매칭.
    description이 주어지면 description_pattern과 비교하여 가장 적합한 규칙 선택.
    """
    if not counterparty:
        return None

    # 1차: description 있으면 description_pattern이 일치하는 규칙 우선
    if description:
        cur.execute(
            """
            SELECT internal_account_id, standard_account_id, confidence
            FROM mapping_rules
            WHERE entity_id = %s AND counterparty_pattern = %s AND confidence >= 0.8
              AND description_pattern IS NOT NULL
              AND %s ILIKE '%%' || description_pattern || '%%'
            ORDER BY confidence DESC, hit_count DESC
            LIMIT 1
            """,
            [entity_id, counterparty, description],
        )
        row = cur.fetchone()
        if row:
            return {
                "internal_account_id": row[0],
                "standard_account_id": row[1],
                "confidence": float(row[2]),
                "match_type": "exact_contextual",
            }

    # 2차: fallback — description_pattern 없는 기본 규칙
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
        "match_type": "exact",
    }


# ── 2. 유사 매칭 (pg_trgm) ───────────────────────────────────


def similar_match(
    cur,
    *,
    entity_id: int,
    counterparty: str | None,
    description: str | None,
) -> dict | None:
    """pg_trgm 유사도 기반 매칭. counterparty + description 결합."""
    if not counterparty and not description:
        return None

    search_text = " ".join(filter(None, [counterparty, description]))

    cur.execute(
        """
        SELECT internal_account_id, standard_account_id,
               GREATEST(
                   similarity(counterparty_pattern, %s),
                   CASE WHEN description_pattern IS NOT NULL
                        THEN similarity(description_pattern, %s) * 0.8
                        ELSE 0 END,
                   CASE WHEN vendor IS NOT NULL
                        THEN similarity(vendor, %s) * 0.9
                        ELSE 0 END
               ) AS sim,
               counterparty_pattern, description_pattern, vendor
        FROM mapping_rules
        WHERE entity_id = %s
          AND (
              similarity(counterparty_pattern, %s) >= %s
              OR (description_pattern IS NOT NULL AND similarity(description_pattern, %s) >= %s)
              OR (vendor IS NOT NULL AND similarity(vendor, %s) >= %s)
          )
          AND confidence >= 0.5
        ORDER BY sim DESC, confidence DESC, hit_count DESC
        LIMIT 1
        """,
        [search_text, search_text, search_text,
         entity_id,
         search_text, SIMILAR_THRESHOLD,
         search_text, SIMILAR_THRESHOLD,
         search_text, SIMILAR_THRESHOLD],
    )
    row = cur.fetchone()
    if not row:
        return None

    return {
        "internal_account_id": row[0],
        "standard_account_id": row[1],
        "confidence": round(float(row[2]), 2),
        "match_type": "similar",
        "matched_pattern": row[3],
    }


# ── 3. 키워드 규칙 ───────────────────────────────────────────


def keyword_match(
    cur,
    *,
    entity_id: int,
    counterparty: str | None,
    description: str | None,
) -> dict | None:
    """keyword_mapping_rules 테이블에서 키워드 패턴 매칭."""
    search_text = " ".join(filter(None, [counterparty, description]))
    if not search_text:
        return None

    cur.execute(
        """
        SELECT k.internal_account_id, k.confidence
        FROM keyword_mapping_rules k
        WHERE k.entity_id = %s
          AND %s ILIKE '%%' || k.keyword || '%%'
        ORDER BY length(k.keyword) DESC, k.confidence DESC
        LIMIT 1
        """,
        [entity_id, search_text],
    )
    row = cur.fetchone()
    if not row:
        return None

    # Fetch standard_account_id from internal_accounts
    cur.execute(
        "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
        [row[0]],
    )
    std_row = cur.fetchone()

    return {
        "internal_account_id": row[0],
        "standard_account_id": std_row[0] if std_row else None,
        "confidence": float(row[1]),
        "match_type": "keyword",
    }


# ── 3b. 글로벌 도메인 키워드 (standard_account_keywords) ─────


def global_keyword_match(
    cur,
    *,
    entity_id: int,
    counterparty: str | None,
    description: str | None,
) -> dict | None:
    """standard_account_keywords (entity 무관 도메인 사전) 매칭.

    keyword_mapping_rules 와 달리 entity 별 학습이 아닌 글로벌 사전.
    standard_account_id 만 결정 가능. internal_account_id 는 entity 의 동일
    standard_account 매핑 internal_accounts 에서 추론.
    """
    search_text = " ".join(filter(None, [counterparty, description]))
    if not search_text:
        return None

    cur.execute(
        """
        SELECT k.standard_account_id, k.confidence, k.keyword
        FROM standard_account_keywords k
        WHERE %s ILIKE '%%' || k.keyword || '%%'
        ORDER BY length(k.keyword) DESC, k.confidence DESC
        LIMIT 1
        """,
        [search_text],
    )
    row = cur.fetchone()
    if not row:
        return None

    std_id, conf, keyword = row

    # entity 의 internal_accounts 중 같은 standard_account 매핑 추론 (있으면)
    cur.execute(
        """
        SELECT id FROM internal_accounts
        WHERE entity_id = %s AND standard_account_id = %s AND is_active = TRUE
        ORDER BY sort_order LIMIT 1
        """,
        [entity_id, std_id],
    )
    int_row = cur.fetchone()

    return {
        "internal_account_id": int_row[0] if int_row else None,
        "standard_account_id": std_id,
        "confidence": float(conf),
        "match_type": "global_keyword",
        "matched_keyword": keyword,
    }


# ── 4. Claude AI fallback ────────────────────────────────────


def ai_match(
    cur,
    *,
    entity_id: int,
    counterparty: str | None,
    description: str | None,
) -> dict | None:
    """Claude AI로 거래→내부계정 매칭 추천. mapping_rules에 학습 저장."""
    if not counterparty and not description:
        return None

    # 내부계정 목록 조회
    cur.execute(
        """
        SELECT id, name, (SELECT name FROM internal_accounts p WHERE p.id = ia.parent_id) AS parent_name
        FROM internal_accounts ia
        WHERE entity_id = %s AND is_active = true
        ORDER BY sort_order
        """,
        [entity_id],
    )
    accounts = cur.fetchall()
    if not accounts:
        return None

    account_list = "\n".join(
        f"- id:{a[0]} {a[2] + ' > ' if a[2] else ''}{a[1]}" for a in accounts
    )

    prompt = f"""거래 정보:
- 거래처: {counterparty or '(없음)'}
- 설명: {description or '(없음)'}

내부계정 목록:
{account_list}

이 거래가 어떤 내부계정에 해당하는지 JSON으로 답하세요.
반드시 위 목록에 있는 id만 사용하세요.
확신이 없으면 {{"internal_account_id": null, "reasoning": "이유"}}를 반환하세요.

응답 형식 (JSON만, 다른 텍스트 없이):
{{"internal_account_id": <id 또는 null>, "reasoning": "<한국어 이유>"}}"""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(l for l in lines if not l.startswith("```"))
        data = json.loads(raw)
    except Exception:
        logger.warning("ai_match failed for counterparty=%s", counterparty, exc_info=True)
        return None

    account_id = data.get("internal_account_id")
    reasoning = data.get("reasoning", "")

    # Validate that returned id exists in our account list
    valid_ids = {a[0] for a in accounts}
    if not account_id or account_id not in valid_ids:
        return None

    # Fetch standard_account_id
    cur.execute(
        "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
        [account_id],
    )
    std_row = cur.fetchone()

    # Learn this mapping for future fast matching
    if counterparty:
        learn_mapping_rule(cur, entity_id=entity_id, counterparty=counterparty, internal_account_id=account_id)
        # Update match_type to 'ai' for the just-learned rule
        cur.execute(
            "UPDATE mapping_rules SET match_type = 'ai' WHERE entity_id = %s AND counterparty_pattern = %s",
            [entity_id, counterparty],
        )

    return {
        "internal_account_id": account_id,
        "standard_account_id": std_row[0] if std_row else None,
        "confidence": 0.6,
        "match_type": "ai",
        "ai_reasoning": reasoning,
    }


# ── 5단계 캐스케이드 ─────────────────────────────────────────


def auto_map_transaction(
    cur,
    *,
    entity_id: int,
    counterparty: str | None,
    description: str | None = None,
    enable_ai: bool = False,
) -> dict | None:
    """6단계 캐스케이드 매칭:
    exact → similar → entity_keyword → global_keyword → AI → None.

    Returns dict with keys: internal_account_id, standard_account_id, confidence, match_type
    or None if all stages fail.
    """
    if not counterparty and not description:
        return None

    # 1. 정확 일치
    result = exact_match(cur, entity_id=entity_id, counterparty=counterparty, description=description)
    if result:
        return result

    # 2. 유사 매칭 (pg_trgm)
    result = similar_match(cur, entity_id=entity_id, counterparty=counterparty, description=description)
    if result:
        return result

    # 3a. entity 별 키워드 규칙 (keyword_mapping_rules)
    result = keyword_match(cur, entity_id=entity_id, counterparty=counterparty, description=description)
    if result:
        return result

    # 3b. 글로벌 도메인 키워드 (standard_account_keywords)
    result = global_keyword_match(cur, entity_id=entity_id, counterparty=counterparty, description=description)
    if result:
        return result

    # 4. Claude AI (선택적, 비용 발생)
    if enable_ai:
        result = ai_match(cur, entity_id=entity_id, counterparty=counterparty, description=description)
        if result:
            return result

    # 5. 미매칭
    return None


# ── 학습 ──────────────────────────────────────────────────────


def learn_mapping_rule(
    cur, *, entity_id: int, counterparty: str | None, internal_account_id: int,
    description_pattern: str | None = None, vendor: str | None = None, category: str | None = None,
) -> None:
    """사용자의 계정 선택을 mapping_rules에 UPSERT.

    Slack 컨텍스트가 있으면 거래처+description_pattern 조합으로 복수 규칙 지원.
    같은 거래처라도 Slack 설명이 다르면 다른 내부계정으로 매핑 가능.
    """
    if not counterparty:
        return

    # Slack 컨텍스트가 있으면 거래처+description 조합으로 검색
    if description_pattern:
        cur.execute(
            """
            SELECT id, internal_account_id, confidence, hit_count
            FROM mapping_rules
            WHERE entity_id = %s AND counterparty_pattern = %s AND description_pattern = %s
            LIMIT 1
            """,
            [entity_id, counterparty, description_pattern],
        )
    else:
        # Slack 없는 경우: 거래처만 + description_pattern IS NULL 매칭
        cur.execute(
            """
            SELECT id, internal_account_id, confidence, hit_count
            FROM mapping_rules
            WHERE entity_id = %s AND counterparty_pattern = %s AND description_pattern IS NULL
            LIMIT 1
            """,
            [entity_id, counterparty],
        )
    existing = cur.fetchone()

    # Slack 컨텍스트 업데이트 SQL 조각
    slack_sets = ""
    slack_params: list = []
    if vendor:
        slack_sets += ", vendor = %s"
        slack_params.append(vendor)
    if category:
        slack_sets += ", category = %s"
        slack_params.append(category)

    if existing:
        rule_id, existing_account_id, confidence, hit_count = existing
        if existing_account_id == internal_account_id:
            new_confidence = min(1.0, float(confidence) + 0.05)
            cur.execute(
                f"UPDATE mapping_rules SET hit_count = %s, confidence = %s{slack_sets}, updated_at = NOW() WHERE id = %s",
                [hit_count + 1, new_confidence] + slack_params + [rule_id],
            )
        else:
            cur.execute(
                "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
                [internal_account_id],
            )
            std_row = cur.fetchone()
            std_id = std_row[0] if std_row else None

            if std_id is not None:
                cur.execute(
                    f"""
                    UPDATE mapping_rules
                    SET internal_account_id = %s, standard_account_id = %s,
                        confidence = 0.8, hit_count = 1{slack_sets}, updated_at = NOW()
                    WHERE id = %s
                    """,
                    [internal_account_id, std_id] + slack_params + [rule_id],
                )
            else:
                cur.execute(
                    f"""
                    UPDATE mapping_rules
                    SET internal_account_id = %s,
                        confidence = 0.8, hit_count = 1{slack_sets}, updated_at = NOW()
                    WHERE id = %s
                    """,
                    [internal_account_id] + slack_params + [rule_id],
                )
    else:
        cur.execute(
            "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
            [internal_account_id],
        )
        std_row = cur.fetchone()
        std_id = std_row[0] if std_row else None

        if std_id is None:
            return  # 표준계정 미연결 → 매핑 규칙 저장 건너뜀

        cur.execute(
            """
            INSERT INTO mapping_rules (entity_id, counterparty_pattern, internal_account_id, standard_account_id,
                                       confidence, hit_count, description_pattern, vendor, category)
            VALUES (%s, %s, %s, %s, 0.8, 1, %s, %s, %s)
            """,
            [entity_id, counterparty, internal_account_id, std_id, description_pattern, vendor, category],
        )

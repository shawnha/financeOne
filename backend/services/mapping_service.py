"""거래 ↔ 내부계정 매핑 서비스 — 5단계 캐스케이드 자동 매핑 + 학습"""

import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

SIMILAR_THRESHOLD = 0.3
AI_MODEL = "claude-haiku-4-5-20251001"


# ── 1. 정확 일치 ──────────────────────────────────────────────


def exact_match(
    cur, *,
    entity_id: int,
    counterparty: str | None,
    description: str | None = None,
    direction: str | None = None,
) -> dict | None:
    """counterparty로 mapping_rules 정확 일치 조회.

    Slack 컨텍스트(description_pattern)가 있는 규칙을 우선 매칭.
    description이 주어지면 description_pattern과 비교하여 가장 적합한 규칙 선택.
    direction 이 주어지면 applicable_directions 에 그 방향이 포함된 룰만 매칭
    (NULL 인 룰은 모든 방향 허용).
    """
    if not counterparty:
        return None

    dir_filter = "AND (applicable_directions IS NULL OR %s = ANY(applicable_directions))"
    dir_params = [direction] if direction else []
    if not direction:
        dir_filter = ""

    # 1차: description 있으면 description_pattern이 일치하는 규칙 우선
    if description:
        cur.execute(
            f"""
            SELECT internal_account_id, standard_account_id, confidence
            FROM mapping_rules
            WHERE entity_id = %s AND counterparty_pattern = %s AND confidence >= 0.8
              AND description_pattern IS NOT NULL
              AND %s ILIKE '%%' || description_pattern || '%%'
              {dir_filter}
            ORDER BY confidence DESC, hit_count DESC
            LIMIT 1
            """,
            [entity_id, counterparty, description, *dir_params],
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
        f"""
        SELECT internal_account_id, standard_account_id, confidence
        FROM mapping_rules
        WHERE entity_id = %s AND counterparty_pattern = %s AND confidence >= 0.8
          {dir_filter}
        ORDER BY confidence DESC, hit_count DESC
        LIMIT 1
        """,
        [entity_id, counterparty, *dir_params],
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
    direction: str | None = None,
) -> dict | None:
    """pg_trgm 유사도 기반 매칭. counterparty + description 결합."""
    if not counterparty and not description:
        return None

    search_text = " ".join(filter(None, [counterparty, description]))

    dir_filter = ""
    dir_params: list = []
    if direction:
        dir_filter = "AND (applicable_directions IS NULL OR %s = ANY(applicable_directions))"
        dir_params = [direction]

    cur.execute(
        f"""
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
          {dir_filter}
        ORDER BY sim DESC, confidence DESC, hit_count DESC
        LIMIT 1
        """,
        [search_text, search_text, search_text,
         entity_id,
         search_text, SIMILAR_THRESHOLD,
         search_text, SIMILAR_THRESHOLD,
         search_text, SIMILAR_THRESHOLD,
         *dir_params],
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


# ── 3. 키워드 규칙 (entity ∪ global 통합 cascade) ────────────
#
# Stage 3 Eng Review 결정:
#   D1: 통합 SQL — keyword_mapping_rules (entity-level) UNION
#       standard_account_keywords (global). length × confidence 정렬.
#   D2: global 매칭 시 entity 의 standard_account 매핑된 internal_account
#       자동 추론. 없으면 internal_account_id=NULL 반환.
#
# 매칭 우선순위:
#   1. 더 긴 keyword (구체적인 매칭)
#   2. 더 높은 confidence
#   3. entity-level 우선 (source priority: entity=0 < global=1)


def keyword_match(
    cur,
    *,
    entity_id: int,
    counterparty: str | None,
    description: str | None,
) -> dict | None:
    """entity_keyword (keyword_mapping_rules) ∪ global_keyword (standard_account_keywords).

    통합 SQL 한 번으로 두 테이블 모두 검색, length × confidence 정렬, 1건 반환.

    return dict 의 match_type:
      - 'keyword' (기존, entity-level)
      - 'global_keyword' (P4-B 신규, 전역)
    """
    search_text = " ".join(filter(None, [counterparty, description]))
    if not search_text:
        return None

    # 통합 SQL: entity-level + global 양쪽 검색
    # source_priority: entity=0 (우선), global=1 (fallback)
    #
    # 안전성 보장 (Code Reviewer P0/P1 반영):
    #   - entity-level: ia.entity_id = k.entity_id 검증 (cross-entity leak 차단)
    #   - is_active 필터 (entity 와 global 양쪽)
    #   - standard_accounts.is_active 검증
    #   - ILIKE ESCAPE '\' 로 메타문자 false-match 차단
    cur.execute(
        r"""
        SELECT internal_account_id,
               standard_account_id,
               confidence,
               match_type,
               keyword
        FROM (
            -- entity-level: keyword_mapping_rules
            SELECT k.internal_account_id,
                   ia.standard_account_id,
                   k.confidence,
                   length(k.keyword) AS w,
                   0 AS source_priority,
                   'keyword' AS match_type,
                   k.keyword
            FROM keyword_mapping_rules k
            JOIN internal_accounts ia
              ON k.internal_account_id = ia.id
             AND ia.entity_id = k.entity_id
             AND ia.is_active = TRUE
            WHERE k.entity_id = %s
              AND %s ILIKE '%%' || k.keyword || '%%' ESCAPE '\'

            UNION ALL

            -- global: standard_account_keywords (P4-B)
            -- D2: entity 의 internal_account 자동 추론 (있으면)
            SELECT (
                       SELECT id FROM internal_accounts ia2
                       WHERE ia2.entity_id = %s
                         AND ia2.standard_account_id = sak.standard_account_id
                         AND ia2.is_active = TRUE
                       ORDER BY ia2.sort_order
                       LIMIT 1
                   ) AS internal_account_id,
                   sak.standard_account_id,
                   sak.confidence,
                   length(sak.keyword) AS w,
                   1 AS source_priority,
                   'global_keyword' AS match_type,
                   sak.keyword
            FROM standard_account_keywords sak
            JOIN standard_accounts sa
              ON sak.standard_account_id = sa.id
             AND sa.is_active = TRUE
            WHERE %s ILIKE '%%' || sak.keyword || '%%' ESCAPE '\'
        ) merged
        -- entity 가 항상 global 보다 우선 (P2-6: docstring 일치)
        -- 그 다음 length 우선 (구체적 매칭), confidence 우선
        ORDER BY source_priority ASC, w DESC, confidence DESC
        LIMIT 1
        """,
        [entity_id, search_text, entity_id, search_text],
    )
    row = cur.fetchone()
    if not row:
        return None

    internal_id, standard_id, confidence, match_type, matched_kw = row

    return {
        "internal_account_id": internal_id,
        "standard_account_id": standard_id,
        "confidence": float(confidence),
        "match_type": match_type,
        "matched_keyword": matched_kw,
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
    direction: str | None = None,
) -> dict | None:
    """5단계 캐스케이드 매칭: exact → similar → keyword → AI → None.

    Returns dict with keys: internal_account_id, standard_account_id, confidence, match_type
    or None if all stages fail.

    direction: 'sales' | 'purchase' | None. mapping_rules.applicable_directions
    가 NULL 이면 모든 방향 허용. 명시된 경우 direction 이 그 array 에 포함되어야.
    transactions 의 type='in' → direction='sales', type='out' → direction='purchase'.
    invoices 는 direction 컬럼 그대로 사용.
    """
    if not counterparty and not description:
        return None

    # 1. 정확 일치
    result = exact_match(cur, entity_id=entity_id, counterparty=counterparty, description=description, direction=direction)
    if result:
        return result

    # 2. 유사 매칭 (pg_trgm)
    result = similar_match(cur, entity_id=entity_id, counterparty=counterparty, description=description, direction=direction)
    if result:
        return result

    # 3. 키워드 규칙
    result = keyword_match(cur, entity_id=entity_id, counterparty=counterparty, description=description)
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

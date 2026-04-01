# 내부계정 자동 매칭 고도화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade transaction→internal account auto-mapping from exact-match-only to a 5-stage hybrid pipeline: exact → similar (pg_trgm) → keyword → Claude AI → manual, with source badges and bulk confirm UI.

**Architecture:** Extend `mapping_service.py` with a cascade of matchers. Each stage returns `{internal_account_id, standard_account_id, confidence, match_type}` or `None` to fall through. New `keyword_mapping_rules` table for keyword-based matching. Claude AI fallback uses existing `anthropic` SDK pattern from `structured_parser.py`. Frontend shows match source badges on transactions.

**Tech Stack:** PostgreSQL pg_trgm extension, Anthropic Claude API (haiku), FastAPI, Next.js/React, psycopg2

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/database/migrations/add_matching_v2.sql` | Create | DDL: match_type column, pg_trgm, keyword tables, indexes |
| `backend/services/mapping_service.py` | Modify | Add `similar_match()`, `keyword_match()`, `ai_match()`, update `auto_map_transaction()` cascade |
| `backend/services/standard_account_recommender.py` | Create | Standard account recommendation for new internal accounts |
| `backend/routers/accounts.py` | Modify | Add standard account recommendation to create endpoint |
| `backend/routers/transactions.py` | Modify | Update auto-map endpoint to use new cascade, add bulk-confirm |
| `backend/routers/upload.py` | Modify | Use updated `auto_map_transaction()` (cascade) |
| `backend/tests/test_mapping_service.py` | Modify | Tests for similar, keyword, AI matchers |
| `backend/tests/test_standard_recommender.py` | Create | Tests for standard account recommendation |
| `frontend/src/app/transactions/page.tsx` | Modify | Source badges, bulk confirm button |

---

### Task 1: DB Migration — pg_trgm, match_type, keyword tables

**Files:**
- Create: `backend/database/migrations/add_matching_v2.sql`
- Modify: `backend/database/schema.sql` (add comments for new columns/tables)

- [ ] **Step 1: Write migration SQL**

Create `backend/database/migrations/add_matching_v2.sql`:

```sql
-- 1. pg_trgm 확장 활성화
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. mapping_rules에 match_type 컬럼 추가
ALTER TABLE mapping_rules ADD COLUMN IF NOT EXISTS match_type varchar(20) DEFAULT 'exact';
-- values: 'exact' | 'similar' | 'keyword' | 'ai'

-- 3. counterparty_pattern 유사도 인덱스 (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_mapping_rules_trgm
  ON mapping_rules USING gin (counterparty_pattern gin_trgm_ops);

-- 4. entity_id + counterparty_pattern 복합 인덱스 (기존 쿼리 최적화)
CREATE INDEX IF NOT EXISTS idx_mapping_rules_entity_pattern
  ON mapping_rules(entity_id, counterparty_pattern);

-- 5. 키워드 매핑 규칙 테이블
CREATE TABLE IF NOT EXISTS keyword_mapping_rules (
  id                  SERIAL PRIMARY KEY,
  entity_id           INTEGER NOT NULL REFERENCES entities(id),
  keyword             VARCHAR(100) NOT NULL,
  match_field         VARCHAR(20) NOT NULL DEFAULT 'description',
  internal_account_id INTEGER NOT NULL REFERENCES internal_accounts(id),
  confidence          NUMERIC(3,2) NOT NULL DEFAULT 0.75,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, keyword, match_field)
);

-- 6. 일상어 → 표준계정 매핑 사전
CREATE TABLE IF NOT EXISTS standard_account_keywords (
  id                  SERIAL PRIMARY KEY,
  keyword             VARCHAR(100) NOT NULL UNIQUE,
  standard_account_id INTEGER NOT NULL REFERENCES standard_accounts(id),
  confidence          NUMERIC(3,2) NOT NULL DEFAULT 0.80
);

-- 7. 일상어 사전 시드 데이터
INSERT INTO standard_account_keywords (keyword, standard_account_id, confidence)
SELECT v.keyword, sa.id, 0.85
FROM (VALUES
  ('회식', '8220'),       -- 복리후생비
  ('택시', '8230'),       -- 여비교통비
  ('식대', '8220'),       -- 복리후생비
  ('커피', '8250'),       -- 접대비
  ('사무용품', '8290'),   -- 소모품비
  ('택배', '8270'),       -- 운반비
  ('인터넷', '8260'),     -- 통신비
  ('전화', '8260'),       -- 통신비
  ('임대', '8100'),       -- 임차료
  ('월세', '8100'),       -- 임차료
  ('급여', '8010'),       -- 급여
  ('보험', '8110'),       -- 보험료
  ('광고', '8310'),       -- 광고선전비
  ('수수료', '8340'),     -- 지급수수료
  ('이자', '9100')        -- 이자비용
) AS v(keyword, std_code)
JOIN standard_accounts sa ON sa.code = v.std_code
ON CONFLICT (keyword) DO NOTHING;
```

- [ ] **Step 2: Run migration on Supabase**

```bash
# 로컬에서 Supabase에 직접 실행
source .venv/bin/activate
python -c "
from backend.database.connection import init_pool, get_db
init_pool()
conn = next(get_db())
cur = conn.cursor()
with open('backend/database/migrations/add_matching_v2.sql') as f:
    cur.execute(f.read())
conn.commit()
cur.close()
print('Migration complete')
"
```

Expected: "Migration complete" (no errors)

- [ ] **Step 3: Verify migration**

```bash
source .venv/bin/activate
python -c "
from backend.database.connection import init_pool, get_db
init_pool()
conn = next(get_db())
cur = conn.cursor()
# Check pg_trgm works
cur.execute(\"SELECT similarity('택시비', '택시')\")
print('pg_trgm similarity:', cur.fetchone()[0])
# Check match_type column
cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_schema='financeone' AND table_name='mapping_rules' AND column_name='match_type'\")
print('match_type column:', cur.fetchone())
# Check keyword table
cur.execute('SELECT COUNT(*) FROM keyword_mapping_rules')
print('keyword_mapping_rules:', cur.fetchone()[0])
# Check standard_account_keywords
cur.execute('SELECT COUNT(*) FROM standard_account_keywords')
print('standard_account_keywords:', cur.fetchone()[0])
cur.close()
"
```

Expected: pg_trgm returns float > 0, match_type column exists, keyword counts ≥ 0

- [ ] **Step 4: Update schema.sql with new table definitions (documentation)**

Add after existing `mapping_rules` table definition in `backend/database/schema.sql`:

```sql
-- match_type on mapping_rules: 'exact' | 'similar' | 'keyword' | 'ai'

CREATE TABLE IF NOT EXISTS keyword_mapping_rules (
  id                  SERIAL PRIMARY KEY,
  entity_id           INTEGER NOT NULL REFERENCES entities(id),
  keyword             VARCHAR(100) NOT NULL,
  match_field         VARCHAR(20) NOT NULL DEFAULT 'description',
  internal_account_id INTEGER NOT NULL REFERENCES internal_accounts(id),
  confidence          NUMERIC(3,2) NOT NULL DEFAULT 0.75,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, keyword, match_field)
);

CREATE TABLE IF NOT EXISTS standard_account_keywords (
  id                  SERIAL PRIMARY KEY,
  keyword             VARCHAR(100) NOT NULL UNIQUE,
  standard_account_id INTEGER NOT NULL REFERENCES standard_accounts(id),
  confidence          NUMERIC(3,2) NOT NULL DEFAULT 0.80
);
```

- [ ] **Step 5: Commit**

```bash
git add backend/database/migrations/add_matching_v2.sql backend/database/schema.sql
git commit -m "feat: DB migration for auto-matching v2 (pg_trgm, keyword tables, match_type)"
```

---

### Task 2: Similar Match — pg_trgm fuzzy matching

**Files:**
- Modify: `backend/services/mapping_service.py` (add `similar_match()`)
- Modify: `backend/tests/test_mapping_service.py` (add tests)

- [ ] **Step 1: Write failing tests for similar_match**

Add to `backend/tests/test_mapping_service.py`:

```python
class TestSimilarMatch:
    def test_returns_match_above_threshold(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        cur.fetchone.return_value = (10, 20, 0.85, "OPENAI *CHATGPT SUB")
        result = similar_match(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", description=None)
        assert result is not None
        assert result["internal_account_id"] == 10
        assert result["match_type"] == "similar"

    def test_returns_none_below_threshold(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = similar_match(cur, entity_id=2, counterparty="완전다른거래처", description=None)
        assert result is None

    def test_returns_none_when_counterparty_empty(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        result = similar_match(cur, entity_id=2, counterparty=None, description=None)
        assert result is None
        cur.execute.assert_not_called()

    def test_combines_counterparty_and_description(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        cur.fetchone.return_value = (10, 20, 0.72, "배달의민족")
        result = similar_match(cur, entity_id=2, counterparty="배민", description="배달의민족 결제")
        assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestSimilarMatch -v
```

Expected: FAIL — `ImportError: cannot import name 'similar_match'`

- [ ] **Step 3: Implement similar_match**

Add to `backend/services/mapping_service.py` after `auto_map_transaction()`:

```python
SIMILAR_THRESHOLD = 0.3


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
               similarity(counterparty_pattern, %s) AS sim,
               counterparty_pattern
        FROM mapping_rules
        WHERE entity_id = %s
          AND similarity(counterparty_pattern, %s) >= %s
          AND confidence >= 0.5
        ORDER BY sim DESC, confidence DESC, hit_count DESC
        LIMIT 1
        """,
        [search_text, entity_id, search_text, SIMILAR_THRESHOLD],
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestSimilarMatch -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/mapping_service.py backend/tests/test_mapping_service.py
git commit -m "feat: add pg_trgm similar matching for auto-mapping v2"
```

---

### Task 3: Keyword Match — description keyword rules

**Files:**
- Modify: `backend/services/mapping_service.py` (add `keyword_match()`)
- Modify: `backend/tests/test_mapping_service.py` (add tests)

- [ ] **Step 1: Write failing tests for keyword_match**

Add to `backend/tests/test_mapping_service.py`:

```python
class TestKeywordMatch:
    def test_returns_match_when_keyword_found_in_description(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        cur.fetchone.return_value = (10, 0.75)
        result = keyword_match(cur, entity_id=2, counterparty=None, description="회식비 결제")
        assert result is not None
        assert result["internal_account_id"] == 10
        assert result["match_type"] == "keyword"

    def test_returns_none_when_no_keyword_matches(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = keyword_match(cur, entity_id=2, counterparty=None, description="특이한 거래")
        assert result is None

    def test_returns_none_when_no_description(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        result = keyword_match(cur, entity_id=2, counterparty=None, description=None)
        assert result is None
        cur.execute.assert_not_called()

    def test_searches_counterparty_too(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        cur.fetchone.return_value = (10, 0.75)
        result = keyword_match(cur, entity_id=2, counterparty="택시비", description=None)
        assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestKeywordMatch -v
```

Expected: FAIL — `ImportError: cannot import name 'keyword_match'`

- [ ] **Step 3: Implement keyword_match**

Add to `backend/services/mapping_service.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestKeywordMatch -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/mapping_service.py backend/tests/test_mapping_service.py
git commit -m "feat: add keyword-based matching for auto-mapping v2"
```

---

### Task 4: Claude AI Match — fallback with learning

**Files:**
- Modify: `backend/services/mapping_service.py` (add `ai_match()`)
- Modify: `backend/tests/test_mapping_service.py` (add tests)

- [ ] **Step 1: Write failing tests for ai_match**

Add to `backend/tests/test_mapping_service.py`:

```python
from unittest.mock import patch


class TestAIMatch:
    def test_returns_match_from_ai(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        # fetchall for internal_accounts list
        cur.fetchall.return_value = [
            (10, "급여", "인건비"),
            (11, "임차료", "고정비"),
            (12, "복리후생비", "인건비"),
        ]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"internal_account_id": 12, "reasoning": "회식은 복리후생비"}')]
        with patch("backend.services.mapping_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response
            result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is not None
        assert result["internal_account_id"] == 12
        assert result["match_type"] == "ai"

    def test_returns_none_on_api_error(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        cur.fetchall.return_value = [(10, "급여", "인건비")]
        with patch("backend.services.mapping_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = Exception("API error")
            result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is None

    def test_returns_none_when_no_accounts(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        cur.fetchall.return_value = []
        result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is None

    def test_returns_none_when_ai_returns_invalid_account(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        cur.fetchall.return_value = [(10, "급여", "인건비")]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"internal_account_id": 999, "reasoning": "추측"}')]
        with patch("backend.services.mapping_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response
            result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestAIMatch -v
```

Expected: FAIL — `ImportError: cannot import name 'ai_match'`

- [ ] **Step 3: Implement ai_match**

Add to top of `backend/services/mapping_service.py`:

```python
import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

AI_MODEL = "claude-haiku-4-5-20251001"
```

Add the function after `keyword_match()`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestAIMatch -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/mapping_service.py backend/tests/test_mapping_service.py
git commit -m "feat: add Claude AI fallback matching with learning for auto-mapping v2"
```

---

### Task 5: Cascade — wire all matchers into auto_map_transaction

**Files:**
- Modify: `backend/services/mapping_service.py` (update `auto_map_transaction()`)
- Modify: `backend/tests/test_mapping_service.py` (update cascade tests)

- [ ] **Step 1: Write failing tests for cascade behavior**

Add to `backend/tests/test_mapping_service.py`:

```python
class TestCascade:
    def test_exact_match_takes_priority(self):
        """exact match가 있으면 similar/keyword/ai는 호출되지 않음"""
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        cur.fetchone.return_value = (10, 20, 0.9)  # exact match found
        result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI", description="구독")
        assert result is not None
        assert result["match_type"] == "exact"
        # Only 1 execute call (exact match query)
        assert cur.execute.call_count == 1

    def test_falls_through_to_similar(self):
        """exact miss → similar hit"""
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,                              # exact match miss
            (10, 20, 0.75, "OPENAI CHATGPT"),  # similar match hit
        ]
        result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI CHAT", description=None)
        assert result is not None
        assert result["match_type"] == "similar"

    def test_falls_through_to_keyword(self):
        """exact miss → similar miss → keyword hit"""
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,         # exact miss
            None,         # similar miss
            (10, 0.75),   # keyword hit
            (20,),        # standard_account_id lookup
        ]
        result = auto_map_transaction(cur, entity_id=2, counterparty=None, description="회식비 결제")
        assert result is not None
        assert result["match_type"] == "keyword"

    def test_returns_none_when_all_miss(self):
        """모든 단계 miss → None (AI는 기본적으로 skip, enable_ai=True일 때만)"""
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        result = auto_map_transaction(cur, entity_id=2, counterparty="???", description="???")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestCascade -v
```

Expected: FAIL — `auto_map_transaction()` doesn't accept `description` parameter yet

- [ ] **Step 3: Update auto_map_transaction to cascade**

Replace the existing `auto_map_transaction` function in `backend/services/mapping_service.py`:

```python
def auto_map_transaction(
    cur,
    *,
    entity_id: int,
    counterparty: str | None,
    description: str | None = None,
    enable_ai: bool = False,
) -> dict | None:
    """5단계 캐스케이드 매칭: exact → similar → keyword → AI → None.
    
    Returns dict with keys: internal_account_id, standard_account_id, confidence, match_type
    or None if all stages fail.
    """
    if not counterparty and not description:
        return None

    # 1. 정확 일치
    if counterparty:
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
        if row:
            return {
                "internal_account_id": row[0],
                "standard_account_id": row[1],
                "confidence": float(row[2]),
                "match_type": "exact",
            }

    # 2. 유사 매칭 (pg_trgm)
    result = similar_match(cur, entity_id=entity_id, counterparty=counterparty, description=description)
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
```

- [ ] **Step 4: Run all mapping tests**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py -v
```

Expected: All tests PASS (existing TestAutoMap tests may need `description` kwarg added — update those too if they break)

- [ ] **Step 5: Update existing TestAutoMap tests for new signature**

If tests fail because `auto_map_transaction` signature changed, update the existing tests to include `description=None`:

```python
# In TestAutoMap, update call signatures:
result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", description=None)
```

- [ ] **Step 6: Run all tests again**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py -v
```

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/services/mapping_service.py backend/tests/test_mapping_service.py
git commit -m "feat: wire 5-stage cascade into auto_map_transaction"
```

---

### Task 6: Update callers — upload, auto-map endpoint, remap

**Files:**
- Modify: `backend/routers/upload.py` (pass description to auto_map)
- Modify: `backend/routers/transactions.py` (pass description, add enable_ai option, add mapping_source tracking)
- Modify: `backend/services/remapping_service.py` (use cascade)

- [ ] **Step 1: Update upload.py auto-mapping call**

In `backend/routers/upload.py`, find the `auto_map_transaction` call (around line 151) and add description:

```python
# Before:
mapping = auto_map_transaction(cur, entity_id=entity_id, counterparty=tx.counterparty)

# After:
mapping = auto_map_transaction(
    cur, entity_id=entity_id,
    counterparty=tx.counterparty,
    description=tx.description,
)
```

Also update the transaction UPDATE to save `match_type`:

```python
# Before:
mapping_source = 'rule'

# After — use match_type from result:
mapping_source = mapping.get("match_type", "rule")
```

- [ ] **Step 2: Update transactions.py auto-map endpoint**

In `backend/routers/transactions.py`, update the `auto_map_unmapped` endpoint (around line 211):

Add `enable_ai` query parameter:

```python
@router.post("/auto-map")
async def auto_map_unmapped(
    entity_id: int,
    enable_ai: bool = False,
    conn: PgConnection = Depends(get_db),
):
```

Update the unmapped query to also fetch `description`:

```sql
SELECT id, counterparty, description
FROM transactions
WHERE entity_id = %s
  AND internal_account_id IS NULL
  AND (counterparty IS NOT NULL OR description IS NOT NULL)
```

Update the mapping call:

```python
mapping = auto_map_transaction(
    cur, entity_id=entity_id,
    counterparty=row[1],
    description=row[2],
    enable_ai=enable_ai,
)
```

Update the UPDATE query to save match_type as mapping_source:

```python
mapping_source = mapping.get("match_type", "rule")
```

- [ ] **Step 3: Update remapping_service.py**

In `backend/services/remapping_service.py`, update `remap_transactions()` to use the new cascade.

Update `query_remap_candidates()` to also select `description`:

```sql
SELECT id, counterparty, internal_account_id, mapping_source, description
FROM transactions
...
```

Update the mapping call in `remap_transactions()`:

```python
# In-memory exact match first (existing fast path)
key = tx["counterparty"].lower() if tx.get("counterparty") else None
if key and key in rules:
    ...
else:
    # Fall through to cascade (similar + keyword, no AI for batch remap)
    from backend.services.mapping_service import auto_map_transaction
    mapping = auto_map_transaction(
        cur, entity_id=entity_id,
        counterparty=tx.get("counterparty"),
        description=tx.get("description"),
        enable_ai=False,
    )
```

- [ ] **Step 4: Test server starts without errors**

```bash
source .venv/bin/activate && uvicorn backend.main:app --reload --port 8001 &
sleep 3
curl -s http://localhost:8001/docs | head -5
kill %1
```

Expected: Server starts, API docs accessible

- [ ] **Step 5: Commit**

```bash
git add backend/routers/upload.py backend/routers/transactions.py backend/services/remapping_service.py
git commit -m "feat: update upload/auto-map/remap to use cascade matching"
```

---

### Task 7: Bulk Confirm endpoint

**Files:**
- Modify: `backend/routers/transactions.py` (add bulk-confirm endpoint)

- [ ] **Step 1: Add bulk-confirm endpoint**

Add to `backend/routers/transactions.py`:

```python
class BulkConfirm(BaseModel):
    ids: list[int]


@router.post("/bulk-confirm")
async def bulk_confirm(body: BulkConfirm, conn: PgConnection = Depends(get_db)):
    """AI/유사 매칭된 거래를 일괄 확정."""
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE transactions
        SET is_confirmed = true, mapping_source = 'confirmed', updated_at = NOW()
        WHERE id = ANY(%s) AND internal_account_id IS NOT NULL
        RETURNING id
        """,
        [body.ids],
    )
    confirmed = [r[0] for r in cur.fetchall()]

    # 확정된 거래의 mapping_rules 신뢰도 +0.05
    for tx_id in confirmed:
        cur.execute(
            "SELECT entity_id, counterparty, internal_account_id FROM transactions WHERE id = %s",
            [tx_id],
        )
        tx = cur.fetchone()
        if tx and tx[1]:
            learn_mapping_rule(cur, entity_id=tx[0], counterparty=tx[1], internal_account_id=tx[2])

    conn.commit()
    cur.close()
    return {"confirmed": len(confirmed), "ids": confirmed}
```

- [ ] **Step 2: Test the endpoint**

```bash
curl -s -X POST "http://localhost:8000/api/transactions/bulk-confirm" \
  -H "Content-Type: application/json" \
  -d '{"ids": []}' | python3 -m json.tool
```

Expected: `{"confirmed": 0, "ids": []}`

- [ ] **Step 3: Commit**

```bash
git add backend/routers/transactions.py
git commit -m "feat: add bulk-confirm endpoint for auto-matched transactions"
```

---

### Task 8: Standard Account Recommender

**Files:**
- Create: `backend/services/standard_account_recommender.py`
- Create: `backend/tests/test_standard_recommender.py`
- Modify: `backend/routers/accounts.py` (add recommendation to create flow)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_standard_recommender.py`:

```python
"""표준계정 추천 서비스 테스트"""

import pytest
from unittest.mock import MagicMock


class TestRecommendStandardAccount:
    def test_inherits_from_parent(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        # parent has standard_account_id = 100
        cur.fetchone.return_value = (100,)
        result = recommend_standard_account(cur, entity_id=2, name="식대", parent_id=5)
        assert result is not None
        assert result["standard_account_id"] == 100
        assert result["source"] == "parent"

    def test_similar_account_in_same_entity(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,       # no parent
            (200, 0.6), # similar account found
        ]
        result = recommend_standard_account(cur, entity_id=2, name="택시비", parent_id=None)
        assert result is not None
        assert result["standard_account_id"] == 200
        assert result["source"] == "similar"

    def test_keyword_dictionary(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,        # no parent
            None,        # no similar account
            (300, 0.85), # keyword match
        ]
        result = recommend_standard_account(cur, entity_id=2, name="회식", parent_id=None)
        assert result is not None
        assert result["standard_account_id"] == 300
        assert result["source"] == "keyword"

    def test_returns_none_when_no_match(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        result = recommend_standard_account(cur, entity_id=2, name="특이한항목", parent_id=None)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_standard_recommender.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement standard_account_recommender.py**

Create `backend/services/standard_account_recommender.py`:

```python
"""내부계정 → 표준계정 자동 추천 서비스.

추천 순서: 1) 상위계정 상속 → 2) 동일 법인 유사계정 → 3) 일상어 사전
"""

import logging

logger = logging.getLogger(__name__)


def recommend_standard_account(
    cur,
    *,
    entity_id: int,
    name: str,
    parent_id: int | None,
) -> dict | None:
    """내부계정 이름으로 표준계정 추천.

    Returns: {"standard_account_id": int, "confidence": float, "source": str} or None
    """
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
                "confidence": 0.90,
                "source": "parent",
            }

    # 2. 동일 법인 유사계정 (pg_trgm)
    cur.execute(
        """
        SELECT standard_account_id, similarity(name, %s) AS sim
        FROM internal_accounts
        WHERE entity_id = %s
          AND standard_account_id IS NOT NULL
          AND is_active = true
          AND similarity(name, %s) >= 0.3
        ORDER BY sim DESC
        LIMIT 1
        """,
        [name, entity_id, name],
    )
    row = cur.fetchone()
    if row:
        return {
            "standard_account_id": row[0],
            "confidence": round(float(row[1]), 2),
            "source": "similar",
        }

    # 3. 일상어 사전
    cur.execute(
        """
        SELECT standard_account_id, confidence
        FROM standard_account_keywords
        WHERE %s ILIKE '%%' || keyword || '%%'
        ORDER BY length(keyword) DESC, confidence DESC
        LIMIT 1
        """,
        [name],
    )
    row = cur.fetchone()
    if row:
        return {
            "standard_account_id": row[0],
            "confidence": float(row[1]),
            "source": "keyword",
        }

    return None
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_standard_recommender.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Add recommendation to accounts create endpoint**

In `backend/routers/accounts.py`, after inserting the new internal account (around line 170), add standard account recommendation if `standard_account_id` was not provided:

```python
from backend.services.standard_account_recommender import recommend_standard_account

# After INSERT ... RETURNING, if standard_account_id is None:
if body.standard_account_id is None:
    recommendation = recommend_standard_account(
        cur, entity_id=body.entity_id, name=body.name, parent_id=body.parent_id,
    )
    if recommendation:
        cur.execute(
            "UPDATE internal_accounts SET standard_account_id = %s WHERE id = %s",
            [recommendation["standard_account_id"], new_id],
        )
        # Include recommendation info in response
```

- [ ] **Step 6: Commit**

```bash
git add backend/services/standard_account_recommender.py backend/tests/test_standard_recommender.py backend/routers/accounts.py
git commit -m "feat: add standard account recommender for new internal accounts"
```

---

### Task 9: Frontend — source badges on transactions

**Files:**
- Modify: `frontend/src/app/transactions/page.tsx` (add match source badges + bulk confirm)

- [ ] **Step 1: Find the transactions table rendering**

Read `frontend/src/app/transactions/page.tsx` and locate where `mapping_source` is available in the transaction data and where table rows are rendered.

- [ ] **Step 2: Add source badge component**

Add inline in the transactions page (before the table JSX):

```tsx
function MatchBadge({ source, confidence }: { source: string | null; confidence: number | null }) {
  if (!source) return null
  const config: Record<string, { label: string; className: string }> = {
    exact:     { label: "규칙",  className: "bg-emerald-500/15 text-emerald-400" },
    similar:   { label: "유사",  className: "bg-blue-500/15 text-blue-400" },
    keyword:   { label: "키워드", className: "bg-cyan-500/15 text-cyan-400" },
    ai:        { label: "AI",    className: "bg-purple-500/15 text-purple-400" },
    rule:      { label: "규칙",  className: "bg-emerald-500/15 text-emerald-400" },
    manual:    { label: "수동",  className: "bg-gray-500/15 text-gray-400" },
    confirmed: { label: "확정",  className: "bg-amber-500/15 text-amber-400" },
  }
  const c = config[source] ?? { label: source, className: "bg-gray-500/15 text-gray-400" }
  return (
    <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0 font-medium", c.className)}>
      {c.label}{confidence != null ? ` ${Math.round(confidence * 100)}%` : ""}
    </Badge>
  )
}
```

- [ ] **Step 3: Render badge in transaction rows**

In the table row where internal account is shown, add:

```tsx
<MatchBadge source={tx.mapping_source} confidence={tx.mapping_confidence} />
```

- [ ] **Step 4: Add bulk confirm button**

After the table filter controls, add a "일괄 확정" button:

```tsx
{selectedIds.length > 0 && (
  <Button
    size="sm"
    variant="outline"
    onClick={async () => {
      const res = await fetchAPI<{ confirmed: number }>("/transactions/bulk-confirm", {
        method: "POST",
        body: JSON.stringify({ ids: selectedIds }),
      })
      toast.success(`${res.confirmed}건 확정 완료`)
      setSelectedIds([])
      fetchTransactions()
    }}
  >
    AI 매칭 {selectedIds.length}건 일괄 확정
  </Button>
)}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/transactions/page.tsx
git commit -m "feat: add match source badges and bulk confirm to transactions page"
```

---

### Task 10: Integration test & backfill

**Files:**
- No new files — manual verification steps

- [ ] **Step 1: Run full test suite**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/ -v
```

Expected: All tests PASS

- [ ] **Step 2: Test auto-map endpoint with cascade**

```bash
curl -s -X POST "http://localhost:8000/api/transactions/auto-map?entity_id=2" | python3 -m json.tool
```

Expected: Returns mapped count (may be 0 if no unmapped transactions)

- [ ] **Step 3: Test with AI enabled**

```bash
curl -s -X POST "http://localhost:8000/api/transactions/auto-map?entity_id=2&enable_ai=true" | python3 -m json.tool
```

Expected: Returns mapped count (AI matches if any unmapped)

- [ ] **Step 4: Final commit with all changes**

```bash
git add -A
git commit -m "feat: auto-matching v2 — 5-stage cascade (exact/similar/keyword/AI/manual)"
```

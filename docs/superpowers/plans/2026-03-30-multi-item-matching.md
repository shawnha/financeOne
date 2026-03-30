# 다중 항목 개별 매칭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slack 메시지의 다중 비용 항목(items)을 각각 별도 거래에 개별 매칭하는 워크플로우를 추가한다.

**Architecture:** 기존 `transaction_slack_match` 테이블에 `item_index`/`item_description` 컬럼을 추가하여 1:N 매칭을 지원한다. 후보 검색 API에 `item_index` 파라미터를 추가하고, 프론트엔드에 shadcn Tabs로 전체/개별 매칭 모드를 분리한다.

**Tech Stack:** FastAPI, PostgreSQL (Supabase), Next.js 14, shadcn/ui Tabs, sonner toast

**Design Spec:** `docs/superpowers/specs/2026-03-30-multi-item-matching-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/database/schema.sql` | item_index, item_description 컬럼 추가 |
| Modify | `backend/routers/slack.py` | candidates, confirm, undo, list_messages API 변경 |
| Create | `backend/tests/test_slack_item_match.py` | 개별 매칭 API 테스트 |
| Modify | `frontend/src/app/slack-match/page.tsx` | 탭 UI, 항목 테이블, 진행률 표시 |

---

### Task 1: DB 스키마 변경 — item_index, item_description 컬럼 추가

**Files:**
- Modify: `backend/database/schema.sql:296-312`

- [ ] **Step 1: schema.sql에 컬럼 추가**

`backend/database/schema.sql`의 `transaction_slack_match` 테이블 정의를 수정:

```sql
CREATE TABLE IF NOT EXISTS transaction_slack_match (
  id                   SERIAL PRIMARY KEY,
  transaction_id       INTEGER NOT NULL REFERENCES transactions(id),
  slack_message_id     INTEGER NOT NULL REFERENCES slack_messages(id),
  match_confidence     NUMERIC(3,2),
  is_manual            BOOLEAN NOT NULL DEFAULT FALSE,
  is_confirmed         BOOLEAN NOT NULL DEFAULT FALSE,
  ai_reasoning         TEXT,
  note                 TEXT,
  amount_override      NUMERIC(18,2),
  text_override        TEXT,
  project_tag_override TEXT,
  item_index           INTEGER DEFAULT NULL,
  item_description     TEXT DEFAULT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 2: Supabase에 ALTER TABLE 실행**

```bash
source .venv/bin/activate && python3 -c "
from backend.database.connection import get_db_direct
conn = get_db_direct()
cur = conn.cursor()
cur.execute('''
  ALTER TABLE financeone.transaction_slack_match
    ADD COLUMN IF NOT EXISTS item_index INTEGER DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS item_description TEXT DEFAULT NULL;
''')
cur.execute('''
  CREATE UNIQUE INDEX IF NOT EXISTS idx_match_message_item
    ON financeone.transaction_slack_match(slack_message_id, item_index)
    WHERE is_confirmed = true AND item_index IS NOT NULL;
''')
conn.commit()
cur.close()
conn.close()
print('OK: columns added')
"
```

Expected: `OK: columns added`

- [ ] **Step 3: Commit**

```bash
git add backend/database/schema.sql
git commit -m "schema: transaction_slack_match에 item_index, item_description 컬럼 추가"
```

---

### Task 2: 백엔드 — 개별 항목 후보 검색 API

**Files:**
- Modify: `backend/routers/slack.py:157-330` (get_candidates 함수)
- Test: `backend/tests/test_slack_item_match.py`

- [ ] **Step 1: 테스트 파일 생성 — 개별 항목 후보 검색**

`backend/tests/test_slack_item_match.py` 생성:

```python
"""다중 항목 개별 매칭 API 테스트"""

import pytest
import json
from unittest.mock import MagicMock, patch


def make_mock_cursor(rows=None, fetchone_val=None):
    """테스트용 mock cursor 생성"""
    cur = MagicMock()
    if rows is not None:
        cur.fetchall.return_value = rows
    if fetchone_val is not None:
        cur.fetchone.return_value = fetchone_val
    cur.description = []
    return cur


class TestGetCandidatesItemIndex:
    """GET /api/slack/messages/{id}/candidates?item_index=N 테스트"""

    def test_item_index_extracts_single_item_amount(self):
        """item_index 지정 시 해당 항목 금액만으로 검색해야 함"""
        from backend.routers.slack import _build_search_amounts

        structured = {
            "total_amount": 1811250,
            "items": [
                {"description": "설치", "amount": 1350000, "currency": "KRW"},
                {"description": "제거", "amount": 400000, "currency": "KRW"},
                {"description": "수수료", "amount": 61250, "currency": "KRW"},
            ],
            "vendor": "현수막업체",
        }

        # item_index=0 → 설치 1,350,000만
        amounts = _build_search_amounts(structured, parsed_amount=None, item_index=0)
        assert len(amounts) == 1
        assert amounts[0]["amount"] == 1350000
        assert amounts[0]["label"] == "설치"

    def test_item_index_none_uses_all_amounts(self):
        """item_index 미지정 시 total + 모든 items 금액 사용 (기존 동작)"""
        from backend.routers.slack import _build_search_amounts

        structured = {
            "total_amount": 1811250,
            "items": [
                {"description": "설치", "amount": 1350000, "currency": "KRW"},
                {"description": "제거", "amount": 400000, "currency": "KRW"},
            ],
        }

        amounts = _build_search_amounts(structured, parsed_amount=None, item_index=None)
        assert len(amounts) == 3  # total + 2 items
        assert amounts[0]["amount"] == 1811250

    def test_item_index_out_of_range(self):
        """item_index가 범위 밖이면 빈 목록 반환"""
        from backend.routers.slack import _build_search_amounts

        structured = {
            "total_amount": 100000,
            "items": [{"description": "A", "amount": 100000, "currency": "KRW"}],
        }

        amounts = _build_search_amounts(structured, parsed_amount=None, item_index=5)
        assert len(amounts) == 0

    def test_no_structured_data_fallback(self):
        """structured 없으면 parsed_amount fallback"""
        from backend.routers.slack import _build_search_amounts

        amounts = _build_search_amounts({}, parsed_amount=50000, item_index=None)
        assert len(amounts) == 1
        assert amounts[0]["amount"] == 50000


class TestBuildExcludedTransactions:
    """이미 매칭된 거래 제외 로직 테스트"""

    def test_excludes_confirmed_from_same_message(self):
        """같은 메시지의 다른 항목에 확정된 거래는 제외해야 함"""
        from backend.routers.slack import _get_excluded_transaction_ids

        cur = make_mock_cursor(rows=[(100,), (200,)])
        excluded = _get_excluded_transaction_ids(cur, message_id=1339)
        assert 100 in excluded
        assert 200 in excluded
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_item_match.py -v
```

Expected: FAIL — `_build_search_amounts` 함수 없음

- [ ] **Step 3: _build_search_amounts 헬퍼 함수 구현**

`backend/routers/slack.py` 상단 (IgnoreMessage 클래스 아래)에 추가:

```python
def _build_search_amounts(
    ps: dict,
    parsed_amount: float | None,
    item_index: int | None = None,
) -> list[dict]:
    """매칭 후보 검색에 사용할 금액 목록 생성.

    item_index 지정 시 해당 항목 금액만 반환.
    미지정 시 total_amount + 모든 items + parsed_amount fallback.
    """
    if not ps:
        ps = {}

    structured_total = ps.get("total_amount")
    structured_items = ps.get("items") or []

    # 개별 항목 모드
    if item_index is not None:
        if 0 <= item_index < len(structured_items):
            item = structured_items[item_index]
            item_amt = item.get("amount")
            if item_amt and item_amt > 0:
                return [{"amount": float(item_amt), "label": item.get("description", "")[:30]}]
        return []

    # 전체 모드 (기존 동작)
    search_amounts: list[dict] = []

    if structured_total and structured_total > 0:
        search_amounts.append({"amount": float(structured_total), "label": "총액"})

    for item in structured_items:
        item_amt = item.get("amount")
        if item_amt and item_amt > 0:
            desc = item.get("description", "")[:30]
            search_amounts.append({"amount": float(item_amt), "label": desc})

    if parsed_amount is not None and not search_amounts:
        search_amounts.append({"amount": float(parsed_amount), "label": "파싱금액"})

    return search_amounts


def _get_excluded_transaction_ids(cur, message_id: int) -> set[int]:
    """이미 확정된 매칭의 transaction_id 집합 반환.

    1) 전역: 다른 메시지에 확정된 거래
    2) 같은 메시지: 다른 항목에 확정된 거래
    """
    cur.execute(
        "SELECT transaction_id FROM transaction_slack_match WHERE is_confirmed = true",
    )
    return {row[0] for row in cur.fetchall()}
```

- [ ] **Step 4: get_candidates에 item_index 파라미터 추가**

`backend/routers/slack.py`의 `get_candidates` 함수 시그니처와 본문 수정:

```python
@router.get("/messages/{message_id}/candidates")
def get_candidates(
    message_id: int,
    item_index: Optional[int] = Query(None, description="개별 항목 인덱스 (0-based)"),
    conn: PgConnection = Depends(get_db),
):
```

기존 `search_amounts` 생성 코드 블록(라인 195~208)을 교체:

```python
    search_amounts = _build_search_amounts(ps, parsed_amount, item_index)
```

기존 `NOT IN` 서브쿼리(라인 239~241)를 교체:

```python
    excluded_ids = _get_excluded_transaction_ids(cur, message_id)
    if excluded_ids:
        placeholders = ",".join(["%s"] * len(excluded_ids))
        where_parts.append(f"t.id NOT IN ({placeholders})")
        params.extend(list(excluded_ids))
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_item_match.py -v
```

Expected: 4 passed

- [ ] **Step 6: 기존 테스트 회귀 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/ -v --tb=short
```

Expected: 172+ tests passed (기존 + 신규 4)

- [ ] **Step 7: Commit**

```bash
git add backend/routers/slack.py backend/tests/test_slack_item_match.py
git commit -m "feat: 후보 검색 API에 item_index 파라미터 추가 — 개별 항목 금액으로 검색"
```

---

### Task 3: 백엔드 — 개별 항목 매칭 확정 API

**Files:**
- Modify: `backend/routers/slack.py:333-393` (confirm_match 함수)
- Modify: `backend/routers/slack.py:20-28` (ConfirmMatch 모델)
- Test: `backend/tests/test_slack_item_match.py`

- [ ] **Step 1: 테스트 추가 — 개별 항목 확정**

`backend/tests/test_slack_item_match.py`에 추가:

```python
class TestConfirmItemMatch:
    """POST /api/slack/messages/{id}/confirm with item_index 테스트"""

    def test_confirm_body_accepts_item_fields(self):
        """ConfirmMatch 모델이 item_index, item_description 필드 허용"""
        from backend.routers.slack import ConfirmMatch

        body = ConfirmMatch(
            transaction_id=100,
            item_index=0,
            item_description="설치",
        )
        assert body.item_index == 0
        assert body.item_description == "설치"

    def test_confirm_body_item_fields_optional(self):
        """기존 동작: item_index 미지정 시 None"""
        from backend.routers.slack import ConfirmMatch

        body = ConfirmMatch(transaction_id=100)
        assert body.item_index is None
        assert body.item_description is None
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_item_match.py::TestConfirmItemMatch -v
```

Expected: FAIL — `item_index` field not recognized

- [ ] **Step 3: ConfirmMatch 모델에 필드 추가**

`backend/routers/slack.py`의 `ConfirmMatch` 클래스 수정:

```python
class ConfirmMatch(BaseModel):
    transaction_id: int
    match_confidence: Optional[float] = None
    ai_reasoning: Optional[str] = None
    note: Optional[str] = None
    amount_override: Optional[float] = None
    text_override: Optional[str] = None
    project_tag_override: Optional[str] = None
    item_index: Optional[int] = None
    item_description: Optional[str] = None
```

- [ ] **Step 4: confirm_match 함수 — 개별 항목 매칭 로직 추가**

`backend/routers/slack.py`의 `confirm_match` 함수 본문을 교체:

```python
@router.post("/messages/{message_id}/confirm")
def confirm_match(
    message_id: int,
    body: ConfirmMatch,
    conn: PgConnection = Depends(get_db),
):
    """Create a transaction_slack_match record and mark message as completed."""
    cur = conn.cursor()
    try:
        # Verify slack message exists
        cur.execute(
            "SELECT id, entity_id, parsed_structured FROM slack_messages WHERE id = %s",
            [message_id],
        )
        msg = cur.fetchone()
        if not msg:
            raise HTTPException(404, "Slack message not found")

        _, _, parsed_structured = msg

        # Verify transaction exists
        cur.execute("SELECT id FROM transactions WHERE id = %s", [body.transaction_id])
        if not cur.fetchone():
            raise HTTPException(404, "Transaction not found")

        # Check for existing confirmed match
        if body.item_index is not None:
            # 개별 항목: 같은 (message_id, item_index) 중복 체크
            cur.execute(
                """SELECT id FROM transaction_slack_match
                   WHERE slack_message_id = %s AND item_index = %s AND is_confirmed = true""",
                [message_id, body.item_index],
            )
        else:
            # 전체 매칭: 기존 동작
            cur.execute(
                """SELECT id FROM transaction_slack_match
                   WHERE slack_message_id = %s AND is_confirmed = true AND item_index IS NULL""",
                [message_id],
            )
        if cur.fetchone():
            raise HTTPException(409, "이 항목은 이미 매칭이 확정되었습니다.")

        # Create match record
        cur.execute(
            """
            INSERT INTO transaction_slack_match
                (transaction_id, slack_message_id, match_confidence, is_manual, is_confirmed,
                 ai_reasoning, note, amount_override, text_override, project_tag_override,
                 item_index, item_description)
            VALUES (%s, %s, %s, true, true, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            [
                body.transaction_id, message_id,
                body.match_confidence or 1.0,
                body.ai_reasoning, body.note,
                body.amount_override, body.text_override, body.project_tag_override,
                body.item_index, body.item_description,
            ],
        )
        match_id = cur.fetchone()[0]

        # is_completed 판단
        ps = parsed_structured if isinstance(parsed_structured, dict) else {}
        items = ps.get("items") or []

        if body.item_index is not None and len(items) >= 2:
            # 개별 매칭 모드: 모든 항목이 확정되었는지 확인
            cur.execute(
                """SELECT COUNT(*) FROM transaction_slack_match
                   WHERE slack_message_id = %s AND is_confirmed = true AND item_index IS NOT NULL""",
                [message_id],
            )
            confirmed_count = cur.fetchone()[0]
            is_completed = confirmed_count >= len(items)
        else:
            # 전체 매칭 또는 단일 항목: 즉시 완료
            is_completed = True

        cur.execute(
            "UPDATE slack_messages SET is_completed = %s WHERE id = %s",
            [is_completed, message_id],
        )

        conn.commit()
        cur.close()
        return {
            "match_id": match_id,
            "message_id": message_id,
            "confirmed": True,
            "is_completed": is_completed,
            "item_index": body.item_index,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_item_match.py -v
```

Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/routers/slack.py backend/tests/test_slack_item_match.py
git commit -m "feat: confirm API에 item_index 지원 — 개별 항목 매칭 확정 + is_completed 재계산"
```

---

### Task 4: 백엔드 — 개별 매칭 확정 취소 + 무시 API

**Files:**
- Modify: `backend/routers/slack.py` (신규 엔드포인트 + ignore 수정)
- Test: `backend/tests/test_slack_item_match.py`

- [ ] **Step 1: 테스트 추가 — 확정 취소**

`backend/tests/test_slack_item_match.py`에 추가:

```python
class TestUndoItemMatch:
    """DELETE /api/slack/messages/{id}/match/{item_index} 테스트"""

    def test_undo_body_model(self):
        """UndoItemMatch 엔드포인트가 존재하는지 확인"""
        from backend.routers.slack import router
        routes = [r.path for r in router.routes]
        assert "/messages/{message_id}/match/{item_index}" in routes
```

- [ ] **Step 2: 확정 취소 엔드포인트 구현**

`backend/routers/slack.py`에 `confirm_match` 함수 아래에 추가:

```python
@router.delete("/messages/{message_id}/match/{item_index}")
def undo_item_match(
    message_id: int,
    item_index: int,
    conn: PgConnection = Depends(get_db),
):
    """개별 항목 매칭 확정 취소."""
    cur = conn.cursor()
    try:
        # 매칭 레코드 삭제
        cur.execute(
            """DELETE FROM transaction_slack_match
               WHERE slack_message_id = %s AND item_index = %s AND is_confirmed = true
               RETURNING id""",
            [message_id, item_index],
        )
        deleted = cur.fetchone()
        if not deleted:
            raise HTTPException(404, "해당 항목의 매칭 기록이 없습니다.")

        # is_completed 재계산
        cur.execute(
            "SELECT parsed_structured FROM slack_messages WHERE id = %s",
            [message_id],
        )
        msg = cur.fetchone()
        if msg:
            ps = msg[0] if isinstance(msg[0], dict) else {}
            items = ps.get("items") or []
            if len(items) >= 2:
                cur.execute(
                    """SELECT COUNT(*) FROM transaction_slack_match
                       WHERE slack_message_id = %s AND is_confirmed = true AND item_index IS NOT NULL""",
                    [message_id],
                )
                confirmed_count = cur.fetchone()[0]
                is_completed = confirmed_count >= len(items)
            else:
                is_completed = False

            cur.execute(
                "UPDATE slack_messages SET is_completed = %s WHERE id = %s",
                [is_completed, message_id],
            )

        conn.commit()
        cur.close()
        return {"message_id": message_id, "item_index": item_index, "undone": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
```

- [ ] **Step 3: ignore_message 수정 — 부분 매칭 경고 처리**

`backend/routers/slack.py`의 `ignore_message` 함수 수정:

```python
@router.post("/messages/{message_id}/ignore")
def ignore_message(
    message_id: int,
    body: IgnoreMessage,
    conn: PgConnection = Depends(get_db),
):
    """Mark a slack message as cancelled/ignored. 부분 매칭 시 매칭 레코드도 삭제."""
    cur = conn.cursor()
    try:
        # 부분 매칭 레코드 삭제
        cur.execute(
            "DELETE FROM transaction_slack_match WHERE slack_message_id = %s AND is_confirmed = true",
            [message_id],
        )

        cur.execute(
            "UPDATE slack_messages SET is_cancelled = true, is_completed = false WHERE id = %s RETURNING id",
            [message_id],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Slack message not found")

        conn.commit()
        cur.close()
        return {"message_id": message_id, "ignored": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
```

- [ ] **Step 4: 테스트 실행**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_item_match.py -v
```

Expected: 7 passed

- [ ] **Step 5: 전체 테스트 회귀 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/ -v --tb=short
```

Expected: 176+ tests passed

- [ ] **Step 6: Commit**

```bash
git add backend/routers/slack.py backend/tests/test_slack_item_match.py
git commit -m "feat: 개별 매칭 확정 취소(DELETE) + 무시 시 매칭 레코드 정리"
```

---

### Task 5: 백엔드 — list_messages에 item_matches 응답 추가

**Files:**
- Modify: `backend/routers/slack.py:36-154` (list_slack_messages 함수)
- Test: `backend/tests/test_slack_item_match.py`

- [ ] **Step 1: 테스트 추가**

`backend/tests/test_slack_item_match.py`에 추가:

```python
class TestBuildItemMatches:
    """item_matches 응답 빌드 로직 테스트"""

    def test_builds_item_matches_for_multi_item(self):
        """items ≥ 2인 메시지에 item_matches 배열 생성"""
        from backend.routers.slack import _build_item_matches

        parsed_structured = {
            "items": [
                {"description": "설치", "amount": 1350000, "currency": "KRW"},
                {"description": "제거", "amount": 400000, "currency": "KRW"},
            ],
        }
        # 매칭 레코드: item_index=0만 확정
        match_rows = [
            {"item_index": 0, "item_description": "설치", "transaction_id": 6001, "is_confirmed": True},
        ]

        result = _build_item_matches(parsed_structured, match_rows)
        assert result["match_progress"]["total_items"] == 2
        assert result["match_progress"]["matched_items"] == 1
        assert len(result["item_matches"]) == 2
        assert result["item_matches"][0]["is_confirmed"] is True
        assert result["item_matches"][1]["is_confirmed"] is False

    def test_returns_none_for_single_item(self):
        """items < 2이면 None 반환"""
        from backend.routers.slack import _build_item_matches

        parsed_structured = {
            "items": [{"description": "A", "amount": 100000, "currency": "KRW"}],
        }
        result = _build_item_matches(parsed_structured, [])
        assert result is None

    def test_returns_none_for_no_structured(self):
        """structured 없으면 None 반환"""
        from backend.routers.slack import _build_item_matches

        result = _build_item_matches(None, [])
        assert result is None
```

- [ ] **Step 2: _build_item_matches 헬퍼 구현**

`backend/routers/slack.py`에 `_get_excluded_transaction_ids` 아래에 추가:

```python
def _build_item_matches(
    parsed_structured: dict | None,
    match_rows: list[dict],
) -> dict | None:
    """다중 항목 메시지의 항목별 매칭 상태를 빌드.

    items < 2이면 None 반환 (개별 매칭 해당 없음).
    """
    if not parsed_structured or not isinstance(parsed_structured, dict):
        return None

    items = parsed_structured.get("items") or []
    if len(items) < 2:
        return None

    # match_rows를 item_index로 인덱싱
    match_by_index = {}
    for mr in match_rows:
        idx = mr.get("item_index")
        if idx is not None:
            match_by_index[idx] = mr

    item_matches = []
    matched_count = 0
    for i, item in enumerate(items):
        mr = match_by_index.get(i)
        is_confirmed = bool(mr and mr.get("is_confirmed"))
        if is_confirmed:
            matched_count += 1
        item_matches.append({
            "item_index": i,
            "item_description": item.get("description", ""),
            "amount": item.get("amount"),
            "currency": item.get("currency", "KRW"),
            "transaction_id": mr["transaction_id"] if mr else None,
            "is_confirmed": is_confirmed,
        })

    return {
        "item_matches": item_matches,
        "match_progress": {
            "total_items": len(items),
            "matched_items": matched_count,
        },
    }
```

- [ ] **Step 3: list_slack_messages 쿼리 수정**

`backend/routers/slack.py`의 `list_slack_messages` 함수에서, 기존 LEFT JOIN을 수정하여 item별 매칭도 가져오기. `cur.close()` 직전(rows 리턴 가공 부분)에 다음 로직 추가:

```python
    # ── 항목별 매칭 상태 조회 ──
    message_ids = [r["id"] for r in rows]
    item_match_map = {}
    if message_ids:
        placeholders = ",".join(["%s"] * len(message_ids))
        cur3 = conn.cursor()
        cur3.execute(
            f"""SELECT slack_message_id, item_index, item_description,
                       transaction_id, is_confirmed
                FROM transaction_slack_match
                WHERE slack_message_id IN ({placeholders})
                  AND item_index IS NOT NULL AND is_confirmed = true
                ORDER BY slack_message_id, item_index""",
            message_ids,
        )
        for match_row in fetch_all(cur3):
            mid = match_row["slack_message_id"]
            if mid not in item_match_map:
                item_match_map[mid] = []
            item_match_map[mid].append(match_row)
        cur3.close()

    # 각 메시지에 item_matches 추가
    for row in rows:
        ps = row.get("parsed_structured")
        match_rows_for_msg = item_match_map.get(row["id"], [])
        item_data = _build_item_matches(ps, match_rows_for_msg)
        if item_data:
            row["item_matches"] = item_data["item_matches"]
            row["match_progress"] = item_data["match_progress"]
```

- [ ] **Step 4: 테스트 실행**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_item_match.py -v
```

Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/routers/slack.py backend/tests/test_slack_item_match.py
git commit -m "feat: list_messages 응답에 item_matches, match_progress 추가"
```

---

### Task 6: 프론트엔드 — 타입 + shadcn Tabs 설치 확인

**Files:**
- Modify: `frontend/src/app/slack-match/page.tsx` (타입 정의부)

- [ ] **Step 1: shadcn Tabs 컴포넌트 확인/설치**

```bash
ls frontend/src/components/ui/tabs.tsx 2>/dev/null && echo "EXISTS" || (cd frontend && npx shadcn@latest add tabs -y)
```

- [ ] **Step 2: 타입 정의 추가**

`frontend/src/app/slack-match/page.tsx`의 타입 섹션에 추가:

```typescript
interface ItemMatch {
  item_index: number
  item_description: string
  amount: number | null
  currency: string
  transaction_id: number | null
  is_confirmed: boolean
}

interface MatchProgress {
  total_items: number
  matched_items: number
}
```

그리고 `SlackMessage` 인터페이스에 필드 추가:

```typescript
interface SlackMessage {
  // ... 기존 필드 유지 ...
  item_matches?: ItemMatch[]
  match_progress?: MatchProgress
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx frontend/src/components/ui/tabs.tsx
git commit -m "feat: 개별 매칭 타입 정의 + shadcn Tabs 컴포넌트"
```

---

### Task 7: 프론트엔드 — 후보 패널에 탭 + 항목 테이블 추가

**Files:**
- Modify: `frontend/src/app/slack-match/page.tsx` (후보 패널 영역)

이 태스크가 프론트엔드 핵심. 기존 후보 패널 컴포넌트를 탭 구조로 감싸고, 개별 매칭 탭에 항목 테이블 + 항목별 후보를 표시한다.

- [ ] **Step 1: 상태 변수 추가**

페이지 컴포넌트 내부에 상태 추가:

```typescript
const [activeItemIndex, setActiveItemIndex] = useState<number | null>(null)
const [itemCandidates, setItemCandidates] = useState<MatchCandidate[]>([])
const [itemCandidatesLoading, setItemCandidatesLoading] = useState(false)
const [selectedItemCandidate, setSelectedItemCandidate] = useState<number | null>(null)
```

- [ ] **Step 2: 항목별 후보 fetch 함수**

```typescript
const fetchItemCandidates = useCallback(async (messageId: number, itemIdx: number) => {
  setItemCandidatesLoading(true)
  setSelectedItemCandidate(null)
  try {
    const data = await fetchAPI(
      `/api/slack/messages/${messageId}/candidates?item_index=${itemIdx}`
    )
    setItemCandidates(data.candidates || [])
  } catch {
    toast.error("후보 검색 중 오류가 발생했습니다")
    setItemCandidates([])
  } finally {
    setItemCandidatesLoading(false)
  }
}, [])
```

- [ ] **Step 3: 항목 확정 함수**

```typescript
const confirmItemMatch = useCallback(async (
  messageId: number,
  transactionId: number,
  itemIndex: number,
  itemDescription: string,
) => {
  try {
    const res = await fetchAPI(`/api/slack/messages/${messageId}/confirm`, {
      method: "POST",
      body: JSON.stringify({
        transaction_id: transactionId,
        item_index: itemIndex,
        item_description: itemDescription,
      }),
    })
    toast.success(`✓ ${itemDescription} 매칭 완료`)

    // 메시지 리스트 갱신
    await loadMessages()

    // 자동 다음 미매칭 항목 이동
    if (!res.is_completed) {
      const msg = messages.find(m => m.id === messageId)
      const items = msg?.parsed_structured?.items || []
      const matches = msg?.item_matches || []
      const confirmedIndices = new Set([
        ...matches.filter(m => m.is_confirmed).map(m => m.item_index),
        itemIndex,
      ])
      const nextUnmatched = items.findIndex((_, i) => !confirmedIndices.has(i))
      if (nextUnmatched >= 0) {
        setTimeout(() => {
          setActiveItemIndex(nextUnmatched)
          fetchItemCandidates(messageId, nextUnmatched)
        }, 300)
      }
    } else {
      toast.success("전체 매칭 완료!")
      setActiveItemIndex(null)
    }
  } catch {
    toast.error("매칭 확정에 실패했습니다")
  }
}, [messages, loadMessages, fetchItemCandidates])
```

- [ ] **Step 4: 항목 확정 취소 함수**

```typescript
const undoItemMatch = useCallback(async (messageId: number, itemIndex: number) => {
  try {
    await fetchAPI(`/api/slack/messages/${messageId}/match/${itemIndex}`, {
      method: "DELETE",
    })
    toast.success("매칭이 취소되었습니다")
    await loadMessages()
    setActiveItemIndex(null)
  } catch {
    toast.error("매칭 취소에 실패했습니다")
  }
}, [loadMessages])
```

- [ ] **Step 5: 후보 패널 JSX — 탭 구조**

기존 후보 패널(candidates 표시 영역)을 다음으로 교체. `Tabs` import 필요:

```typescript
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
```

후보 패널 렌더링:

```tsx
{/* 후보 패널 */}
{selectedMessage && (
  <div className="space-y-3">
    <h3 className="text-sm font-medium text-muted-foreground">매칭 후보</h3>

    {/* 다중 항목: 탭 표시 */}
    {selectedMessage.parsed_structured?.items &&
     selectedMessage.parsed_structured.items.length >= 2 ? (
      <Tabs defaultValue="total">
        <TabsList className="w-full">
          <TabsTrigger value="total" className="flex-1">전체 매칭</TabsTrigger>
          <TabsTrigger value="items" className="flex-1">
            개별 매칭
            <Badge variant="secondary" className="ml-1.5 text-[10px] px-1.5">
              {selectedMessage.parsed_structured.items.length}
            </Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="total" className="mt-3">
          {/* 기존 전체 매칭 후보 리스트 */}
          {renderCandidatesList(candidates, selectedCandidate, setSelectedCandidate)}
          {selectedCandidate && (
            <Button
              className="w-full mt-2"
              onClick={() => handleConfirm(selectedMessage.id, selectedCandidate)}
            >
              확정
            </Button>
          )}
        </TabsContent>

        <TabsContent value="items" className="mt-3 space-y-3">
          {/* 항목 테이블 */}
          <div className="rounded-md border border-border overflow-hidden">
            {selectedMessage.parsed_structured.items.map((item, idx) => {
              const match = selectedMessage.item_matches?.find(m => m.item_index === idx)
              const isActive = activeItemIndex === idx
              const isConfirmed = match?.is_confirmed

              return (
                <div
                  key={idx}
                  role="option"
                  aria-selected={isActive}
                  aria-label={`${item.description} 항목, ${formatKRW(item.amount)}원, ${isConfirmed ? '확정' : '미매칭'}`}
                  className={cn(
                    "flex items-center justify-between px-3 py-2 cursor-pointer border-b border-border last:border-b-0 transition-colors",
                    isActive && "bg-yellow-500/10",
                    isConfirmed && "bg-emerald-500/10",
                    !isActive && !isConfirmed && "hover:bg-muted/50",
                  )}
                  onClick={() => {
                    if (!isConfirmed) {
                      setActiveItemIndex(idx)
                      fetchItemCandidates(selectedMessage.id, idx)
                    }
                  }}
                >
                  <div className="flex items-center gap-2">
                    {isActive && <span className="text-yellow-400 text-xs">▶</span>}
                    {isConfirmed && <Check className="w-3.5 h-3.5 text-emerald-400" />}
                    <span className={cn("text-sm", isConfirmed && "text-emerald-400")}>
                      {item.description}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono">{formatKRW(item.amount)}</span>
                    {isConfirmed ? (
                      <button
                        className="text-xs text-muted-foreground hover:text-red-400 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation()
                          undoItemMatch(selectedMessage.id, idx)
                        }}
                      >
                        취소
                      </button>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        {isActive ? "선택중" : "미매칭"}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
            {/* 합계 행 */}
            <div className="flex items-center justify-between px-3 py-2 bg-muted/30 text-sm">
              <span className="font-medium">합계</span>
              <div className="flex items-center gap-2">
                <span className="font-mono">
                  {formatKRW(selectedMessage.parsed_structured.items.reduce((s, i) => s + (i.amount || 0), 0))}
                </span>
                {selectedMessage.match_progress && (
                  <Badge variant="outline" className="text-[10px]">
                    {selectedMessage.match_progress.matched_items}/{selectedMessage.match_progress.total_items}
                  </Badge>
                )}
              </div>
            </div>
          </div>

          {/* 항목별 후보 리스트 */}
          {activeItemIndex !== null && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                "{selectedMessage.parsed_structured.items[activeItemIndex]?.description}" 후보
              </p>
              {itemCandidatesLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                </div>
              ) : itemCandidates.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">
                  이 금액에 맞는 거래를 찾지 못했습니다
                </p>
              ) : (
                <>
                  {renderCandidatesList(itemCandidates, selectedItemCandidate, setSelectedItemCandidate)}
                  {selectedItemCandidate && (
                    <Button
                      className="w-full"
                      onClick={() => {
                        const item = selectedMessage.parsed_structured!.items![activeItemIndex]
                        confirmItemMatch(
                          selectedMessage.id,
                          selectedItemCandidate,
                          activeItemIndex,
                          item.description,
                        )
                      }}
                    >
                      확정
                    </Button>
                  )}
                </>
              )}
            </div>
          )}
        </TabsContent>
      </Tabs>
    ) : (
      /* 단일 항목: 기존 후보 리스트 (탭 없음) */
      <>
        {renderCandidatesList(candidates, selectedCandidate, setSelectedCandidate)}
        {selectedCandidate && (
          <Button
            className="w-full mt-2"
            onClick={() => handleConfirm(selectedMessage.id, selectedCandidate)}
          >
            확정
          </Button>
        )}
      </>
    )}
  </div>
)}
```

- [ ] **Step 6: renderCandidatesList 헬퍼 추출**

기존 후보 카드 렌더링 코드를 재사용 가능한 함수로 추출:

```typescript
function renderCandidatesList(
  candidates: MatchCandidate[],
  selectedId: number | null,
  onSelect: (id: number | null) => void,
) {
  if (candidates.length === 0) {
    return <p className="text-sm text-muted-foreground py-4 text-center">매칭 후보가 없습니다</p>
  }

  return (
    <div className="space-y-1.5">
      {candidates.map((c) => (
        <div
          key={c.id}
          role="option"
          aria-selected={selectedId === c.id}
          className={cn(
            "p-2.5 rounded-md border cursor-pointer transition-colors",
            selectedId === c.id
              ? "border-emerald-500 bg-emerald-500/10"
              : "border-border hover:border-muted-foreground/30",
          )}
          onClick={() => onSelect(selectedId === c.id ? null : c.id)}
        >
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <span className="text-muted-foreground">{formatDate(c.date)}</span>
              {" "}
              <span>{c.counterparty || c.description}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-mono">{formatKRW(c.amount)}</span>
              {getConfidenceBadge(c.confidence)}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx
git commit -m "feat: 후보 패널에 탭 구조 + 개별 매칭 항목 테이블 + 항목별 후보 검색"
```

---

### Task 8: 프론트엔드 — 메시지 카드 진행률 + 키보드 단축키

**Files:**
- Modify: `frontend/src/app/slack-match/page.tsx` (메시지 카드 영역 + 키보드 핸들러)

- [ ] **Step 1: 메시지 카드에 진행률 Badge 추가**

메시지 카드 컴팩트 뷰에서, 금액 표시 영역 옆에 match_progress 표시:

```tsx
{/* 기존 금액 표시 코드 옆에 추가 */}
{msg.match_progress && !msg.is_completed && (
  <Badge
    variant="outline"
    className="text-[10px] px-1.5 py-0 bg-yellow-500/10 text-yellow-400 border-yellow-500/30"
  >
    {msg.match_progress.matched_items}/{msg.match_progress.total_items}
  </Badge>
)}
```

메시지 상태 판단 함수 `getMessageStatus`도 수정:

```typescript
function getMessageStatus(msg: SlackMessage): "confirmed" | "ignored" | "pending" | "partial" {
  if (msg.is_completed && msg.matched_transaction_id) return "confirmed"
  if (msg.is_completed && msg.match_progress?.matched_items === msg.match_progress?.total_items) return "confirmed"
  if (msg.is_cancelled) return "ignored"
  if (msg.match_progress && msg.match_progress.matched_items > 0) return "partial"
  return "pending"
}
```

상태 도트 색상에 "partial" 추가:

```tsx
{status === "partial" && <div className="w-2 h-2 rounded-full bg-yellow-400" />}
```

- [ ] **Step 2: 키보드 단축키 확장**

기존 키보드 핸들러에 개별 매칭 모드 단축키 추가:

```typescript
// 기존 키보드 핸들러 내부에 추가
if (e.key === "Escape" && activeItemIndex !== null) {
  setActiveItemIndex(null)
  setItemCandidates([])
  e.preventDefault()
  return
}

if (e.key === "ArrowUp" && activeItemIndex !== null && itemCandidates.length > 0) {
  // 후보 리스트에서 위로 이동
  const currentIdx = itemCandidates.findIndex(c => c.id === selectedItemCandidate)
  if (currentIdx > 0) {
    setSelectedItemCandidate(itemCandidates[currentIdx - 1].id)
  }
  e.preventDefault()
  return
}

if (e.key === "ArrowDown" && activeItemIndex !== null && itemCandidates.length > 0) {
  // 후보 리스트에서 아래로 이동
  const currentIdx = itemCandidates.findIndex(c => c.id === selectedItemCandidate)
  if (currentIdx < itemCandidates.length - 1) {
    setSelectedItemCandidate(itemCandidates[currentIdx + 1].id)
  } else if (currentIdx === -1) {
    setSelectedItemCandidate(itemCandidates[0].id)
  }
  e.preventDefault()
  return
}
```

- [ ] **Step 3: 무시 시 경고 다이얼로그 (부분 매칭)**

기존 무시 핸들러를 수정:

```typescript
const handleIgnore = useCallback(async (messageId: number) => {
  const msg = messages.find(m => m.id === messageId)
  if (msg?.match_progress && msg.match_progress.matched_items > 0) {
    const confirmed = window.confirm(
      `${msg.match_progress.matched_items}개 항목이 매칭됨. 무시하면 매칭도 해제됩니다. 계속?`
    )
    if (!confirmed) return
  }

  try {
    await fetchAPI(`/api/slack/messages/${messageId}/ignore`, {
      method: "POST",
      body: JSON.stringify({}),
    })
    toast.success("메시지를 무시했습니다")
    await loadMessages()
  } catch {
    toast.error("무시 처리에 실패했습니다")
  }
}, [messages, loadMessages])
```

- [ ] **Step 4: 프론트엔드 빌드 확인**

```bash
cd frontend && npm run build
```

Expected: 빌드 성공, 에러 없음

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx
git commit -m "feat: 메시지 카드 진행률 Badge + partial 상태 + 키보드 단축키 + 무시 경고"
```

---

### Task 9: 통합 테스트 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 전체 백엔드 테스트**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/ -v --tb=short
```

Expected: 176+ tests passed

- [ ] **Step 2: 프론트엔드 빌드**

```bash
cd frontend && npm run build
```

Expected: 빌드 성공

- [ ] **Step 3: CHANGELOG 업데이트**

`CHANGELOG.md` 상단에 추가:

```markdown
## v0.7.1 — 다중 항목 개별 매칭 (2026-03-30)

### Added
- Slack 메시지의 다중 비용 항목을 각각 별도 거래에 개별 매칭하는 워크플로우
- 후보 패널에 [전체 매칭] / [개별 매칭] 탭 (shadcn/ui Tabs)
- 항목 테이블: 클릭 → 해당 금액 기준 후보 검색 → 개별 확정
- 확정 후 자동으로 다음 미매칭 항목 이동 + 토스트 알림
- 메시지 카드에 매칭 진행률 Badge (예: 2/3)
- 개별 매칭 확정 취소(undo) 기능
- items 합계 ≠ total_amount 경고
- 키보드: Arrow ↑↓ (후보 이동), Escape (항목 선택 해제)

### Changed
- transaction_slack_match 테이블에 item_index, item_description 컬럼 추가
- confirm API에 item_index/item_description 파라미터 지원
- candidates API에 item_index 쿼리 파라미터 지원
- list_messages 응답에 item_matches, match_progress 필드 추가
- ignore 시 부분 매칭 레코드 자동 정리 + 경고 다이얼로그
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG v0.7.1 — 다중 항목 개별 매칭"
```

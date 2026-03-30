# Slack 구조화 파싱 엔진 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** sync 시 Claude Sonnet API로 Slack 경비 메시지를 구조화된 JSON으로 변환하여 `parsed_structured` JSONB 컬럼에 저장하고, 프론트에서 구조화 테이블로 표시한다.

**Architecture:** 기존 regex 파싱(message_parser.py) 유지 + 새 `structured_parser.py`가 Claude Sonnet 4.6 structured output으로 보강. sync 플로우에서 regex → thread 분석 → Claude 파싱 순서로 실행. Claude 실패 시 regex 결과만 저장 (fallback). 프론트 카드 펼침 시 `parsed_structured` 유무에 따라 구조화 테이블 또는 기존 원문 표시.

**Tech Stack:** Python (anthropic SDK), FastAPI, PostgreSQL JSONB, Next.js 14, shadcn/ui

**Spec:** `docs/superpowers/specs/2026-03-30-slack-structured-parser-design.md`

---

## 파일 구조

| Action | File | 역할 |
|--------|------|------|
| Create | `backend/services/slack/structured_parser.py` | Claude Sonnet API 호출 + JSON 파싱 |
| Create | `backend/tests/test_structured_parser.py` | structured_parser 단위 테스트 |
| Modify | `backend/database/schema.sql:262-289` | slack_messages에 parsed_structured 컬럼 추가 |
| Modify | `backend/routers/slack.py:337-496` | sync 플로우에 구조화 파싱 단계 삽입 |
| Modify | `frontend/src/app/slack-match/page.tsx:42-59` | SlackMessage 타입에 parsed_structured 추가 |
| Modify | `frontend/src/app/slack-match/page.tsx:249-424` | CompactMessageRow 펼침 영역에 구조화 테이블 추가 |

---

### Task 1: DB 스키마 — parsed_structured 컬럼 추가

**Files:**
- Modify: `backend/database/schema.sql:262-289`

- [ ] **Step 1: schema.sql에 parsed_structured 컬럼 추가**

`backend/database/schema.sql`의 slack_messages 테이블 정의에서, `sub_amounts JSONB,` 줄 다음에 추가:

```sql
  parsed_structured           JSONB,
```

- [ ] **Step 2: Supabase에 ALTER TABLE 실행**

```bash
source .venv/bin/activate && python3 -c "
from backend.database.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute('''
  ALTER TABLE slack_messages
    ADD COLUMN IF NOT EXISTS parsed_structured JSONB DEFAULT NULL;
''')
conn.commit()
cur.close()
conn.close()
print('OK: parsed_structured column added')
"
```

Expected: `OK: parsed_structured column added`

- [ ] **Step 3: 컬럼 존재 확인**

```bash
source .venv/bin/activate && python3 -c "
from backend.database.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='financeone' AND table_name='slack_messages' AND column_name='parsed_structured'\")
row = cur.fetchone()
print(f'Column: {row[0]}, Type: {row[1]}')
cur.close()
conn.close()
"
```

Expected: `Column: parsed_structured, Type: jsonb`

- [ ] **Step 4: Commit**

```bash
git add backend/database/schema.sql
git commit -m "feat: slack_messages에 parsed_structured JSONB 컬럼 추가"
```

---

### Task 2: anthropic SDK 설치

**Files:**
- Modify: `requirements.txt` (if exists) or install directly

- [ ] **Step 1: anthropic 패키지 설치**

```bash
source .venv/bin/activate && pip install anthropic
```

- [ ] **Step 2: .env에 ANTHROPIC_API_KEY 확인**

```bash
grep "ANTHROPIC_API_KEY" .env || echo "MISSING"
```

If MISSING, 사용자에게 물어본다. `.env`에 추가:

```
ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 3: SDK 연결 테스트**

```bash
source .venv/bin/activate && python3 -c "
import anthropic
client = anthropic.Anthropic()
print(f'SDK version: {anthropic.__version__}')
print('API key loaded: OK')
"
```

Expected: SDK version 출력 + API key loaded: OK

- [ ] **Step 4: requirements.txt 업데이트 (있으면)**

```bash
source .venv/bin/activate && pip freeze | grep anthropic >> requirements.txt 2>/dev/null || echo "no requirements.txt"
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example 2>/dev/null; git add -u
git commit -m "feat: anthropic SDK 설치"
```

---

### Task 3: structured_parser.py — 핵심 파싱 모듈

**Files:**
- Create: `backend/services/slack/structured_parser.py`
- Create: `backend/tests/test_structured_parser.py`

- [ ] **Step 1: 테스트 파일 작성**

`backend/tests/test_structured_parser.py`:

```python
"""structured_parser 단위 테스트 — Claude API mock으로 검증."""

import json
import pytest
from unittest.mock import patch, MagicMock

from backend.services.slack.structured_parser import parse_structured, SYSTEM_PROMPT, build_user_prompt


# ── build_user_prompt 테스트 ──────────────────────────────

class TestBuildUserPrompt:
    def test_message_only(self):
        result = build_user_prompt("[ODD] 택시비 35,000원 결제완료", thread_replies=None)
        assert "[메시지 본문]" in result
        assert "택시비 35,000원" in result
        assert "[쓰레드 댓글]" not in result

    def test_with_thread_replies(self):
        replies = json.dumps([
            {"ts": "1", "user": "U1", "text": "입금완료"},
        ], ensure_ascii=False)
        result = build_user_prompt("[HAK] 입금요청 500,000원", thread_replies=replies)
        assert "[쓰레드 댓글]" in result
        assert "입금완료" in result

    def test_empty_text(self):
        result = build_user_prompt("", thread_replies=None)
        assert "[메시지 본문]" in result


# ── parse_structured 테스트 (Claude API mocked) ──────────

MOCK_RESPONSE = {
    "summary": "ODD 촬영 택시비",
    "vendor": "카카오택시",
    "project": "ODD",
    "category": "교통",
    "items": [{"description": "택시비", "amount": 35000, "currency": "KRW"}],
    "total_amount": 35000,
    "currency": "KRW",
    "vat": {"type": "none", "vat_amount": None, "supply_amount": None},
    "withholding_tax": {"applies": False, "rate": None, "amount": None, "net_amount": None},
    "payment_terms": {"type": "full", "ratio": None, "related_context": None},
    "tax_invoice": False,
    "date_mentioned": None,
    "urgency": None,
    "confidence": 0.95,
}


def _mock_anthropic_response(content_json: dict):
    """Anthropic SDK 응답 mock 생성."""
    mock_block = MagicMock()
    mock_block.text = json.dumps(content_json, ensure_ascii=False)
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage.input_tokens = 500
    mock_response.usage.output_tokens = 200
    return mock_response


class TestParseStructured:
    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_basic_parse(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.return_value = _mock_anthropic_response(MOCK_RESPONSE)

        result = parse_structured("[ODD] 택시비 35,000원 결제완료", thread_replies=None)

        assert result is not None
        assert result["summary"] == "ODD 촬영 택시비"
        assert result["vendor"] == "카카오택시"
        assert result["project"] == "ODD"
        assert result["total_amount"] == 35000
        assert result["confidence"] == 0.95

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_api_failure_returns_none(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.side_effect = Exception("API error")

        result = parse_structured("[ODD] 택시비 35,000원", thread_replies=None)

        assert result is None

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_invalid_json_returns_none(self, MockAnthropic):
        client = MockAnthropic.return_value
        mock_block = MagicMock()
        mock_block.text = "not valid json {{"
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        client.messages.create.return_value = mock_response

        result = parse_structured("[ODD] 택시비 35,000원", thread_replies=None)

        assert result is None

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_with_thread_replies(self, MockAnthropic):
        client = MockAnthropic.return_value
        response_with_deposit = {**MOCK_RESPONSE, "summary": "ODD 택시비 - 입금완료"}
        client.messages.create.return_value = _mock_anthropic_response(response_with_deposit)

        replies = json.dumps([{"ts": "1", "user": "U1", "text": "입금완료"}], ensure_ascii=False)
        result = parse_structured("[ODD] 택시비 35,000원", thread_replies=replies)

        assert result is not None
        assert "입금완료" in result["summary"]

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_skip_other_type(self, MockAnthropic):
        """message_type이 other이고 금액 없으면 호출하지 않음."""
        result = parse_structured("", thread_replies=None, skip=True)

        assert result is None
        MockAnthropic.return_value.messages.create.assert_not_called()


class TestSystemPrompt:
    def test_system_prompt_exists(self):
        assert len(SYSTEM_PROMPT) > 100
        assert "JSON" in SYSTEM_PROMPT
        assert "VAT" in SYSTEM_PROMPT
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_structured_parser.py -v 2>&1 | head -30
```

Expected: FAIL (모듈 없음)

- [ ] **Step 3: structured_parser.py 구현**

`backend/services/slack/structured_parser.py`:

```python
"""Claude Sonnet API로 Slack 경비 메시지를 구조화된 JSON으로 변환."""

import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

# ── API 키 ────────────────────────────────────────────────

def _get_api_key() -> str:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("ANTHROPIC_API_KEY not found in .env")


# ── 프롬프트 ──────────────────────────────────────────────

SYSTEM_PROMPT = """한아원 그룹 내부 경비 Slack 메시지를 구조화된 JSON으로 변환하세요.

규칙:
- 금액은 숫자만 (콤마/원/만원 → 정수로 변환)
- VAT 별도(vat-)면 vat_amount에 10% 계산, supply_amount에 원금
- VAT 포함(vat+)면 supply_amount = 총액/1.1 (소수점 버림), vat_amount = 총액 - supply_amount
- 3.3% 원천징수 언급 시 withholding rate=3.3, amount=총액×0.033, net_amount=총액-amount
- 선금/잔금은 payment_terms.type으로 구분 (full/advance/balance/installment)
- 항목이 여러 개면 items 배열로 분리 (bullet 형식 아니어도, 문장 안의 나열도 분리)
- 확신 없는 필드는 null
- 쓰레드 댓글이 있으면 최종 상태(금액 변경, 입금 완료 등) 반영
- category는 다음 중 하나: 식비, 교통, 구독, 마케팅, 촬영, 배송, 인건비, 기타

반드시 아래 JSON 스키마만 반환하세요. 다른 텍스트 없이 JSON만 출력하세요.

{
  "summary": "1줄 요약 (한국어)",
  "vendor": "거래처/업체명 또는 null",
  "project": "프로젝트명 또는 null",
  "category": "식비|교통|구독|마케팅|촬영|배송|인건비|기타",
  "items": [{"description": "항목 설명", "amount": 숫자, "currency": "KRW|USD|EUR"}],
  "total_amount": 숫자,
  "currency": "KRW|USD|EUR",
  "vat": {"type": "none|included|excluded", "vat_amount": null, "supply_amount": null},
  "withholding_tax": {"applies": false, "rate": null, "amount": null, "net_amount": null},
  "payment_terms": {"type": "full|advance|balance|installment", "ratio": null, "related_context": null},
  "tax_invoice": false,
  "date_mentioned": "YYYY-MM-DD 또는 null",
  "urgency": "문자열 또는 null",
  "confidence": 0.0~1.0
}"""

MODEL = "claude-sonnet-4-6-20250514"
MAX_TOKENS = 1024


# ── 프롬프트 빌드 ─────────────────────────────────────────

def build_user_prompt(text: str, *, thread_replies: str | None) -> str:
    """메시지 본문 + 쓰레드 댓글로 유저 프롬프트 생성."""
    prompt = f"[메시지 본문]\n{text}"

    if thread_replies:
        try:
            replies = json.loads(thread_replies)
            if replies:
                lines = []
                for r in replies:
                    sender = r.get("user", "unknown")
                    reply_text = r.get("text", "")
                    lines.append(f"{sender}: {reply_text}")
                prompt += f"\n\n[쓰레드 댓글]\n" + "\n".join(lines)
        except (json.JSONDecodeError, TypeError):
            pass

    return prompt


# ── 메인 파싱 함수 ────────────────────────────────────────

def parse_structured(
    text: str,
    *,
    thread_replies: str | None = None,
    skip: bool = False,
) -> dict | None:
    """Slack 메시지를 Claude Sonnet으로 구조화 파싱.

    Returns:
        파싱 결과 dict, 또는 실패/스킵 시 None.
    """
    if skip or not text or not text.strip():
        return None

    try:
        client = anthropic.Anthropic(api_key=_get_api_key())
        user_prompt = build_user_prompt(text, thread_replies=thread_replies)

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text.strip()

        # JSON 블록 추출 (```json ... ``` 감싸는 경우 대비)
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    json_lines.append(line)
            raw_text = "\n".join(json_lines)

        result = json.loads(raw_text)

        logger.info(
            "structured_parse OK: summary=%s, confidence=%.2f, tokens=%d+%d",
            result.get("summary", "?")[:30],
            result.get("confidence", 0),
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return result

    except json.JSONDecodeError as e:
        logger.warning("structured_parse JSON error: %s | raw: %s", e, raw_text[:200] if 'raw_text' in dir() else "N/A")
        return None
    except Exception as e:
        logger.warning("structured_parse API error: %s", e)
        return None
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_structured_parser.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/slack/structured_parser.py backend/tests/test_structured_parser.py
git commit -m "feat: structured_parser.py — Claude Sonnet 구조화 파싱 모듈 + 테스트"
```

---

### Task 4: sync 플로우에 구조화 파싱 통합

**Files:**
- Modify: `backend/routers/slack.py:337-496`

- [ ] **Step 1: slack.py 상단에 import 추가**

`backend/routers/slack.py` 상단 import 영역(line 13 근처)에 추가:

```python
from backend.services.slack.structured_parser import parse_structured
```

- [ ] **Step 2: sync 함수에서 기존 DB 레코드 조회 추가**

sync 함수의 `for msg in messages:` 루프 안, `parsed = parse_message(...)` 호출 전(line 387 근처)에, 기존 레코드를 조회하는 코드 추가. 루프 시작 전(line 365 이후)에 기존 메시지 캐시를 빌드:

```python
        # 기존 메시지 캐시 (구조화 파싱 스킵 판단용)
        cur.execute(
            "SELECT ts, text, reply_count, parsed_structured IS NOT NULL AS has_structured FROM slack_messages WHERE entity_id = %s",
            [entity_id],
        )
        existing_cache = {row[0]: {"text": row[1], "reply_count": row[2], "has_structured": row[3]} for row in cur.fetchall()}
```

- [ ] **Step 3: Claude 구조화 파싱 호출 추가**

`resolve_slack_status()` 호출(line 440) 이후, `cur.execute(INSERT ...)` 이전에 추가:

```python
            # ── Claude 구조화 파싱 ──
            parsed_structured = None
            existing = existing_cache.get(ts)
            should_call_claude = (
                existing is None                                    # 신규
                or not existing["has_structured"]                   # 미파싱
                or existing["text"] != text                         # 텍스트 변경
                or existing["reply_count"] < reply_count            # 새 댓글
            )

            if should_call_claude and not parsed.get("skip") and parsed["message_type"] != "other":
                parsed_structured = parse_structured(
                    text,
                    thread_replies=thread_replies_json,
                    skip=False,
                )
```

- [ ] **Step 4: INSERT 쿼리에 parsed_structured 추가**

`cur.execute(INSERT INTO slack_messages ...)` 쿼리(line 442-481)를 수정:

컬럼 리스트에 `parsed_structured` 추가:
```sql
... sender_name, sub_amounts, parsed_structured, is_cancelled, deposit_completed_date)
```

VALUES에 `%s` 하나 추가 (sub_amounts 뒤):
```sql
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
```

ON CONFLICT DO UPDATE SET에 추가:
```sql
                    sub_amounts = EXCLUDED.sub_amounts,
                    parsed_structured = CASE
                        WHEN EXCLUDED.parsed_structured IS NOT NULL THEN EXCLUDED.parsed_structured
                        ELSE slack_messages.parsed_structured
                    END,
                    is_cancelled = EXCLUDED.is_cancelled,
```

파라미터 리스트에 추가 (sub_amounts 값 뒤):
```python
                    json.dumps(parsed_structured, ensure_ascii=False) if parsed_structured else None,
```

참고: ON CONFLICT에서 `CASE WHEN`을 사용하는 이유 — Claude 호출을 스킵한 경우(should_call_claude=False) parsed_structured가 None이 되는데, 이때 기존 값을 덮어쓰지 않기 위함.

- [ ] **Step 5: sync stats에 구조화 파싱 카운트 추가**

stats dict 초기화 부분(line 364)에 추가:

```python
        stats = {"total_fetched": len(messages), "new": 0, "updated": 0, "skipped": 0, "structured": 0}
```

Claude 파싱 성공 시 카운트:

```python
            if parsed_structured is not None:
                stats["structured"] += 1
```

- [ ] **Step 6: 수동 테스트 — sync 실행**

```bash
source .venv/bin/activate && python3 -c "
import requests
resp = requests.post('http://localhost:8000/api/slack/sync', params={'entity_id': 1, 'channel': '99-expenses', 'months': '3'})
print(resp.json())
"
```

Expected: stats에 `structured` 카운트 > 0

- [ ] **Step 7: DB에 parsed_structured 저장 확인**

```bash
source .venv/bin/activate && python3 -c "
from backend.database.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute(\"SELECT ts, parsed_structured->>'summary' AS summary, parsed_structured->>'confidence' AS conf FROM slack_messages WHERE parsed_structured IS NOT NULL LIMIT 5\")
for row in cur.fetchall():
    print(f'ts={row[0]}, summary={row[1]}, confidence={row[2]}')
cur.close()
conn.close()
"
```

Expected: 파싱된 메시지 결과 출력

- [ ] **Step 8: Commit**

```bash
git add backend/routers/slack.py
git commit -m "feat: sync 플로우에 Claude 구조화 파싱 통합"
```

---

### Task 5: GET /messages API에 parsed_structured 반환

**Files:**
- Modify: `backend/routers/slack.py:34-150` (GET /messages 엔드포인트)

- [ ] **Step 1: GET /messages 쿼리에 parsed_structured 추가**

GET /messages 엔드포인트의 SELECT 쿼리에 `parsed_structured` 컬럼 추가. 현재 쿼리가 `SELECT ... FROM slack_messages` 형태이면, SELECT 리스트에 `sm.parsed_structured` (또는 `parsed_structured`) 추가.

응답 dict 빌드 시 `parsed_structured` 필드 추가:

```python
            "parsed_structured": row[N],  # N = 새로 추가된 컬럼 인덱스
```

`parsed_structured`가 text 타입으로 반환될 수 있으니 JSON 파싱:

```python
            "parsed_structured": json.loads(row[N]) if row[N] else None,
```

- [ ] **Step 2: 수동 테스트**

```bash
source .venv/bin/activate && python3 -c "
import requests, json
resp = requests.get('http://localhost:8000/api/slack/messages', params={'entity_id': 1, 'month': '2026-03'})
data = resp.json()
for item in data['items'][:3]:
    ps = item.get('parsed_structured')
    print(f\"id={item['id']}, has_structured={ps is not None}, summary={ps.get('summary') if ps else 'N/A'}\")
"
```

Expected: parsed_structured 필드가 포함된 응답

- [ ] **Step 3: Commit**

```bash
git add backend/routers/slack.py
git commit -m "feat: GET /messages API에 parsed_structured 필드 반환"
```

---

### Task 6: 프론트엔드 — SlackMessage 타입 + 구조화 테이블 컴포넌트

**Files:**
- Modify: `frontend/src/app/slack-match/page.tsx:42-59` (타입)
- Modify: `frontend/src/app/slack-match/page.tsx:249-424` (CompactMessageRow)

- [ ] **Step 1: SlackMessage 인터페이스에 parsed_structured 추가**

`frontend/src/app/slack-match/page.tsx`의 SlackMessage 인터페이스(line 42-59)에 추가:

```typescript
interface ParsedStructured {
  summary: string | null
  vendor: string | null
  project: string | null
  category: string | null
  items: Array<{ description: string; amount: number; currency: string }> | null
  total_amount: number | null
  currency: string | null
  vat: { type: string; vat_amount: number | null; supply_amount: number | null } | null
  withholding_tax: { applies: boolean; rate: number | null; amount: number | null; net_amount: number | null } | null
  payment_terms: { type: string; ratio: string | null; related_context: string | null } | null
  tax_invoice: boolean
  date_mentioned: string | null
  urgency: string | null
  confidence: number | null
}

interface SlackMessage {
  // ... 기존 필드 ...
  parsed_structured: ParsedStructured | null  // 추가
}
```

- [ ] **Step 2: 구조화 테이블 컴포넌트 추가**

CompactMessageRow 컴포넌트 바로 위에 StructuredDetail 컴포넌트 추가:

```tsx
function StructuredDetail({ data }: { data: ParsedStructured }) {
  const [showRaw, setShowRaw] = useState(false)

  const vatLabel =
    data.vat?.type === "included" ? "포함" :
    data.vat?.type === "excluded" ? "별도" : "해당없음"

  const paymentLabel =
    data.payment_terms?.type === "full" ? "일시불" :
    data.payment_terms?.type === "advance" ? "선금" :
    data.payment_terms?.type === "balance" ? "잔금" :
    data.payment_terms?.type === "installment" ? "분할" : "일시불"

  return (
    <div className="space-y-3">
      {/* 메타 정보 */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {data.project && (
          <>
            <span className="text-muted-foreground">프로젝트</span>
            <span className="font-medium">{data.project}</span>
          </>
        )}
        {data.vendor && (
          <>
            <span className="text-muted-foreground">거래처</span>
            <span className="font-medium">{data.vendor}</span>
          </>
        )}
        {data.category && (
          <>
            <span className="text-muted-foreground">카테고리</span>
            <span className="font-medium">{data.category}</span>
          </>
        )}
      </div>

      {/* 항목 테이블 */}
      {data.items && data.items.length > 0 && (
        <div className="rounded-md border border-white/[0.06] overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/[0.06] bg-secondary/30">
                <th className="text-left px-2 py-1.5 font-medium text-muted-foreground">항목</th>
                <th className="text-right px-2 py-1.5 font-medium text-muted-foreground">금액</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item, i) => (
                <tr key={i} className="border-b border-white/[0.04] last:border-0">
                  <td className="px-2 py-1.5">{item.description}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                    {item.currency === "USD"
                      ? `$${item.amount.toLocaleString()}`
                      : formatKRW(item.amount)}
                  </td>
                </tr>
              ))}
              {data.items.length > 1 && data.total_amount && (
                <tr className="bg-secondary/20 font-medium">
                  <td className="px-2 py-1.5">합계</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                    {data.currency === "USD"
                      ? `$${data.total_amount.toLocaleString()}`
                      : formatKRW(data.total_amount)}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* 세금/결제 정보 */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <span className="text-muted-foreground">VAT</span>
        <span>
          {vatLabel}
          {data.vat?.vat_amount != null && ` (${formatKRW(data.vat.vat_amount)})`}
        </span>

        {data.withholding_tax?.applies && (
          <>
            <span className="text-muted-foreground">원천징수</span>
            <span>
              {data.withholding_tax.rate}%
              {data.withholding_tax.amount != null && ` (${formatKRW(data.withholding_tax.amount)})`}
              {data.withholding_tax.net_amount != null && ` → 실수령 ${formatKRW(data.withholding_tax.net_amount)}`}
            </span>
          </>
        )}

        <span className="text-muted-foreground">결제조건</span>
        <span>
          {paymentLabel}
          {data.payment_terms?.ratio && ` (${data.payment_terms.ratio})`}
        </span>

        {data.tax_invoice && (
          <>
            <span className="text-muted-foreground">세금계산서</span>
            <span>발행 예정</span>
          </>
        )}

        {data.urgency && (
          <>
            <span className="text-muted-foreground">긴급도</span>
            <span className="text-[hsl(var(--loss))]">{data.urgency}</span>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: CompactMessageRow의 접힌 상태 — 날짜를 이름 앞으로**

CompactMessageRow(line 286-327)의 compact summary line 안에서 Sender와 Date 순서를 바꾼다:

기존 (line 296-304):
```tsx
        {/* Sender */}
        <span className="text-xs text-muted-foreground truncate max-w-[80px]">
          {message.sender_name}
        </span>

        {/* Date */}
        <span className="text-xs text-muted-foreground">
          {formatDate(message.message_date)}
        </span>
```

변경:
```tsx
        {/* Date — 날짜순 정렬이므로 이름 앞에 배치 */}
        <span className="text-xs text-muted-foreground">
          {formatDate(message.message_date)}
        </span>

        {/* Sender */}
        <span className="text-xs text-muted-foreground truncate max-w-[80px]">
          {message.sender_name}
        </span>
```

- [ ] **Step 4: CompactMessageRow의 펼침 영역에 구조화 테이블 삽입**

CompactMessageRow의 expanded detail 영역(line 337-421)에서, `{/* Full message text */}` 부분(line 354-355)을 변경:

기존:
```tsx
          {/* Full message text */}
          <p className="text-sm leading-relaxed">{message.message_text}</p>
```

변경:
```tsx
          {/* 구조화 정보 또는 원문 */}
          {message.parsed_structured ? (
            <div className="space-y-2">
              <StructuredDetail data={message.parsed_structured} />
              {/* 원문 토글 */}
              <button
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                onClick={(e) => {
                  e.stopPropagation()
                  const el = e.currentTarget.nextElementSibling
                  if (el) el.classList.toggle("hidden")
                }}
              >
                <ChevronDown className="h-3 w-3" />
                원문 보기
              </button>
              <p className="hidden text-xs leading-relaxed text-muted-foreground whitespace-pre-wrap bg-secondary/20 rounded p-2">
                {message.message_text}
              </p>
            </div>
          ) : (
            <p className="text-sm leading-relaxed">{message.message_text}</p>
          )}
```

- [ ] **Step 5: 브라우저에서 확인**

1. `cd frontend && npm run dev`
2. http://localhost:3000/slack-match 접속
3. sync 실행
4. 카드 펼쳐서 구조화 테이블 표시 확인
5. "원문 보기" 토글 동작 확인

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx
git commit -m "feat: Slack 카드 펼침 시 구조화 파싱 테이블 표시"
```

---

### Task 7: 전체 테스트 + 정리

**Files:**
- Test: `backend/tests/test_structured_parser.py`
- Test: 기존 테스트 전체

- [ ] **Step 1: structured_parser 테스트 실행**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_structured_parser.py -v
```

Expected: All passed

- [ ] **Step 2: 기존 테스트 전체 실행 (regression 확인)**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/ -v
```

Expected: 기존 테스트 + 새 테스트 모두 통과

- [ ] **Step 3: CHANGELOG.md 업데이트**

CHANGELOG.md 최상단에 추가:

```markdown
## [Unreleased]

### Added
- Slack 구조화 파싱 엔진 — Claude Sonnet API로 경비 메시지 자동 구조화
  - vendor, category, 항목별 금액, VAT, 원천징수, 선금/잔금 추출
  - sync 시 자동 호출 (신규/변경 메시지만)
  - `parsed_structured` JSONB 컬럼으로 저장
- Slack 카드 펼침 시 구조화 테이블 표시 + 원문 토글
- 카드 접힌 상태에서 날짜를 이름 앞에 배치
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG — Slack 구조화 파싱 엔진 추가"
```

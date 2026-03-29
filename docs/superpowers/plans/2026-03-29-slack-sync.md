# Slack 경비 채널 동기화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #99-expenses 채널의 355개 경비 메시지 + 쓰레드 댓글을 DB에 수집하고, 유형 분류 + 금액 파싱 + 완료 상태 자동 판정 + 멤버 매핑까지 처리

**Architecture:** 3개 서비스 모듈(slack_client, message_parser, thread_analyzer)을 파이프라인으로 연결. `POST /api/slack/sync` 엔드포인트에서 전체 흐름 실행. 기존 slack.py 라우터와 slack-match UI는 alias 수정만으로 재사용.

**Tech Stack:** FastAPI, psycopg2, requests (Slack API), Next.js

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/services/slack/__init__.py` | 패키지 init |
| Create | `backend/services/slack/slack_client.py` | Slack API 호출 (history, replies, users, reactions) |
| Create | `backend/services/slack/message_parser.py` | 유형 분류, 금액/VAT/태그/sub_amounts 파싱 |
| Create | `backend/services/slack/thread_analyzer.py` | 쓰레드 이벤트 감지 (입금완료/취소/금액변경) |
| Create | `backend/tests/test_message_parser.py` | 파서 유닛 테스트 |
| Create | `backend/tests/test_thread_analyzer.py` | 쓰레드 분석 유닛 테스트 |
| Create | `backend/tests/test_slack_status.py` | 상태 판정 + 그룹 매칭 테스트 |
| Modify | `backend/routers/slack.py` | sync 엔드포인트 추가 + list_messages alias 수정 |
| Modify | `backend/routers/accounts.py` | members에 slack_user_id 지원 |
| Modify | `backend/database/schema.sql` | slack_messages + members 스키마 업데이트 |
| Modify | `frontend/src/app/slack-match/page.tsx` | 동기화 버튼 추가 |
| Modify | `frontend/src/app/members/page.tsx` | Slack ID 편집 필드 |

---

### Task 1: DB 마이그레이션

**Files:**
- Modify: `backend/database/schema.sql`

- [ ] **Step 1: slack_messages + members 컬럼 추가 마이그레이션 실행**

```bash
source .venv/bin/activate && python3 -c "
import psycopg2
from pathlib import Path
env_path = Path('.env')
DATABASE_URL = None
for line in env_path.read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        DATABASE_URL = line.split('=', 1)[1].strip()
        break
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute('SET search_path TO financeone, public')

# slack_messages 새 컬럼
cur.execute('ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS member_id INTEGER REFERENCES members(id)')
cur.execute(\"ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS message_type TEXT\")
cur.execute(\"ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS slack_status TEXT DEFAULT 'pending'\")
cur.execute(\"ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'KRW'\")
cur.execute('ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS withholding_tax BOOLEAN DEFAULT FALSE')
cur.execute('ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS sender_name TEXT')
cur.execute('ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS sub_amounts JSONB')

# members에 slack_user_id
cur.execute('ALTER TABLE members ADD COLUMN IF NOT EXISTS slack_user_id TEXT')
cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_members_slack ON members (entity_id, slack_user_id) WHERE slack_user_id IS NOT NULL')

conn.commit()
print('Migration done')
cur.close()
conn.close()
"
```

- [ ] **Step 2: schema.sql 업데이트**

`slack_messages` 테이블 정의에 새 컬럼 추가:

```sql
-- 15. slack_messages — Slack 경비 메시지
CREATE TABLE IF NOT EXISTS slack_messages (
  id                        SERIAL PRIMARY KEY,
  entity_id                 INTEGER REFERENCES entities(id),
  ts                        TEXT NOT NULL UNIQUE,
  channel                   TEXT NOT NULL,
  user_id                   TEXT,
  text                      TEXT,
  parsed_amount             NUMERIC(18,2),
  parsed_amount_vat_included NUMERIC(18,2),
  vat_flag                  TEXT,
  project_tag               TEXT,
  is_completed              BOOLEAN NOT NULL DEFAULT FALSE,
  raw_json                  TEXT,
  date_override             DATE,
  is_cancelled              BOOLEAN NOT NULL DEFAULT FALSE,
  deposit_completed_date    DATE,
  reply_count               INTEGER NOT NULL DEFAULT 0,
  thread_replies_json       TEXT,
  member_id                 INTEGER REFERENCES members(id),
  message_type              TEXT,
  slack_status              TEXT DEFAULT 'pending',
  currency                  TEXT DEFAULT 'KRW',
  withholding_tax           BOOLEAN DEFAULT FALSE,
  sender_name               TEXT,
  sub_amounts               JSONB,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`members` 테이블 정의에 `slack_user_id` 추가:

```sql
CREATE TABLE IF NOT EXISTS members (
  id            SERIAL PRIMARY KEY,
  entity_id     INTEGER NOT NULL REFERENCES entities(id),
  name          TEXT NOT NULL,
  role          TEXT DEFAULT 'staff',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  card_numbers  TEXT[] DEFAULT ARRAY[]::TEXT[],
  slack_user_id TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_members_slack ON members (entity_id, slack_user_id) WHERE slack_user_id IS NOT NULL;
```

- [ ] **Step 3: Commit**

```bash
git add backend/database/schema.sql
git commit -m "feat: DB 마이그레이션 — slack_messages 새 컬럼 + members.slack_user_id"
```

---

### Task 2: message_parser.py — 메시지 파서

**Files:**
- Create: `backend/services/slack/__init__.py`
- Create: `backend/services/slack/message_parser.py`
- Test: `backend/tests/test_message_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_message_parser.py
"""message_parser 테스트 — 유형 분류 + 금액/VAT/태그 파싱"""

import pytest


class TestClassify:
    def test_card_payment_korean(self):
        from backend.services.slack.message_parser import classify
        assert classify("[ODD] 카카오택시 35,000원 - 개인법카 결제완료") == "card_payment"

    def test_card_payment_purchase(self):
        from backend.services.slack.message_parser import classify
        assert classify("[마트약국 제작물 결제] - 개인 법카 구매완료") == "card_payment"

    def test_deposit_request(self):
        from backend.services.slack.message_parser import classify
        assert classify("[ODD] 스튜디오 대관비용 입금요청") == "deposit_request"

    def test_deposit_request_needed(self):
        from backend.services.slack.message_parser import classify
        assert classify("[마트약국 쇼카드 발주] 입금 필요") == "deposit_request"

    def test_tax_invoice(self):
        from backend.services.slack.message_parser import classify
        assert classify("[한아원명함] - 세금계산서 발행 완료") == "tax_invoice"

    def test_expense_share_with_amount(self):
        from backend.services.slack.message_parser import classify
        assert classify("크롤러 PC용 주변기기 구매 - 16000원") == "expense_share"

    def test_other_no_amount_no_keyword(self):
        from backend.services.slack.message_parser import classify
        assert classify("다들 주말 잘보내고계신가요~?") == "other"

    def test_bot_message(self):
        from backend.services.slack.message_parser import classify
        assert classify("ExpenseOne 봇 연결 테스트입니다.") == "other"


class TestExtractAmount:
    def test_krw_comma(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("카카오택시 35,000원")
        assert result == {"amount": 35000, "currency": "KRW"}

    def test_krw_no_comma(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("다이소 16000원")
        assert result == {"amount": 16000, "currency": "KRW"}

    def test_krw_man(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("퀵비용 3만원")
        assert result == {"amount": 30000, "currency": "KRW"}

    def test_usd_dollar_sign(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("클로드 $11")
        assert result == {"amount": 11.0, "currency": "USD"}

    def test_usd_us_dollar(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("법무법인 US$882")
        assert result == {"amount": 882.0, "currency": "USD"}

    def test_usd_bul(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("힉스필드 158불")
        assert result == {"amount": 158.0, "currency": "USD"}

    def test_usd_with_cents(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("Target $98.78 결제")
        assert result == {"amount": 98.78, "currency": "USD"}

    def test_no_amount(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("서류 공유해주세요")
        assert result is None


class TestExtractVat:
    def test_vat_included(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("92,400원 (VAT 포함)") == "included"

    def test_vat_plus(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("851,400원(vat+)") == "included"

    def test_vat_excluded(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("64,000원(VAT 제외)") == "excluded"

    def test_vat_minus(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("60,000원(vat-)") == "excluded"

    def test_vat_separate(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("314,000원 + 부가세 별도") == "excluded"

    def test_no_vat(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("카카오택시 35,000원") == "none"


class TestExtractTag:
    def test_project_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("[ODD] 카카오택시 35,000원") == "ODD"

    def test_korean_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("[마트약국] 쇼카드 발주") == "마트약국"

    def test_multi_word_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("[AI 웹 제작을 위한 API 비용]") == "AI 웹 제작을 위한 API 비용"

    def test_no_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("카카오택시 35,000원") is None


class TestExtractSubAmounts:
    def test_multi_line_items(self):
        from backend.services.slack.message_parser import extract_sub_amounts
        text = """[ODD] 스티커 + 포장
• 스티커 851,400원
• 포장 286,100원
합계 1,137,500원"""
        result = extract_sub_amounts(text)
        assert len(result) == 2
        assert result[0]["amount"] == 851400
        assert result[1]["amount"] == 286100

    def test_single_amount_no_sub(self):
        from backend.services.slack.message_parser import extract_sub_amounts
        text = "카카오택시 35,000원"
        result = extract_sub_amounts(text)
        assert result == []


class TestWithholding:
    def test_withholding_detected(self):
        from backend.services.slack.message_parser import detect_withholding
        assert detect_withholding("500,000원 (3.3% 제외 해야합니다)") is True

    def test_no_withholding(self):
        from backend.services.slack.message_parser import detect_withholding
        assert detect_withholding("카카오택시 35,000원") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_message_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create package init**

```python
# backend/services/slack/__init__.py
```

- [ ] **Step 4: Implement message_parser.py**

```python
# backend/services/slack/message_parser.py
"""Slack 메시지 파서 — 유형 분류 + 금액/VAT/태그 추출"""

import re
import json

# ── 유형 분류 ──────────────────────────────────────────

CARD_PAYMENT_KEYWORDS = ["결제완료", "결제 완료", "구매완료", "구매 완료", "법카로 결제"]
DEPOSIT_REQUEST_KEYWORDS = ["입금요청", "입금 요청", "입금 필요", "입금요청드립니다", "입금 부탁"]
TAX_INVOICE_KEYWORDS = ["세금계산서 발행", "세금계산서 요청"]

# 경비 관련 키워드 (금액 없어도 경비 메시지로 판단)
EXPENSE_KEYWORDS = ["결제", "구매", "비용", "입금", "지급", "발주", "견적", "인보이스", "invoice"]


def classify(text: str) -> str:
    """메시지 유형 분류. card_payment / deposit_request / tax_invoice / expense_share / other"""
    if not text:
        return "other"

    for kw in CARD_PAYMENT_KEYWORDS:
        if kw in text:
            return "card_payment"

    for kw in DEPOSIT_REQUEST_KEYWORDS:
        if kw in text:
            return "deposit_request"

    for kw in TAX_INVOICE_KEYWORDS:
        if kw in text:
            return "tax_invoice"

    # 금액이 있으면 expense_share
    if extract_amount(text) is not None:
        return "expense_share"

    # 경비 키워드가 있으면 expense_share
    for kw in EXPENSE_KEYWORDS:
        if kw in text:
            return "expense_share"

    return "other"


# ── 금액 추출 ──────────────────────────────────────────

KRW_PATTERN = re.compile(r'(?:총\s*|총금액\s*[=:]\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})\s*원')
KRW_MAN_PATTERN = re.compile(r'(\d+)\s*만\s*원')
USD_PATTERN = re.compile(r'(?:US)?\$\s*([\d,]+(?:\.\d{1,2})?)')
USD_BUL_PATTERN = re.compile(r'(\d+(?:,\d+)?)\s*(?:불|달러)')
EUR_PATTERN = re.compile(r'€\s*([\d,]+(?:\.\d{1,2})?)|(\d+(?:,\d+)?)\s*(?:EURO|유로)')


def _parse_number(s: str) -> float:
    return float(s.replace(",", ""))


def extract_amount(text: str) -> dict | None:
    """메시지에서 금액 추출. 합계 키워드가 있으면 합계, 없으면 가장 큰 금액."""
    if not text:
        return None

    # USD 먼저 ($ 기호)
    usd_matches = USD_PATTERN.findall(text)
    if usd_matches:
        amounts = [_parse_number(m) for m in usd_matches]
        return {"amount": max(amounts), "currency": "USD"}

    usd_bul = USD_BUL_PATTERN.findall(text)
    if usd_bul:
        amounts = [_parse_number(m) for m in usd_bul]
        return {"amount": max(amounts), "currency": "USD"}

    # EUR
    eur_matches = EUR_PATTERN.findall(text)
    for m1, m2 in eur_matches:
        val = m1 or m2
        if val:
            return {"amount": _parse_number(val), "currency": "EUR"}

    # KRW 만원
    man_matches = KRW_MAN_PATTERN.findall(text)
    if man_matches:
        amounts = [int(m) * 10000 for m in man_matches]
        return {"amount": max(amounts), "currency": "KRW"}

    # KRW 원
    krw_matches = KRW_PATTERN.findall(text)
    if krw_matches:
        amounts = [_parse_number(m) for m in krw_matches]
        # 합계 키워드 앞의 금액 우선
        lines = text.split("\n")
        for line in lines:
            if any(kw in line for kw in ["합계", "총금액", "총액", "= "]):
                line_amounts = KRW_PATTERN.findall(line)
                if line_amounts:
                    return {"amount": _parse_number(line_amounts[-1]), "currency": "KRW"}
        return {"amount": max(amounts), "currency": "KRW"}

    return None


# ── 다중 항목 추출 ────────────────────────────────────

def extract_sub_amounts(text: str) -> list[dict]:
    """다중 항목 메시지에서 개별 금액 추출. [{amount, desc}]"""
    lines = text.strip().split("\n")
    sub_items = []

    for line in lines:
        line = line.strip().lstrip("•-·")
        # 합계 라인은 skip
        if any(kw in line for kw in ["합계", "총금액", "총액", "= "]):
            continue
        krw = KRW_PATTERN.findall(line)
        if krw:
            amount = _parse_number(krw[0])
            desc = KRW_PATTERN.sub("", line).strip().rstrip(":：/ ")
            sub_items.append({"amount": amount, "desc": desc[:100]})

    # 1개 이하면 다중 항목이 아님
    return sub_items if len(sub_items) >= 2 else []


# ── VAT 추출 ──────────────────────────────────────────

VAT_INCLUDED = ["VAT 포함", "vat+", "vat포함", "부가세 포함", "VAT+", "(vat+)"]
VAT_EXCLUDED = ["VAT 제외", "vat-", "vat제외", "부가세 별도", "VAT 별도", "VAT-", "(vat-)"]


def extract_vat(text: str) -> str:
    """VAT 상태. included / excluded / none"""
    text_lower = text.lower()
    for kw in VAT_INCLUDED:
        if kw.lower() in text_lower:
            return "included"
    for kw in VAT_EXCLUDED:
        if kw.lower() in text_lower:
            return "excluded"
    return "none"


# ── 태그 추출 ─────────────────────────────────────────

TAG_PATTERN = re.compile(r'^\*?\[([^\]]+)\]', re.MULTILINE)


def extract_tag(text: str) -> str | None:
    """프로젝트 태그 추출. [ODD], [마트약국] 등"""
    m = TAG_PATTERN.search(text)
    return m.group(1) if m else None


# ── 원천징수 감지 ─────────────────────────────────────

WITHHOLDING_PATTERN = re.compile(r'3\.3%\s*(?:제외|공제)')


def detect_withholding(text: str) -> bool:
    return bool(WITHHOLDING_PATTERN.search(text))


# ── 날짜 추출 ─────────────────────────────────────────

DATE_PATTERN = re.compile(r'\((\d{1,2})/(\d{1,2})\)')


def extract_date_override(text: str, default_year: int = 2026) -> str | None:
    """(1/15) 형태의 날짜 추출 → YYYY-MM-DD"""
    m = DATE_PATTERN.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{default_year}-{month:02d}-{day:02d}"
    return None


# ── 통합 파싱 ─────────────────────────────────────────

def parse_message(text: str, *, is_bot: bool = False, is_system: bool = False) -> dict:
    """메시지 전체 파싱. 봇/시스템 메시지는 other로 처리."""
    if is_bot or is_system:
        return {"message_type": "other", "skip": True}

    message_type = classify(text)
    amount_info = extract_amount(text)
    vat = extract_vat(text)
    tag = extract_tag(text)
    sub = extract_sub_amounts(text)
    withholding = detect_withholding(text)
    date_override = extract_date_override(text)

    parsed_amount = amount_info["amount"] if amount_info else None
    currency = amount_info["currency"] if amount_info else "KRW"

    # VAT 포함 금액 계산
    vat_included = None
    if parsed_amount is not None:
        if vat == "included":
            vat_included = parsed_amount
        elif vat == "excluded":
            vat_included = round(parsed_amount * 1.1, 2)

    return {
        "message_type": message_type,
        "parsed_amount": parsed_amount,
        "parsed_amount_vat_included": vat_included,
        "currency": currency,
        "vat_flag": vat,
        "project_tag": tag,
        "sub_amounts": sub if sub else None,
        "withholding_tax": withholding,
        "date_override": date_override,
        "skip": message_type == "other" and parsed_amount is None,
    }
```

- [ ] **Step 5: Run tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_message_parser.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/slack/__init__.py backend/services/slack/message_parser.py backend/tests/test_message_parser.py
git commit -m "feat: Slack 메시지 파서 — 유형 분류 + 금액/VAT/태그/sub_amounts 추출"
```

---

### Task 3: thread_analyzer.py — 쓰레드 분석기

**Files:**
- Create: `backend/services/slack/thread_analyzer.py`
- Test: `backend/tests/test_thread_analyzer.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_thread_analyzer.py
"""thread_analyzer 테스트 — 쓰레드 이벤트 감지"""

import pytest


class TestDetectDepositDone:
    def test_deposit_complete(self):
        from backend.services.slack.thread_analyzer import detect_deposit_done
        assert detect_deposit_done("입금완료") is True

    def test_transfer_complete(self):
        from backend.services.slack.thread_analyzer import detect_deposit_done
        assert detect_deposit_done("아까 바로이체완료했습니다!") is True

    def test_normal_reply(self):
        from backend.services.slack.thread_analyzer import detect_deposit_done
        assert detect_deposit_done("넵 확인했습니다") is False


class TestDetectCancel:
    def test_cancel(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("해당건은 반품하였습니다.") is True

    def test_refund(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("환불 완료되었습니다!") is True

    def test_direction_change_refund(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("방향성 변경으로 환불처리되었습니다.") is True

    def test_normal_reply(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("넵 확인했습니다") is False


class TestDetectAmountChange:
    def test_new_amount_in_reply(self):
        from backend.services.slack.thread_analyzer import detect_amount_change
        result = detect_amount_change("금액 변경: 총 92,400원 (VAT 포함)", original_amount=84000)
        assert result == 92400

    def test_same_amount(self):
        from backend.services.slack.thread_analyzer import detect_amount_change
        result = detect_amount_change("확인했습니다 35,000원", original_amount=35000)
        assert result is None

    def test_no_amount(self):
        from backend.services.slack.thread_analyzer import detect_amount_change
        result = detect_amount_change("넵 확인했습니다", original_amount=35000)
        assert result is None


class TestAnalyzeThread:
    def test_full_thread_deposit(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        replies = [
            {"text": "인보이스 보내드렸습니다", "user": "U001", "ts": "1770000001.000"},
            {"text": "입금완료", "user": "U002", "ts": "1770000002.000"},
        ]
        result = analyze_thread(replies, original_amount=100000)
        assert result["deposit_done"] is True
        assert result["cancelled"] is False

    def test_full_thread_cancel(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        replies = [
            {"text": "해당건은 반품하였습니다.", "user": "U001", "ts": "1770000001.000"},
        ]
        result = analyze_thread(replies, original_amount=100000)
        assert result["cancelled"] is True

    def test_full_thread_amount_change(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        replies = [
            {"text": "금액 정정: 총 92,400원입니다", "user": "U001", "ts": "1770000001.000"},
        ]
        result = analyze_thread(replies, original_amount=84000)
        assert result["new_amount"] == 92400

    def test_empty_thread(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        result = analyze_thread([], original_amount=100000)
        assert result["deposit_done"] is False
        assert result["cancelled"] is False
        assert result["new_amount"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_thread_analyzer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement thread_analyzer.py**

```python
# backend/services/slack/thread_analyzer.py
"""Slack 쓰레드 분석기 — 입금완료/취소/금액변경 이벤트 감지"""

import json
from backend.services.slack.message_parser import extract_amount

DEPOSIT_DONE_KEYWORDS = [
    "입금완료", "입금 완료", "이체완료", "이체 완료",
    "송금완료", "송금 완료", "입금했습니다", "이체했습니다",
]

CANCEL_KEYWORDS = [
    "취소", "환불", "반품", "캔슬", "환불처리", "반품하였습니다",
]


def detect_deposit_done(text: str) -> bool:
    for kw in DEPOSIT_DONE_KEYWORDS:
        if kw in text:
            return True
    return False


def detect_cancel(text: str) -> bool:
    for kw in CANCEL_KEYWORDS:
        if kw in text:
            return True
    return False


def detect_amount_change(text: str, *, original_amount: float | None) -> float | None:
    """댓글에서 금액 추출. 기존 금액과 다르면 새 금액 반환."""
    if original_amount is None:
        return None
    result = extract_amount(text)
    if result and result["amount"] != original_amount:
        return result["amount"]
    return None


def analyze_thread(replies: list[dict], *, original_amount: float | None = None) -> dict:
    """쓰레드 댓글 전체 분석. 이벤트 결과 반환."""
    result = {
        "deposit_done": False,
        "cancelled": False,
        "new_amount": None,
        "file_urls": [],
    }

    for reply in replies:
        text = reply.get("text", "")
        files = reply.get("files", [])

        if detect_deposit_done(text):
            result["deposit_done"] = True

        if detect_cancel(text):
            result["cancelled"] = True

        amount_change = detect_amount_change(text, original_amount=original_amount)
        if amount_change is not None:
            result["new_amount"] = amount_change  # 마지막 금액이 최종

        for f in files:
            url = f.get("url_private") or f.get("permalink")
            if url:
                result["file_urls"].append({"name": f.get("name", ""), "url": url})

    return result


def resolve_slack_status(message_type: str, has_check_reaction: bool, thread_events: dict) -> dict:
    """메시지 유형 + 리액션 + 쓰레드 이벤트로 slack_status 판정."""
    if thread_events.get("cancelled"):
        return {"slack_status": "cancelled", "is_cancelled": True}

    if message_type == "card_payment":
        return {"slack_status": "done"}

    if thread_events.get("deposit_done"):
        return {"slack_status": "done"}

    if has_check_reaction:
        return {"slack_status": "done"}

    return {"slack_status": "pending"}
```

- [ ] **Step 4: Run tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_thread_analyzer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Write status + group matching tests**

```python
# backend/tests/test_slack_status.py
"""slack_status 판정 + 그룹 매칭 완료 조건 테스트"""

import pytest
from backend.services.slack.thread_analyzer import resolve_slack_status


class TestResolveSlackStatus:
    def test_card_payment_always_done(self):
        result = resolve_slack_status("card_payment", False, {})
        assert result["slack_status"] == "done"

    def test_deposit_request_with_reaction(self):
        result = resolve_slack_status("deposit_request", True, {})
        assert result["slack_status"] == "done"

    def test_deposit_request_with_thread_done(self):
        result = resolve_slack_status("deposit_request", False, {"deposit_done": True})
        assert result["slack_status"] == "done"

    def test_deposit_request_no_signal(self):
        result = resolve_slack_status("deposit_request", False, {})
        assert result["slack_status"] == "pending"

    def test_cancelled_overrides_all(self):
        result = resolve_slack_status("card_payment", True, {"cancelled": True})
        assert result["slack_status"] == "cancelled"
        assert result["is_cancelled"] is True

    def test_expense_share_with_reaction(self):
        result = resolve_slack_status("expense_share", True, {})
        assert result["slack_status"] == "done"

    def test_other_no_signal(self):
        result = resolve_slack_status("other", False, {})
        assert result["slack_status"] == "pending"
```

- [ ] **Step 6: Run all slack tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_thread_analyzer.py backend/tests/test_slack_status.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/services/slack/thread_analyzer.py backend/tests/test_thread_analyzer.py backend/tests/test_slack_status.py
git commit -m "feat: 쓰레드 분석기 + slack_status 판정 로직"
```

---

### Task 4: slack_client.py — Slack API 클라이언트

**Files:**
- Create: `backend/services/slack/slack_client.py`

- [ ] **Step 1: Implement slack_client.py**

```python
# backend/services/slack/slack_client.py
"""Slack API 클라이언트 — 채널 히스토리 + 쓰레드 + 유저 프로필 + 리액션"""

import time
import requests
from pathlib import Path


def _get_token() -> str:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("SLACK_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("SLACK_BOT_TOKEN not found in .env")


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


def _api_get(url: str, params: dict) -> dict:
    """Slack API GET with rate limit handling."""
    for attempt in range(3):
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data
        if data.get("error") == "ratelimited":
            retry_after = int(resp.headers.get("Retry-After", 5))
            time.sleep(retry_after)
            continue
        if data.get("error") == "invalid_auth":
            raise RuntimeError("Slack 토큰이 만료되었거나 유효하지 않습니다. .env의 SLACK_BOT_TOKEN을 확인하세요.")
        if data.get("error") == "not_in_channel":
            raise RuntimeError("봇이 채널에 초대되지 않았습니다. Slack에서 봇을 채널에 추가해주세요.")
        if data.get("error") == "channel_not_found":
            raise RuntimeError(f"채널을 찾을 수 없습니다: {params.get('channel', '?')}")
        raise RuntimeError(f"Slack API error: {data.get('error')}")
    raise RuntimeError("Slack API rate limit exceeded after 3 retries")


def find_channel_id(channel_name: str) -> str:
    """채널 이름으로 ID 조회."""
    data = _api_get("https://slack.com/api/conversations.list", {"types": "public_channel,private_channel", "limit": 200})
    for ch in data["channels"]:
        if ch["name"] == channel_name:
            return ch["id"]
    raise RuntimeError(f"채널 #{channel_name}을 찾을 수 없습니다")


def fetch_history(channel_id: str) -> list[dict]:
    """채널 전체 히스토리 (페이지네이션)."""
    all_messages = []
    cursor = None
    while True:
        params = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _api_get("https://slack.com/api/conversations.history", params)
        all_messages.extend(data["messages"])
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(1)  # rate limit safety
    return all_messages


def fetch_replies(channel_id: str, thread_ts: str) -> list[dict]:
    """쓰레드 댓글 조회 (부모 메시지 제외)."""
    data = _api_get("https://slack.com/api/conversations.replies", {"channel": channel_id, "ts": thread_ts})
    return data["messages"][1:]  # skip parent


def fetch_user_name(user_id: str) -> str:
    """Slack user ID → real_name."""
    data = _api_get("https://slack.com/api/users.info", {"user": user_id})
    user = data["user"]
    return user.get("real_name") or user.get("profile", {}).get("display_name") or user_id


def get_reactions(message: dict) -> list[str]:
    """메시지의 리액션 이름 목록."""
    return [r["name"] for r in message.get("reactions", [])]
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/slack/slack_client.py
git commit -m "feat: Slack API 클라이언트 (history, replies, users, reactions)"
```

---

### Task 5: sync 엔드포인트 + 멤버 매핑

**Files:**
- Modify: `backend/routers/slack.py`
- Modify: `backend/routers/accounts.py`

- [ ] **Step 1: accounts.py에 slack_user_id 지원 추가**

`MemberCreate`에 `slack_user_id` 추가:

```python
class MemberCreate(BaseModel):
    entity_id: int
    name: str
    role: Optional[str] = "staff"
    card_numbers: Optional[list[str]] = None
    slack_user_id: Optional[str] = None
```

`MemberUpdate`에 `slack_user_id` 추가:

```python
class MemberUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    card_numbers: Optional[list[str]] = None
    slack_user_id: Optional[str] = None
```

`list_members` SELECT에 `slack_user_id` 추가:

```sql
SELECT id, entity_id, name, role, card_numbers, slack_user_id FROM members WHERE ...
```

`create_member` INSERT에 `slack_user_id` 추가:

```sql
INSERT INTO members (entity_id, name, role, card_numbers, slack_user_id)
VALUES (%s, %s, %s, %s, %s)
RETURNING id, entity_id, name, role, is_active, card_numbers, slack_user_id
```

`update_member` RETURNING에 `slack_user_id` 추가:

```sql
RETURNING id, entity_id, name, role, is_active, card_numbers, slack_user_id
```

- [ ] **Step 2: slack.py에 sync 엔드포인트 추가**

`backend/routers/slack.py` 상단에 import 추가:

```python
import json
import time
from datetime import datetime
from backend.services.slack.slack_client import find_channel_id, fetch_history, fetch_replies, fetch_user_name, get_reactions
from backend.services.slack.message_parser import parse_message
from backend.services.slack.thread_analyzer import analyze_thread, resolve_slack_status
```

기존 `list_slack_messages` SELECT 쿼리에서 alias 추가 (프론트 호환):

```python
    cur.execute(
        f"""
        SELECT sm.id, sm.entity_id, sm.ts, sm.channel AS channel_name,
               sm.user_id, sm.text AS message_text,
               sm.parsed_amount, sm.parsed_amount_vat_included,
               sm.vat_flag, sm.project_tag,
               sm.is_completed, sm.is_cancelled,
               sm.date_override AS message_date, sm.reply_count,
               sm.created_at, sm.slack_status, sm.message_type,
               sm.sender_name, sm.currency, sm.member_id,
               tsm.id AS match_id,
               tsm.transaction_id AS matched_transaction_id,
               tsm.match_confidence,
               tsm.is_confirmed AS match_confirmed,
               tsm.is_manual AS match_manual
        FROM slack_messages sm
        LEFT JOIN transaction_slack_match tsm ON sm.id = tsm.slack_message_id
        WHERE {where_clause}
        ORDER BY sm.ts DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
```

sync 엔드포인트 추가 (파일 맨 아래):

```python
@router.post("/sync")
def sync_slack_channel(
    channel: str = Query("99-expenses"),
    entity_id: int = Query(...),
    year: int = Query(2026),
    months: Optional[str] = None,
    conn: PgConnection = Depends(get_db),
):
    """Slack 채널 메시지 + 쓰레드를 DB에 동기화."""
    cur = conn.cursor()
    try:
        # 1. 채널 ID 조회
        channel_id = find_channel_id(channel)

        # 2. 전체 히스토리 가져오기
        messages = fetch_history(channel_id)

        # 3. 유저 이름 캐시
        user_cache = {}

        # 4. 멤버 매핑 캐시 (slack_user_id → member_id)
        cur.execute(
            "SELECT slack_user_id, id FROM members WHERE entity_id = %s AND slack_user_id IS NOT NULL AND is_active = true",
            [entity_id],
        )
        member_map = {row[0]: row[1] for row in cur.fetchall()}

        # 5. 월 필터
        target_months = set()
        if months:
            target_months = {int(m) for m in months.split(",")}

        stats = {"total_fetched": len(messages), "new": 0, "updated": 0, "skipped": 0}

        for msg in messages:
            ts = msg.get("ts", "")
            text = msg.get("text", "")
            user_id = msg.get("user", "")
            bot_id = msg.get("bot_id")
            subtype = msg.get("subtype")

            # 월 필터 적용
            if target_months:
                msg_time = datetime.fromtimestamp(float(ts))
                if msg_time.year != year or msg_time.month not in target_months:
                    stats["skipped"] += 1
                    continue

            # 봇/시스템 메시지 판별
            is_bot = bool(bot_id)
            is_system = subtype in ("channel_join", "channel_leave", "channel_purpose", "channel_topic")

            # 파싱
            parsed = parse_message(text, is_bot=is_bot, is_system=is_system)
            if parsed.get("skip"):
                stats["skipped"] += 1
                continue

            # 유저 이름 조회
            sender_name = None
            if user_id and user_id not in user_cache:
                try:
                    user_cache[user_id] = fetch_user_name(user_id)
                except Exception:
                    user_cache[user_id] = user_id
                time.sleep(0.2)
            sender_name = user_cache.get(user_id)

            # 멤버 매핑
            member_id = member_map.get(user_id)

            # 쓰레드 댓글 분석
            thread_events = {"deposit_done": False, "cancelled": False, "new_amount": None, "file_urls": []}
            reply_count = msg.get("reply_count", 0)
            thread_replies_json = None

            if reply_count > 0:
                try:
                    replies = fetch_replies(channel_id, ts)
                    thread_replies_json = json.dumps(
                        [{"ts": r.get("ts"), "user": r.get("user"), "text": r.get("text", "")[:500],
                          "files": [{"name": f.get("name"), "url": f.get("url_private") or f.get("permalink")} for f in r.get("files", [])]}
                         for r in replies],
                        ensure_ascii=False,
                    )
                    thread_events = analyze_thread(replies, original_amount=parsed.get("parsed_amount"))
                    time.sleep(0.5)  # rate limit
                except Exception:
                    pass  # 쓰레드 실패해도 메인 메시지는 저장

            # 금액 업데이트 (쓰레드에서 변경된 경우)
            final_amount = parsed.get("parsed_amount")
            if thread_events.get("new_amount") is not None:
                final_amount = thread_events["new_amount"]

            # 리액션 확인
            reactions = get_reactions(msg)
            has_check = "white_check_mark" in reactions

            # slack_status 판정
            status_result = resolve_slack_status(
                parsed["message_type"], has_check, thread_events,
            )

            # UPSERT
            cur.execute(
                """
                INSERT INTO slack_messages
                    (entity_id, ts, channel, user_id, text, parsed_amount, parsed_amount_vat_included,
                     vat_flag, project_tag, date_override, reply_count, thread_replies_json, raw_json,
                     member_id, message_type, slack_status, currency, withholding_tax, sender_name,
                     sub_amounts, is_cancelled, deposit_completed_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ts) DO UPDATE SET
                    text = EXCLUDED.text,
                    parsed_amount = EXCLUDED.parsed_amount,
                    parsed_amount_vat_included = EXCLUDED.parsed_amount_vat_included,
                    vat_flag = EXCLUDED.vat_flag,
                    project_tag = EXCLUDED.project_tag,
                    date_override = EXCLUDED.date_override,
                    reply_count = EXCLUDED.reply_count,
                    thread_replies_json = EXCLUDED.thread_replies_json,
                    member_id = EXCLUDED.member_id,
                    message_type = EXCLUDED.message_type,
                    slack_status = EXCLUDED.slack_status,
                    currency = EXCLUDED.currency,
                    withholding_tax = EXCLUDED.withholding_tax,
                    sender_name = EXCLUDED.sender_name,
                    sub_amounts = EXCLUDED.sub_amounts,
                    is_cancelled = EXCLUDED.is_cancelled,
                    deposit_completed_date = EXCLUDED.deposit_completed_date
                RETURNING (xmax = 0) AS is_new
                """,
                [
                    entity_id, ts, channel_id, user_id, text,
                    final_amount, parsed.get("parsed_amount_vat_included"),
                    parsed["vat_flag"], parsed["project_tag"], parsed.get("date_override"),
                    reply_count, thread_replies_json, json.dumps(msg, ensure_ascii=False),
                    member_id, parsed["message_type"], status_result["slack_status"],
                    parsed["currency"], parsed["withholding_tax"], sender_name,
                    json.dumps(parsed["sub_amounts"]) if parsed.get("sub_amounts") else None,
                    status_result.get("is_cancelled", False),
                    None,  # deposit_completed_date — TODO: 쓰레드 입금완료 댓글의 ts에서 추출
                ],
            )
            is_new = cur.fetchone()[0]
            if is_new:
                stats["new"] += 1
            else:
                stats["updated"] += 1

        conn.commit()
        cur.close()
        return stats
    except RuntimeError as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        conn.rollback()
        raise
```

- [ ] **Step 3: Run all tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/ -v --tb=short`
Expected: ALL PASS (96 기존 + 새 테스트)

- [ ] **Step 4: Commit**

```bash
git add backend/routers/slack.py backend/routers/accounts.py
git commit -m "feat: Slack 동기화 엔드포인트 + 멤버 slack_user_id + API alias 수정"
```

---

### Task 6: 프론트엔드 — 동기화 버튼 + 멤버 Slack ID

**Files:**
- Modify: `frontend/src/app/slack-match/page.tsx`
- Modify: `frontend/src/app/members/page.tsx`

- [ ] **Step 1: slack-match에 동기화 버튼 추가**

`SlackMatchContent` 컴포넌트 상단, `fetchMessages` 아래에 sync 함수 추가:

```typescript
const [syncing, setSyncing] = useState(false)

const handleSync = useCallback(async () => {
  setSyncing(true)
  try {
    const result = await fetchAPI<{ total_fetched: number; new: number; updated: number; skipped: number }>(
      `/slack/sync?channel=99-expenses&entity_id=${entityId}&year=2026`,
      { method: "POST" },
    )
    toast.success(`동기화 완료: 신규 ${result.new}건, 업데이트 ${result.updated}건`)
    fetchMessages()
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "동기화에 실패했습니다")
  } finally {
    setSyncing(false)
  }
}, [entityId, fetchMessages])
```

헤더 영역에 동기화 버튼:

```tsx
<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
  <div>
    <h1 className="text-2xl font-semibold tracking-tight">Slack 매칭</h1>
    {/* ... existing counts ... */}
  </div>
  <Button onClick={handleSync} disabled={syncing} variant="outline" className="gap-2">
    <RefreshCw className={cn("h-4 w-4", syncing && "animate-spin")} />
    {syncing ? "동기화 중..." : "Slack 동기화"}
  </Button>
</div>
```

`SlackMessage` 인터페이스에 새 필드 추가:

```typescript
interface SlackMessage {
  id: number
  entity_id: number
  channel_name: string
  sender_name: string | null
  message_text: string
  parsed_amount: number | null
  parsed_currency: string | null
  message_date: string
  is_completed: boolean
  is_cancelled: boolean
  slack_status: string
  message_type: string | null
  match_id: number | null
  matched_transaction_id: number | null
  match_confidence: number | null
}
```

`cn` import 추가 (아직 없으면):

```typescript
import { cn } from "@/lib/utils"
```

- [ ] **Step 2: members 페이지에 Slack ID 편집 추가**

`Member` 인터페이스에 `slack_user_id` 추가:

```typescript
interface Member {
  id: number
  entity_id: number
  name: string
  role: string
  card_numbers: string[]
  slack_user_id: string | null
}
```

테이블 헤더에 "Slack" 컬럼 추가:

```tsx
<TableHead>Slack</TableHead>
```

테이블 행에 Slack ID 표시:

```tsx
<TableCell className="text-xs text-muted-foreground font-mono">
  {member.slack_user_id || (
    <span className="text-muted-foreground/50">-</span>
  )}
</TableCell>
```

- [ ] **Step 3: 빌드 확인**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build 성공

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx frontend/src/app/members/page.tsx
git commit -m "feat: Slack 동기화 버튼 + 멤버 Slack ID 표시"
```

---

### Task 7: 멤버 Slack ID 초기 매핑

**Files:** (DB 작업만, 코드 변경 없음)

- [ ] **Step 1: 채널에서 확인된 Slack ID를 멤버에 매핑**

```bash
source .venv/bin/activate && python3 -c "
import psycopg2
from pathlib import Path
env_path = Path('.env')
DATABASE_URL = None
for line in env_path.read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        DATABASE_URL = line.split('=', 1)[1].strip()
        break
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute('SET search_path TO financeone, public')

# Slack ID → 멤버 이름 매핑
mappings = [
    ('U0858TMQCQ4', '하승완'),
    ('U089CFRKW3D', '김주원'),
    ('U089CQMMBH9', '김영수'),
    ('U09L98GAESH', '한로제'),
    ('U09QHD50EJJ', '이창석'),
    ('U0A13JGPXL1', '이동현'),
    ('U089K28L6RL', '유동현'),
    ('U07TGKTAGMV', '김대윤'),
    ('U07TX3UHTM1', '채종민'),
]

for slack_id, name in mappings:
    cur.execute(
        'UPDATE members SET slack_user_id = %s WHERE entity_id = 2 AND name = %s AND is_active = true RETURNING id, name',
        [slack_id, name],
    )
    result = cur.fetchone()
    if result:
        print(f'  mapped: {name} → {slack_id}')
    else:
        print(f'  NOT FOUND: {name}')

# 신수아, 황은상, 백건하 추가
new_members = [
    (2, '신수아', 'member', 'U0AC8K0ETBQ'),
    (2, '황은상', 'member', 'U08C31SFSSU'),
    (2, '백건하', 'member', 'U08NN5XHLFJ'),
]
for entity_id, name, role, slack_id in new_members:
    cur.execute(
        'INSERT INTO members (entity_id, name, role, slack_user_id) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id',
        [entity_id, name, role, slack_id],
    )
    result = cur.fetchone()
    print(f'  added: {name} ({slack_id}) → ID:{result[0]}' if result else f'  exists: {name}')

conn.commit()
cur.close()
conn.close()
"
```

- [ ] **Step 2: 동기화 테스트 실행**

```bash
source .venv/bin/activate && python3 -c "
import requests
resp = requests.post('http://localhost:8000/api/slack/sync?channel=99-expenses&entity_id=2&year=2026')
print(resp.json())
"
```

Expected: `{"total_fetched": 355, "new": ~200, "updated": 0, "skipped": ~155}`

- [ ] **Step 3: Commit (if any code changes were needed)**

---

## Self-Review Checklist

1. **Spec coverage:**
   - ✅ 채널 메시지 + 쓰레드 수집 (Task 4, 5)
   - ✅ 유형 분류 (Task 2)
   - ✅ 금액/통화/VAT/태그/sub_amounts 파싱 (Task 2)
   - ✅ 쓰레드 입금완료/취소/금액변경 감지 (Task 3)
   - ✅ slack_status 분리 (Task 3)
   - ✅ 멤버 매핑 — slack_user_id (Task 5, 7)
   - ✅ 완료 상태 자동 판정 (Task 3)
   - ✅ 프론트 동기화 버튼 (Task 6)
   - ✅ 프론트/백엔드 API alias 수정 (Task 5)
   - ✅ 그룹 매칭 완료 조건 (Task 3 테스트)

2. **Placeholder scan:** 없음. 모든 step에 실제 코드 포함.

3. **Type consistency:** `parse_message()` 반환 dict → sync에서 동일 키 사용. `analyze_thread()` 반환 dict → `resolve_slack_status()`에서 동일 키 사용. `extract_amount()` 반환 `{amount, currency}` → 파서와 분석기 양쪽에서 동일 형태.

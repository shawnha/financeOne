# Slack 경비 채널 동기화 + 쓰레드 분석 — 설계 문서

> 2026-03-29 | Status: DRAFT

## 문제

#99-expenses 채널에 355개 경비 메시지가 있지만, FinanceOne DB에는 0건. 팀원들이 올린 경비 메시지를 수집하고, 카드/은행 거래와 매칭해야 1~3월 경비 처리가 가능하다.

## 목표

1. #99-expenses 채널의 메시지 + 쓰레드 댓글을 DB에 수집
2. 메시지 유형 자동 분류 (법카결제/입금요청/세금계산서/비용공유/비경비)
3. 금액/통화/VAT/프로젝트태그 자동 파싱
4. 쓰레드 댓글에서 입금완료/취소/금액변경 감지 → 메인 메시지 상태 업데이트
5. Slack user_id ↔ members 테이블 매핑
6. 완료 상태 자동 판정 (유형별 로직)

## 비목표 (Not in Scope)

- ExpenseOne 연동 (통합 ERP 시점에 설계)
- Claude AI 기반 분류 (규칙 기반으로 충분, 나중에 추가 가능)
- Slack webhook 실시간 수신 (수동 동기화만)
- 서류/영수증 파일 다운로드 (URL만 저장)

## 실제 채널 데이터 분석 (355개 메시지)

### 메시지 유형 분포

| 유형 | 건수 | 설명 |
|------|------|------|
| 법카 결제완료 | 87 | "개인법카 결제완료", "법카 구매완료" 등 |
| 입금요청 | 50 | "입금요청", "입금 필요" + 계좌정보 |
| 세금계산서 | 12 | "세금계산서 발행 요청/완료" |
| 비용공유/승인요청 | ~80 | "비용 공유드립니다", "승인 요청" |
| 구독 서비스 | ~30 | SaaS 월 결제 공유 |
| Creator payment | ~15 | 해외 인플루언서 USD 결제 |
| 봇 메시지 | 6 | ExpenseOne 봇 (필터링) |
| 시스템 (join 등) | 18 | 필터링 |
| 잡담/질문/공지 | ~50 | 비경비 (필터링) |

### 쓰레드 댓글 패턴 (200개 쓰레드)

| 패턴 | 건수 | 처리 |
|------|------|------|
| 입금완료 | 56 | `is_completed = true`, `deposit_completed_date` 설정 |
| 취소/환불 | 15 | `is_cancelled = true` |
| 금액변경 | 18 | `parsed_amount` 업데이트 (마지막 금액 = 최종) |
| 서류첨부 | 148 | file URL을 `thread_replies_json`에 저장 |
| 승인/확인 | 149 | 참고 정보 (상태 변경 안 함) |

### 금액 표기 패턴

- KRW: `35,000원`, `35000원`, `3만원`
- USD: `$98.78`, `US$882`, `$1,251.00`, `158불`
- EUR: `€2,000`, `2,000 EURO`
- VAT: `(VAT 포함)`, `(vat+)`, `(VAT 제외)`, `(vat-)`, `부가세 별도`, `부가세 포함`
- 원천징수: `(3.3% 제외)` → 실제 입금액 계산 필요

### 프로젝트 태그

`[ODD]`, `[마트약국]`, `[한아원]`, `[AI 웹 제작]`, `[유미특허법인]`, `[Legal]`, `[HOAI]`, `[Claude]`, `[국내 ODD 판매]`, `[ODD 쇼핑백]`, `[바이럴마케팅]` 등

## 아키텍처

```
POST /api/slack/sync?channel=99-expenses&months=1,2,3
    │
    ▼
┌──────────────────────────────────────────┐
│ 1. Slack Collector (slack_client.py)     │
│    conversations.history (페이지네이션)   │
│    conversations.replies (쓰레드 전체)    │
│    users.info (프로필 → member 매핑)      │
│    reactions.get (✅ 리액션 수집)          │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ 2. Message Filter                        │
│    봇 메시지 제외 (bot_id 존재)           │
│    시스템 메시지 제외 (channel_join 등)    │
│    비경비 메시지 필터링:                   │
│      금액 없음 AND 경비 키워드 없음 → skip │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ 3. Message Parser (message_parser.py)    │
│    유형 분류:                             │
│      "결제완료/구매완료" → card_payment    │
│      "입금요청/입금필요" → deposit_request │
│      "세금계산서"       → tax_invoice     │
│      그 외 금액 있음    → expense_share   │
│    금액 추출 (KRW/USD/EUR)               │
│    VAT 처리 (포함/제외/없음)              │
│    프로젝트 태그 추출 [...]              │
│    날짜 추출 (괄호 안 날짜)              │
│    원천징수 3.3% 감지                    │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ 4. Thread Analyzer (thread_analyzer.py)  │
│    댓글 순회하며 이벤트 감지:             │
│    ① 입금완료 → is_completed, date 설정   │
│    ② 취소/환불 → is_cancelled             │
│    ③ 금액변경 → parsed_amount 업데이트    │
│    ④ 파일 첨부 → file URL 수집            │
│    thread_replies_json에 전체 저장         │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ 5. Status Resolver                       │
│    유형별 완료 판정:                      │
│    card_payment  → 항상 is_completed      │
│    deposit_request → ✅ 리액션 시 완료    │
│    tax_invoice   → ✅ 리액션 시 완료      │
│    expense_share → ✅ 리액션 시 완료      │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ 6. DB Upsert                             │
│    slack_messages UPSERT (ts 기준)       │
│    member_id 매핑 (slack user_id → FK)   │
│    중복 방지: ON CONFLICT (ts) DO UPDATE  │
└──────────────────────────────────────────┘
```

## DB 변경

### members 테이블에 slack_user_id 추가

```sql
ALTER TABLE members ADD COLUMN IF NOT EXISTS slack_user_id TEXT;
-- entity_id + slack_user_id 복합 unique (같은 사람이 여러 법인에 존재 가능)
CREATE UNIQUE INDEX IF NOT EXISTS uq_members_slack ON members (entity_id, slack_user_id) WHERE slack_user_id IS NOT NULL;
```

### slack_messages 테이블에 컬럼 추가

```sql
ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS member_id INTEGER REFERENCES members(id);
ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS message_type TEXT; -- card_payment, deposit_request, tax_invoice, expense_share, other
ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS slack_status TEXT DEFAULT 'pending'; -- pending, done, cancelled (Slack 처리 상태, is_completed와 분리)
ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'KRW';
ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS withholding_tax BOOLEAN DEFAULT FALSE;
ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS sender_name TEXT; -- Slack 프로필에서 가져온 이름
ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS sub_amounts JSONB; -- 다중 항목 개별 금액 [{amount, description}]
-- 참고: is_completed는 기존대로 '거래 매칭 확정' 의미로 유지
```

### 기존 컬럼 활용 (변경 없음)

- `ts` — Slack 타임스탬프 (UNIQUE, 메시지 ID)
- `channel` — 채널 ID
- `user_id` — Slack user ID
- `text` — 메시지 원문
- `parsed_amount` — 파싱된 금액
- `parsed_amount_vat_included` — VAT 포함 금액
- `vat_flag` — included/excluded/none
- `project_tag` — 프로젝트 태그
- `is_completed` — 처리 완료
- `is_cancelled` — 취소됨
- `deposit_completed_date` — 입금 완료 날짜
- `reply_count` — 댓글 수
- `thread_replies_json` — 댓글 전체 JSON
- `raw_json` — Slack API 원본
- `date_override` — 메시지에서 추출한 날짜

## 다중 항목 매칭 전략 (v1 방식)

다중 항목 메시지 (Pattern C):
```
[ODD] 스티커 851,400원 + 포장 286,100원 합계 1,137,500원
```

1. `parsed_amount` = 합계 (1,137,500)
2. `sub_amounts` = [{"amount": 851400, "desc": "스티커"}, {"amount": 286100, "desc": "포장"}]
3. 매칭 순서:
   - sub_amounts 각각으로 거래 매칭 시도 (개별 결제된 경우)
   - 개별 매칭 실패 → parsed_amount(합계)로 매칭 시도
   - 합계 키워드: "합계", "총", "=", "총금액", "총액"
4. 그룹 매칭 완료 조건:
   - sub_amounts 전부 매칭됨 → 그룹 완료 (is_completed = true)
   - OR parsed_amount(합계)가 1건 거래와 매칭됨 → 그룹 완료
   - 일부만 매칭 → 미완료 (부분 매칭 상태로 표시)
   - transaction_slack_match에 그룹 내 개별 매칭 각각 기록

## 메시지 파서 상세

### 유형 분류 우선순위 (순서대로 매칭, 첫 번째 히트)

```python
CLASSIFICATION_RULES = [
    ("card_payment",    ["결제완료", "결제 완료", "구매완료", "구매 완료", "법카로 결제"]),
    ("deposit_request", ["입금요청", "입금 요청", "입금 필요", "입금요청드립니다", "입금 부탁"]),
    ("tax_invoice",     ["세금계산서 발행", "세금계산서 요청"]),
    ("expense_share",   None),  # 금액이 있으면 기본 분류
]
```

### 금액 추출 정규식

```python
# KRW: 35,000원, 35000원, 3만원, 총 330,000원
KRW_PATTERN = r'(?:총\s*)?(\d{1,3}(?:,\d{3})*)\s*원'
KRW_MAN_PATTERN = r'(\d+)\s*만\s*원'  # 3만원 → 30000

# USD: $98.78, US$882, $1,251.00, 158불, 11달러
USD_PATTERN = r'(?:US)?\$\s*([\d,]+(?:\.\d{2})?)'
USD_BUL_PATTERN = r'(\d+(?:,\d+)?)\s*(?:불|달러)'

# EUR: €2,000, 2,000 EURO
EUR_PATTERN = r'€\s*([\d,]+(?:\.\d{2})?)|(\d+(?:,\d+)?)\s*(?:EURO|유로)'
```

### VAT 처리

```python
VAT_RULES = [
    ("included",  ["VAT 포함", "vat+", "vat포함", "부가세 포함", "VAT+"]),
    ("excluded",  ["VAT 제외", "vat-", "vat제외", "부가세 별도", "VAT 별도", "VAT-"]),
]
# 매칭 안 되면 "none"
# VAT 포함 → parsed_amount_vat_included = parsed_amount
# VAT 제외 → parsed_amount_vat_included = parsed_amount * 1.1
```

### 원천징수 감지

```python
# "3.3% 제외", "3.3% 공제" → withholding_tax = True
# 실제 입금액 = parsed_amount * (1 - 0.033)
WITHHOLDING_PATTERN = r'3\.3%\s*(?:제외|공제)'
```

### 프로젝트 태그 추출

```python
# [ODD], [마트약국], [AI 웹 제작] 등
TAG_PATTERN = r'\[([^\]]+)\]'
# 첫 번째 매칭 사용 (보통 메시지 시작 부분)
```

## 완료 상태 판정 로직

```python
def resolve_slack_status(message_type, has_check_reaction, thread_events):
    """메시지 유형과 리액션/쓰레드 이벤트로 Slack 처리 상태 판정.

    주의: is_completed는 '거래 매칭 확정'으로 별도 관리. 여기서는 slack_status만 결정.
    """

    # 쓰레드에서 취소 감지
    if "cancel" in thread_events:
        return {"slack_status": "cancelled", "is_cancelled": True}

    # 법카 결제 → 올린 시점에 이미 Slack 처리 완료
    if message_type == "card_payment":
        return {"slack_status": "done"}

    # 쓰레드에서 입금완료 감지
    if "deposit_done" in thread_events:
        return {"slack_status": "done", "deposit_completed_date": thread_events["deposit_done"]["date"]}

    # ✅ 리액션 → Slack 처리 완료
    if has_check_reaction:
        return {"slack_status": "done"}

    # 그 외 → 미처리
    return {"slack_status": "pending"}
```

## 쓰레드 분석기 상세

```python
THREAD_EVENT_RULES = {
    "deposit_done": ["입금완료", "입금 완료", "이체완료", "이체 완료", "송금완료", "송금 완료", "입금했습니다", "이체했습니다"],
    "cancel": ["취소", "환불", "반품", "캔슬", "환불처리", "반품하였습니다"],
    "amount_change": None,  # 금액 정규식으로 감지
}
```

금액변경 감지: 댓글에 금액 패턴이 있고, 메인 메시지의 `parsed_amount`와 다르면 → 마지막 댓글의 금액이 최종.

## Slack User ↔ Member 매핑

동기화 시:
1. `users.info` API로 Slack user의 `real_name` 조회
2. `members` 테이블에서 `slack_user_id`로 매칭 시도
3. 매칭 안 되면 `name` LIKE 매칭 시도 (fuzzy)
4. 매칭 안 되면 `sender_name`만 저장, `member_id = NULL`
5. 멤버 관리 페이지에서 수동으로 `slack_user_id` 연결 가능

### 채널에서 확인된 Slack 유저 ↔ 멤버 매핑

| Slack User ID | Slack 이름 | members.name | 비고 |
|--------------|-----------|-------------|------|
| U0858TMQCQ4 | Shawn Ha | 하승완 | 기존 |
| U089CFRKW3D | Juwon Kim | 김주원 | 기존 |
| U089CQMMBH9 | Youngsoo Kim | 김영수 | 기존 |
| U09L98GAESH | Rosse Han | 한로제 | 기존 |
| U0AC8K0ETBQ | Soo Ah Shin | 신수아 | 추가 필요 |
| U09QHD50EJJ | Changseok Lee | 이창석 | 기존 |
| U08C31SFSSU | Eun Sang Hwang | 황은상 | 추가 필요 |
| U0A13JGPXL1 | Donghyun Lee | 이동현 | 기존 |
| U089K28L6RL | Donghyun Yoo | 유동현 | 기존 |
| U08NN5XHLFJ | Geonha Baek | 백건하 | 추가 필요 |
| U07TGKTAGMV | Joey Kim | 김대윤 | 기존 |
| U07TX3UHTM1 | Jongmin Chae | 채종민 | 기존 |

## API 엔드포인트

### 동기화

```
POST /api/slack/sync
  Query params:
    channel: str = "99-expenses"    -- 채널 이름
    entity_id: int                  -- 법인 ID (필수)
    year: int = 2026                -- 연도 (필수, 모호성 방지)
    months: str = "1,2,3"           -- 수집할 월 (optional, 없으면 전체)
  Response:
    { "total_fetched": 355, "new": 200, "updated": 50, "skipped": 105 }
```

### 멤버 매핑 (멤버 관리 페이지에서)

```
PATCH /api/accounts/members/{member_id}
  Body: { "slack_user_id": "U0858TMQCQ4" }
```

## 파일 구조

| Action | File | 책임 |
|--------|------|------|
| Create | `backend/services/slack/slack_client.py` | Slack API 호출 (history, replies, users) |
| Create | `backend/services/slack/message_parser.py` | 유형 분류, 금액/VAT/태그 파싱 |
| Create | `backend/services/slack/thread_analyzer.py` | 쓰레드 이벤트 감지 |
| Modify | `backend/routers/slack.py` | `POST /sync` 엔드포인트 추가 |
| Modify | `backend/routers/accounts.py` | members에 slack_user_id 지원 |
| Modify | `backend/database/schema.sql` | 스키마 업데이트 |
| Modify | `frontend/src/app/members/page.tsx` | Slack ID 표시/편집 |
| Modify | `frontend/src/app/slack-match/page.tsx` | 동기화 버튼 + 멤버 이름 표시 |
| Create | `backend/tests/test_message_parser.py` | 파서 유닛 테스트 |
| Create | `backend/tests/test_thread_analyzer.py` | 쓰레드 분석 테스트 |

## 에러 처리

- Slack API rate limit → 1초 간격으로 호출, 429 시 exponential backoff
- 토큰 만료/무효 → `invalid_auth` 에러 → 사용자에게 토큰 재설정 안내
- 파싱 실패 (금액 없음) → `message_type = "other"`, 수동 분류 유도
- 멤버 매칭 실패 → `member_id = NULL`, `sender_name`만 저장

## 테스트 계획

### 파서 테스트 (test_message_parser.py)
- 법카결제 메시지 분류
- 입금요청 메시지 분류
- KRW 금액 추출 (쉼표, 만원 단위)
- USD 금액 추출 ($, US$, 불)
- VAT 포함/제외 판별
- 프로젝트 태그 추출
- 원천징수 3.3% 감지
- 비경비 메시지 필터링

### 쓰레드 분석 테스트 (test_thread_analyzer.py)
- 입금완료 키워드 감지
- 취소/환불 키워드 감지
- 금액변경 감지 (마지막 금액 = 최종)
- 파일 URL 수집

### 상태 판정 테스트
- card_payment → slack_status=done (is_completed는 별도, 매칭 시 설정)
- deposit_request + ✅ → slack_status=done
- deposit_request + 쓰레드 입금완료 → slack_status=done
- 쓰레드 취소 → slack_status=cancelled
- 리액션 없음 + 입금요청 → slack_status=pending

### 그룹 매칭 완료 테스트
- sub_amounts 전부 매칭 → 그룹 완료
- 합계 1건 매칭 → 그룹 완료
- 부분 매칭 → 미완료

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 2 | CLEAR | mode: HOLD_SCOPE, 0 critical gaps |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | 8 findings (3 applied) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 3 | CLEAR | 1 issue (API mismatch), 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR | score: 6/10 → 8/10 (prior review) |

- **CODEX:** is_completed 이중 의미, entity_id 누락, slack_user_id unique 제약 오류 수정 반영
- **VERDICT:** CEO + ENG CLEARED — ready to implement

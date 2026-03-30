# Slack 구조화 파싱 엔진 설계

> 2026-03-30 | Brainstorming 완료 → 구현 대기

## 목적

Slack 경비 채널 메시지를 Claude Sonnet API로 구조화된 경비 요청서(JSON)로 변환한다.
기존 regex 파싱은 유지하되, Claude가 regex로 추출 불가능한 항목(vendor, category, 선금/잔금, 항목 분해 등)을 보강한다.

## 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 모델 | Claude Sonnet 4.6 (structured output) |
| 호출 시점 | sync 시 즉시 (동기) |
| 호출 단위 | 메시지 1건당 1회 |
| 스킵 조건 | parsed_structured 존재 + text/reply_count 동일 |
| 저장 방식 | slack_messages.parsed_structured JSONB 컬럼 |
| regex 관계 | regex 유지 + Claude 보강 (fallback) |
| 선금/잔금 | Claude가 힌트(payment_terms) 저장, DB 연결 로직은 미구현 |
| 프론트 | 카드 펼침 시 구조화 테이블, 원문은 추가 토글 |
| 비용 | 월 최대 ~$0.62 (89건 기준) |

## 아키텍처

```
Slack Channel
    │
    ▼
POST /api/slack/sync
    │
    ├─ 1. fetch_history()          ← 기존
    ├─ 2. regex 파싱               ← message_parser.py (기존)
    ├─ 3. thread 분석              ← thread_analyzer.py (기존)
    ├─ 4. Claude 구조화 파싱        ← NEW: structured_parser.py
    │     ├─ 입력: 메시지 본문 + 쓰레드 댓글
    │     ├─ 출력: parsed_structured JSONB
    │     └─ 실패 시: null (regex 결과만 유지)
    ├─ 5. DB upsert               ← parsed_structured 컬럼 추가 저장
    │
    ▼
Frontend (Slack 매칭 페이지)
    └─ 카드 펼침 → parsed_structured 있으면 구조화 테이블
                   없으면 기존 원문 표시
```

### 새로 만드는 파일
- `backend/services/slack/structured_parser.py`

### 수정하는 파일
- `backend/database/schema.sql` — parsed_structured 컬럼 추가
- `backend/routers/slack.py` — sync 플로우에 구조화 파싱 단계 추가
- `frontend/src/app/slack/` — 카드 펼침 UI에 구조화 테이블 추가

## Claude API 프롬프트 설계

### 시스템 프롬프트

```
한아원 그룹 내부 경비 Slack 메시지를 구조화된 JSON으로 변환하세요.

규칙:
- 금액은 숫자만 (콤마/원/만원 → 정수로 변환)
- VAT 별도(vat-)면 vat_amount에 10% 계산, supply_amount에 원금
- VAT 포함(vat+)면 supply_amount = 총액/1.1, vat_amount = 총액 - supply_amount
- 3.3% 원천징수 언급 시 withholding rate/amount/net_amount 계산
- 선금/잔금은 payment_terms.type으로 구분 (full/advance/balance/installment)
- 항목이 여러 개면 items 배열로 분리 (bullet 형식 아니어도)
- 확신 없는 필드는 null
- 쓰레드 댓글이 있으면 최종 상태(금액 변경, 입금 완료 등) 반영
```

### 유저 프롬프트

```
[메시지 본문]
{text}

[쓰레드 댓글] (있는 경우)
{reply_1_sender}: {reply_1_text}
{reply_2_sender}: {reply_2_text}
...
```

### 출력 JSON 스키마

```json
{
  "summary": "1줄 요약 (한국어)",
  "vendor": "거래처/업체명 또는 null",
  "project": "프로젝트명 또는 null",
  "category": "식비|교통|구독|마케팅|촬영|배송|인건비|기타",
  "items": [
    {
      "description": "항목 설명",
      "amount": 35000,
      "currency": "KRW"
    }
  ],
  "total_amount": 47000,
  "currency": "KRW",
  "vat": {
    "type": "none|included|excluded",
    "vat_amount": null,
    "supply_amount": null
  },
  "withholding_tax": {
    "applies": false,
    "rate": null,
    "amount": null,
    "net_amount": null
  },
  "payment_terms": {
    "type": "full|advance|balance|installment",
    "ratio": null,
    "related_context": null
  },
  "tax_invoice": false,
  "date_mentioned": "2026-01-15 또는 null",
  "urgency": "오늘 중|내일까지|null",
  "confidence": 0.95
}
```

### category → 내부계정 매핑

| category | 내부계정 코드 |
|---|---|
| 식비 | EXP-010 |
| 교통 | EXP-040 |
| 구독 | EXP-050 |
| 마케팅 | EXP-060 |
| 촬영 | EXP-100-001 |
| 배송 | EXP-040-004 |
| 인건비 | EXP-070 |
| 기타 | EXP-090 |

## sync 플로우 변경

### Claude 호출 조건

```python
# 호출하는 경우
should_parse = (
    existing.parsed_structured is None           # 신규 메시지
    or existing.text != new_text                  # 메시지 편집됨
    or existing.reply_count < new_reply_count     # 새 쓰레드 댓글
)

# 스킵하는 경우
skip = (
    not should_parse                              # 이미 파싱 완료 + 변경 없음
    or message_type == 'other'                    # 금액 없는 잡담
    or regex_result.skip is True                  # 봇/시스템 메시지
)
```

### 에러 처리

| 에러 | 대응 |
|---|---|
| Claude API timeout/rate limit/5xx | parsed_structured = null, 다음 sync 시 재시도 |
| JSON 파싱 실패 | parsed_structured = null, raw response 로그 기록 |
| sync 1회 100건 초과 | 나머지는 다음 sync로 이월 |

### 성능

- 신규 메시지당 Sonnet 응답: ~1-2초
- 일반 sync (1-3건 신규): 2-6초 추가
- 이미 파싱된 메시지: 스킵 (추가 시간 0)

## DB 변경

```sql
ALTER TABLE slack_messages
  ADD COLUMN parsed_structured JSONB DEFAULT NULL;

COMMENT ON COLUMN slack_messages.parsed_structured IS
  'Claude Sonnet 구조화 파싱 결과. null이면 미파싱 (regex 결과만 사용)';
```

## 프론트엔드

### 카드 접힌 상태 (기존 + 날짜 위치 변경)

```
┌───────────────────────────────────────────────┐
│ 1/15  홍길동  [ODD] 촬영 택시비 + 점심  ₩47,000 │
│ 입금요청 · pending                                │
└───────────────────────────────────────────────┘
```

- 날짜를 이름 앞에 배치 (날짜순 정렬 기준이므로)

### 카드 펼침 상태 — parsed_structured 있을 때

```
┌───────────────────────────────────────┐
│ 📋 구조화 정보                         │
│                                       │
│  프로젝트   ODD                       │
│  거래처     카카오택시                  │
│  카테고리   교통                       │
│                                       │
│  항목              금액               │
│  ───────────────────────             │
│  택시비            ₩35,000            │
│  점심              ₩12,000            │
│  ───────────────────────             │
│  합계              ₩47,000            │
│                                       │
│  VAT       해당없음                    │
│  원천징수   없음                       │
│  결제조건   일시불                      │
│                                       │
│  ▸ 원문 보기                          │
└───────────────────────────────────────┘
```

### 카드 펼침 상태 — parsed_structured 없을 때
기존 원문 텍스트 표시 (현재와 동일)

## 범위 외 (향후)

- 선금/잔금 DB 연결 로직 — ExpenseOne 연동 시 재설계
- 자동 규칙 매칭 (Stage 4-6) — 별도 설계
- 크로스월 매칭 — 별도 작업
- 내부계정 자동 배정 — ExpenseOne 연동 시

## 비용 추정

| 항목 | 수치 |
|---|---|
| 메시지당 input | ~1,000 tokens |
| 메시지당 output | ~300 tokens |
| 메시지당 비용 (Sonnet) | ~$0.007 |
| 월 최대 (89건) | ~$0.62 |
| 월 평균 (30건) | ~$0.21 |
| 연간 추정 | ~$5.3 |

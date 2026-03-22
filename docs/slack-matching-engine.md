# Slack Matching Engine — 설계 문서

> v1(Fynabl)에서 포팅. 범용 재사용 가능한 경비 메시지 ↔ 거래 매칭 엔진.

## 개요

팀원들이 Slack 채널에 올린 경비 메시지(법카 결제, 입금 요청 등)를 카드/은행 거래 내역과 자동 매칭하는 엔진. 4월 ExpenseOne 전환 전까지 1~3월 데이터 처리에 사용.

## 아키텍처

```
Slack 채널
    │
    ▼ Slack API (conversations.history + conversations.replies)
┌─────────────────────────────────────────────┐
│ 1. Message Collector (slack_client.py)       │
│    - 채널 메시지 수집 (페이지네이션)             │
│    - 쓰레드 댓글 수집 (conversations.replies)   │
│    - 사용자 프로필 조회                         │
│    - 리액션 조회                               │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ 2. Message Parser (message_parser.py)       │
│    - 4가지 패턴 인식 (A/B/C/D)                │
│    - 금액 추출 (₩, 원, $, USD)               │
│    - VAT 처리 (포함/제외/없음)                 │
│    - 날짜 추출 (괄호 안 날짜 우선)              │
│    - 프로젝트 태그 추출 [ODD], [HAK] 등        │
│    - 다중 항목 분리 (서브 메시지)               │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ 3. Thread Analyzer (thread_analyzer.py)     │
│    - 취소 감지 ("취소", "반품" 등)              │
│    - 입금완료 감지 → 매칭 날짜 업데이트          │
│    - 댓글에서 금액 변경 감지 (마지막 금액 = 최종)  │
│    - VAT 재적용                               │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ 4. Rule Matcher (matcher.py)                │
│    3단계 금액 매칭:                            │
│    ① 정확 매칭 (±1원) → 최고 신뢰도            │
│    ② VAT 역매칭 (VAT 제외/포함 금액) → -0.05   │
│    ③ 수수료 허용 (±5%, max ±5,000원) → -0.15  │
│    + 텍스트 유사도 (키워드 비교) → +0.05 보너스   │
│    + 합산 매칭 (서브 항목 합계 = 1건 거래)       │
│    + 날짜 범위 필터 (메시지 날짜 ± N일)          │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ 5. Pattern Learner (pattern_matcher.py)     │
│    - 확정된 매칭에서 반복 패턴 학습              │
│    - 거래처/설명 → 내부계정 매핑 캐시            │
│    - 패턴 신뢰도 부스트 (hit_count 기반)        │
│    - 0.8 이상이면 AI 검증 생략                 │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ 6. AI Validator (ai_matcher.py)             │
│    - Claude API로 후보 의미적 검증              │
│    - Few-shot: 이전 확정 결과를 예시로 제공       │
│    - 배치 처리 (25건씩)                        │
│    - AUTO_ACCEPT_THRESHOLD(0.8) 초과 시 생략   │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ 7. UI: 매칭 확인/수정/확정                     │
│    - 자동 매칭 결과 리뷰                       │
│    - 수동 매칭 (드래그 or 선택)                 │
│    - 일괄 확정                                │
│    - 매칭 해제                                │
└─────────────────────────────────────────────┘
```

## 메시지 파싱 패턴

### Pattern A: 법카 결제완료
```
[ODD] 카카오택시 35,000원 - 법카 결제완료
[ODD] 네이버 서버 비용 150,000원 (VAT 별도) - 법카 결제완료 (1/15)
```

### Pattern B: 입금요청
```
[HAK] 박세미 마케팅비용 577,500원 - 입금요청
[HAK] 임대료 9,059,270원 (VAT 포함) - 입금요청 (2/27)
```

### Pattern C: 다중 항목
```
[ODD] 1월 구독료 정리
- Slack 월 구독 $12.50
- GitHub 월 구독 $4.00
- AWS 서버 비용 45,000원
합계: 약 70,000원
```

### Pattern D: 프로젝트 태그 없음
```
카카오 T 대리 18,000원
OPENAI 구독료 $20
```

## DB 테이블

### slack_messages
| 필드 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | |
| entity_id | INTEGER FK | 법인 |
| ts | TEXT UNIQUE | Slack 타임스탬프 (메시지 고유 ID) |
| channel | TEXT | 채널 ID |
| user_id | TEXT | Slack 사용자 ID |
| text | TEXT | 메시지 원문 |
| parsed_amount | NUMERIC(18,2) | 파싱된 금액 |
| parsed_amount_vat_included | NUMERIC(18,2) | VAT 포함 금액 |
| vat_flag | TEXT | 'included', 'excluded', 'none' |
| project_tag | TEXT | 프로젝트 태그 ([ODD], [HAK] 등) |
| is_completed | BOOLEAN | 처리 완료 여부 |
| raw_json | TEXT | Slack API 원본 JSON |
| date_override | DATE | 메시지 본문에서 추출한 날짜 |
| is_cancelled | BOOLEAN | 쓰레드 댓글에서 "취소" 감지 |
| deposit_completed_date | DATE | "입금 완료" 댓글 날짜 |
| reply_count | INTEGER | Slack reply_count 캐시 |
| thread_replies_json | TEXT | [{ts, user, text}] 댓글 원본 |
| created_at | TIMESTAMPTZ | |

### transaction_slack_match
| 필드 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | |
| transaction_id | INTEGER FK | transactions.id |
| slack_message_id | INTEGER FK | slack_messages.id |
| match_confidence | NUMERIC(3,2) | 매칭 신뢰도 (0.0~1.0) |
| is_manual | BOOLEAN | 수동 매칭 여부 |
| is_confirmed | BOOLEAN | 사용자 확정 여부 |
| ai_reasoning | TEXT | AI 매칭 판단 근거 |
| note | TEXT | 사용자 메모 |
| amount_override | NUMERIC(18,2) | 매칭별 금액 오버라이드 |
| text_override | TEXT | 매칭별 텍스트 오버라이드 |
| project_tag_override | TEXT | 매칭별 프로젝트 태그 오버라이드 |
| created_at | TIMESTAMPTZ | |

## 매칭 신뢰도 계산

| 조건 | 신뢰도 변화 |
|------|-----------|
| 정확 매칭 (±1원) | 기본 0.9 |
| VAT 역매칭 | -0.05 |
| 수수료 허용 매칭 (±5%) | -0.15 |
| 텍스트 키워드 일치 | +0.05 |
| 패턴 학습 부스트 (반복 거래) | +0.15 max |
| AI 검증 통과 | 신뢰도 유지/조정 |
| **AUTO_ACCEPT_THRESHOLD** | **0.8 이상 → AI 검증 생략** |

## 날짜 매칭 우선순위

1. `deposit_completed_date` — 쓰레드 댓글에서 "입금 완료" 날짜
2. `date_override` — 메시지 본문 괄호 안 날짜 `(1/15)`
3. Slack `ts` → datetime 변환

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/slack/sync` | 채널 메시지 동기화 (월 지정 가능) |
| GET | `/api/slack/messages` | 수집된 메시지 목록 (필터/페이지네이션) |
| GET | `/api/slack/matches` | 매칭 결과 목록 |
| POST | `/api/slack/match/auto` | 자동 매칭 실행 (규칙 + AI) |
| POST | `/api/slack/match/manual` | 수동 매칭 (1건) |
| POST | `/api/slack/match/bulk` | 수동 매칭 (일괄) |
| PATCH | `/api/slack/match/{id}/confirm` | 매칭 확정 |
| DELETE | `/api/slack/match/{id}` | 매칭 해제 |
| PATCH | `/api/slack/messages/{id}` | 메시지 수동 수정 (금액, 텍스트) |

## Slack Bot 필요 권한 (OAuth Scopes)

- `channels:history` — 공개 채널 메시지 읽기
- `groups:history` — 비공개 채널 메시지 읽기
- `reactions:read` — 리액션 읽기
- `users.profile:read` — 사용자 프로필
- `channels:read` — 채널 목록

## v2 포팅 시 변경 사항

- SQLAlchemy → psycopg2 직접 쿼리 (v2 패턴)
- `entity_id` 추가 (v1에 없었음)
- DB: SQLite → PostgreSQL (Neon)
- Settings 테이블 구조 변경에 맞춰 토큰 조회 수정

## 재사용 가능성

이 엔진은 Slack 메시지 ↔ 거래 매칭이라는 범용 문제를 해결. 다른 프로젝트에서도:
- Slack 경비 채널 → 회계 시스템 연동
- 메시지 기반 입금/지출 추적
- AI 기반 텍스트 ↔ 숫자 데이터 매칭

으로 재활용 가능.

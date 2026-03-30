# 다중 항목 개별 매칭 워크플로우 — Design Spec

## 문제

Slack 메시지 하나에 여러 비용 항목이 포함된 경우(예: 현수막 설치 1,350,000 + 제거 400,000 + 수수료 61,250), 현재 시스템은 총액(total_amount)으로만 1:1 매칭을 시도한다. 총액에 해당하는 거래가 없으면 매칭 불가 상태로 남는다.

## 해결

전체 금액 매칭 실패 시, 각 항목(items)을 별도 거래에 개별 매칭하는 워크플로우를 추가한다.

## 설계 결정

| 항목 | 결정 | 이유 |
|------|------|------|
| 모드 전환 | 자동 — items ≥ 2이면 개별 매칭 섹션 자동 노출 | 클릭 한 번 줄임, 다중 항목 메시지에서 자연스러운 흐름 |
| 확정 단위 | 항목별 개별 확정 | 부분 매칭 허용, 나중에 나머지 매칭 가능 |
| UI 인터랙션 | 항목 클릭 → 후보 패널 갱신 | 기존 UI 패턴 재활용, 구현 간단 |
| DB 저장 | 기존 transaction_slack_match 테이블 확장 | item_index 컬럼 추가, 하위호환 |
| 레이아웃 | 탭 분리 (전체 매칭 / 개별 매칭) | 화면 공간 효율적, 모드 명확 |
| 탭 컴포넌트 | shadcn/ui Tabs | 키보드 접근성 내장, 프로젝트 일관성 |
| 확정 후 동작 | 자동으로 다음 미매칭 항목으로 이동 + 토스트 | 연속 작업 효율성 |
| 확정 취소 | 허용 — 확정된 항목 옆 "취소" 버튼 | 실수 복구 가능 |
| 탭 표시 조건 | items 0~1개면 탭 숨김 (기존 UI 유지) | 불필요한 UI 제거 |
| 동일 금액 항목 | 허용 — 이미 매칭된 거래만 후보에서 제외 | 자연스러운 중복 처리 |
| 부분 매칭 + 무시 | 경고 후 허용 — 매칭 해제 안내 | 데이터 손실 방지 |
| 반응형 | 데스크탑 전용 (최소 1024px) | 내부 BPO 도구 |

## DB 변경

### transaction_slack_match 테이블 확장

```sql
ALTER TABLE financeone.transaction_slack_match
  ADD COLUMN item_index INTEGER DEFAULT NULL,
  ADD COLUMN item_description TEXT DEFAULT NULL;
```

- `item_index`: 구조화 파싱의 items 배열 인덱스 (0-based). NULL이면 전체 금액 매칭(기존 방식).
- `item_description`: 해당 항목의 설명 텍스트 (예: "설치", "제거"). 조회 편의용.
- 기존 데이터: 모두 item_index=NULL로 하위호환.
- UNIQUE 제약: `(slack_message_id, item_index)` — 같은 메시지의 같은 항목을 중복 매칭 방지. 전체 매칭(item_index=NULL)은 기존 동작 유지.

### is_completed 판단 로직 변경

- **전체 매칭(items 없거나 1개)**: 기존과 동일. 매칭 확정 시 is_completed=true.
- **개별 매칭(items ≥ 2)**: 모든 항목이 매칭 확정되었을 때 is_completed=true. 부분 매칭 상태에서는 is_completed=false 유지.

## API 변경

### GET /api/slack/messages/{message_id}/candidates

**새 파라미터:**
- `item_index` (optional int): 지정 시 해당 항목의 금액으로만 후보 검색. 미지정이면 기존 동작(전체 금액 + 모든 항목 금액).

**동작:**
1. `item_index` 지정 → `parsed_structured.items[item_index].amount`로 후보 검색
2. `item_index` 미지정 → 기존 동작 (total_amount + 모든 items 금액)
3. 이미 다른 항목에 확정된 거래는 후보에서 제외
4. 같은 메시지의 다른 항목에 이미 확정된 transaction_id도 후보에서 제외

### POST /api/slack/messages/{message_id}/confirm

**새 필드:**
- `item_index` (optional int): 개별 항목 매칭 시 항목 인덱스
- `item_description` (optional str): 항목 설명

**동작:**
1. `item_index` 지정 → 해당 항목만 매칭 확정. 같은 메시지의 다른 항목은 영향 없음.
2. `item_index` 미지정 → 기존 전체 매칭 동작.
3. 확정 후, 해당 메시지의 모든 항목이 매칭 완료되었는지 확인 → 전부 완료면 is_completed=true.
4. 중복 방지: 같은 (slack_message_id, item_index) 조합이 이미 확정이면 409 에러.

### DELETE /api/slack/messages/{message_id}/confirm/{item_index}

**신규 엔드포인트 — 개별 매칭 확정 취소:**
1. 해당 (slack_message_id, item_index) 매칭 레코드 삭제
2. is_completed 재계산 (남은 미매칭 항목이 있으면 false)
3. 성공 시 200, 매칭 없으면 404

### GET /api/slack/messages 응답 확장

각 메시지에 `item_matches` 배열 추가:

```json
{
  "id": 1339,
  "parsed_structured": { "items": [...], "total_amount": 1811250 },
  "item_matches": [
    { "item_index": 0, "item_description": "설치", "transaction_id": 6001, "is_confirmed": true },
    { "item_index": 1, "item_description": "제거", "transaction_id": null, "is_confirmed": false },
    { "item_index": 2, "item_description": "수수료", "transaction_id": 6003, "is_confirmed": true }
  ],
  "match_progress": { "total_items": 3, "matched_items": 2 }
}
```

- `item_matches`: items가 2개 이상인 메시지에만 포함. 각 항목의 매칭 상태.
- `match_progress`: 매칭 진행률 (UI 프로그레스 바용).

## 프론트엔드 변경

### 후보 패널 (오른쪽)

**기존 동작 유지:** items가 0~1개인 메시지는 현재와 동일하게 동작. 탭 표시 안 함.

**다중 항목 모드 (items ≥ 2):**

shadcn/ui Tabs로 두 탭 표시:
- **[전체 매칭]** 탭: total_amount 기준 후보 리스트 (기존과 동일)
- **[개별 매칭 (N)]** 탭: 항목 수 배지 + 항목 테이블 + 항목별 후보

전체 매칭이 확정되면 개별 매칭 탭 비활성화. 개별 매칭이 1개라도 확정되면 전체 매칭 탭 비활성화 + "개별 매칭이 진행 중입니다" 안내.

### 항목 테이블 (개별 매칭 탭 내)

```
┌─────────────────────────────────────────────┐
│ 항목명          금액           상태          │
│─────────────────────────────────────────────│
│ ▶ 설치       1,350,000    [선택중] 노란BG  │
│   제거         400,000    [미매칭] 회색     │
│   수수료        61,250    [✓확정] 녹색 취소 │
│─────────────────────────────────────────────│
│   합계       1,811,250    2/3 매칭          │
│   ⚠️ 합계 ≠ total 시 경고 배너             │
└─────────────────────────────────────────────┘
```

| 열 | 내용 |
|----|------|
| 항목명 | items[].description |
| 금액 | items[].amount (formatKRW) |
| 상태 | 미매칭(회색 텍스트) / 선택중(노란 하이라이트 행) / ✓ 확정(녹색 + "취소" 링크) |

- 행 클릭 → 해당 항목이 "선택중" 상태로 전환, 아래에 후보 리스트 표시
- 후보 선택 + 확정 → 행 상태가 "✓ 확정"으로 전환 → 자동으로 다음 미매칭 항목 선택
- 확정된 항목의 "취소" 클릭 → DELETE API 호출 → 미매칭으로 복귀
- 합계 행: items 합계 표시 + 매칭 진행률
- items 합계 ≠ total_amount 시: 노란 경고 배너 "파싱된 합계(X)와 총액(Y)이 다릅니다"
- ARIA: role="listbox", 각 행 role="option", aria-label="설치 항목, 1,350,000원, 미매칭"

### 항목별 후보 리스트

선택된 항목 아래에 표시. 기존 후보 카드와 동일한 디자인:
- 날짜, 거래처, 설명, 금액, confidence 배지
- 클릭으로 선택 → 녹색 테두리 + 확정 버튼 출현
- 해당 메시지의 다른 항목에 이미 매칭된 거래는 후보에서 제외

### 메시지 카드 (왼쪽)

- 다중 항목 메시지에 매칭 진행률 표시: Badge "2/3 항목 매칭"
- 모든 항목 완료 시 녹색 전환 (기존 확정 스타일)
- 부분 매칭 시 노란 도트 + 프로그레스 텍스트
- aria-live="polite"로 진행률 변경 시 스크린리더 알림

### 확정 후 자동 흐름

1. 확정 버튼 클릭 → 버튼 스피너 + disabled
2. API 성공 → "✓ 설치 매칭 완료" 토스트
3. 0.3초 후 다음 미매칭 항목 자동 선택 → 후보 자동 갱신
4. 모든 항목 완료 시 → "전체 매칭 완료!" 토스트 + 메시지 녹색 전환
5. API 실패 → "매칭 확정에 실패했습니다" 에러 토스트 + 항목 상태 롤백

### 키보드 단축키

기존 단축키 유지. 개별 매칭 모드에서:
- `Tab`: 다음 미매칭 항목으로 이동
- `Enter`: 선택된 후보로 현재 항목 확정
- `Arrow ↑↓`: 후보 리스트 내 이동
- `Escape`: 항목 선택 해제
- `Arrow ←→`: shadcn Tabs 탭 전환 (내장)

### 인터랙션 상태 테이블

| 기능 | LOADING | EMPTY | ERROR | SUCCESS | PARTIAL |
|------|---------|-------|-------|---------|---------|
| 항목별 후보 검색 | 후보 영역 스켈레톤 3줄 | "이 금액(X원)에 맞는 거래를 찾지 못했습니다" + 직접 검색 버튼 | "후보 검색 중 오류" + 재시도 | 후보 리스트 표시 | N/A |
| 항목 확정 처리 | 확정 버튼 스피너 + disabled | N/A | 에러 토스트 + 상태 롤백 | ✓ 확정 + 자동 다음 이동 | N/A |
| 메시지 진행률 | N/A | N/A | N/A | "3/3 매칭" 녹색 | "2/3 매칭" 노란 Badge + 노란 도트 |
| 합계 불일치 | N/A | N/A | 노란 경고 배너 | N/A | N/A |

## 엣지 케이스

1. **items 합계 ≠ total_amount**: 경고 배너 표시, 매칭은 허용 (파싱 오류 가능성 알림)
2. **같은 거래에 여러 항목 매칭 시도**: 허용하지 않음. 이미 매칭된 거래는 후보에서 제외.
3. **개별 매칭 중 전체 매칭으로 전환**: 이미 확정된 개별 항목이 있으면 전체 매칭 탭 비활성화 + "개별 매칭이 진행 중입니다" 안내.
4. **전체 매칭 확정 후 개별 매칭 시도**: 전체 매칭이 확정되면 개별 매칭 탭 비활성화.
5. **items가 1개인 메시지**: 탭 미표시. 기존 전체 매칭만.
6. **structured_data 없는 메시지**: 개별 매칭 불가. 기존 동작만.
7. **같은 금액 항목 여러 개**: 허용. 이미 매칭된 거래만 후보에서 제외하면 자연 해결.
8. **부분 매칭 상태에서 메시지 무시**: 경고 다이얼로그 "N개 항목이 매칭됨. 무시하면 매칭도 해제됩니다. 계속?" → 확인 시 매칭 레코드 삭제 + is_cancelled=true.
9. **개별 매칭 확정 취소**: 확정된 항목 옆 "취소" 링크 → DELETE API → 미매칭으로 복귀 + is_completed 재계산.

## 테스트

### 백엔드
- 개별 항목 매칭 확정 → item_index 저장 확인
- 모든 항목 완료 시 is_completed=true 전환 확인
- 부분 매칭 상태에서 is_completed=false 유지 확인
- 중복 (message_id, item_index) 매칭 시 409 에러 확인
- item_index 파라미터로 후보 검색 시 해당 금액만 사용 확인
- 이미 매칭된 거래가 다른 항목 후보에서 제외 확인
- 기존 1:1 매칭 (item_index=NULL) 하위호환 확인
- 개별 매칭 확정 취소(DELETE) → 레코드 삭제 + is_completed 재계산
- 부분 매칭 상태에서 무시 → 매칭 레코드 전체 삭제 + is_cancelled=true

### 프론트엔드
- items ≥ 2 메시지에서 탭 표시 (전체 매칭 / 개별 매칭)
- items < 2 메시지에서 탭 미표시
- 항목 클릭 → 후보 갱신 → 확정 플로우
- 확정 후 자동 다음 미매칭 항목 이동
- 매칭 진행률 표시 (2/3 항목 매칭)
- 전체 완료 시 녹색 전환 + 토스트
- 확정 취소 → 미매칭 복귀
- 전체/개별 탭 상호 비활성화
- 로딩/Empty/에러 상태 처리
- 키보드 단축키 (Tab, Enter, Arrow, Escape)

## NOT in scope

- 자동 매칭 배치 (고신뢰도 자동 확정) — 별도 피처로 구현
- 직접 검색 기능 — Phase 2에서 추가
- 모바일 반응형 — 데스크탑 전용 내부 도구
- 개별 항목별 confidence 점수 집계 — 현재 항목 단위 점수면 충분

## What already exists

- shadcn/ui Badge, Button, Card, Skeleton, Tabs 컴포넌트
- `formatKRW()`, `getConfidenceBadge()` 헬퍼
- `nameColor()` 해시 기반 색상
- 두 패널 레이아웃 (왼쪽 메시지 + 오른쪽 후보)
- 후보 카드 디자인 (날짜, 거래처, 금액, confidence)
- 키보드 단축키 (j/k/i/Enter)
- 토스트 알림 (sonner)

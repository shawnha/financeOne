# 내부계정 재매핑 + 예상 현금흐름 개선 — 설계 스펙

**날짜:** 2026-03-31
**작성자:** brainstorming session
**상태:** DRAFT

---

## 1. 목적

한아원코리아의 자금 운용 예측 정확도를 높이기 위해:
1. 거래내역의 내부계정 매핑을 재정비 (Slack + mapping_rules 기반)
2. 예상 현금흐름에서 고정비 자동 입력, 날짜 기반 그래프, 카드별 시차 보정 구현
3. 데이터가 쌓일수록 예측이 정확해지는 학습 루프 구축 (4월 목표: 정확한 예측)

## 2. 영역 A: 내부계정 재매핑

### 2.1 매핑 범위
- **전체 재검토**: 모든 거래를 대상으로 하되, 수동 매핑(`mapping_source='manual'`)은 유지
- 대상 법인: 한아원코리아 (entity_id=2)

### 2.2 매핑 전략: 하이브리드 (소스별 다른 접근)

**카드 거래 (lotte_card, woori_card):**
- 기존 `mapping_rules` 기반 자동 매핑 유지
- 미매핑 거래처는 Slack `parsed_structured`의 item_description 참고하여 내부계정 추론
- 현황: 647/671건 매핑 완료, ~24건 미매핑

**은행 거래 (woori_bank):**
- Slack 매칭 결과의 item_description + 거래처명 조합으로 내부계정 결정
- 정기 항목(급여, 임차료, 세금)은 거래처 패턴으로 자동 매핑
- 현황: 76건 매핑 완료, ~16건 미매핑

**매핑 우선순위 (워터폴):**
1. `mapping_source='manual'` → 유지 (건드리지 않음)
2. `mapping_rules` 매치 (confidence >= 0.8) → 적용
3. Slack `parsed_structured` item_description 매치 → 적용
4. 매치 없음 → 미매핑 유지 (수동 처리 대상)

**재매핑 배치 안전성:**
- DB 트랜잭션 내에서 실행 (실패 시 전체 롤백)
- 멱등성 보장: 재실행해도 동일 결과
- dry-run 모드 제공: 실제 변경 없이 매핑 결과만 미리 확인

### 2.3 없는 내부계정 자동 생성
- 기존 트리 구조 유지 (EXP-093 마트약국, EXP-094 한아원리테일, EXP-100 ODD, EXP-102 YUNE)
- 하위 항목만 추가 (팀별 분리 유지)
- 팀 분류: Slack sender_name / member_id 기반

### 2.4 매핑 학습
- 수동 변경 시 `mapping_rules`에 UPSERT (기존 `learn_mapping_rule` 활용)
- 표준계정 미연결 시 매핑 규칙 저장 건너뜀 (이미 수정 완료)

## 3. 영역 B: 예상 현금흐름 개선

### 3.1 DB 변경

**forecasts 테이블 확장:**
```sql
ALTER TABLE forecasts ADD COLUMN expected_day INTEGER; -- 1~31, 예상 지출/수입일 (31일 지정 시 해당 월 말일로 처리)
ALTER TABLE forecasts ADD COLUMN is_fixed BOOLEAN DEFAULT false; -- 고정비 여부
ALTER TABLE forecasts ADD COLUMN payment_method TEXT DEFAULT 'bank'; -- 'bank' | 'card' (이중 차감 방지)
```

**card_settings 초기 데이터:**
```sql
INSERT INTO card_settings (entity_id, card_name, source_type, payment_day)
VALUES
  (2, '롯데카드', 'lotte_card', 15),
  (2, '우리카드', 'woori_card', 25);
```
- card_settings에 `statement_day` 추가 (롯데=2, 우리=16) — 향후 명세서 검증용
- card_settings에 `billing_start_day` 추가 (롯데=null/월단위, 우리=11) — 향후 기간 정밀화용
- 현재는 카드별 월 단위로 계산 (우리카드 11-10일 기간은 향후 조정, `billing_start_day` 변경만으로 반영 가능)

### 3.2 카드별 시차보정

**데이터 소스: 이용/승인 내역만 사용 (일원화)**
- 명세서는 향후 검증용 (사용액 = 선결제 + 명세서 금액)
- 선결제는 은행 거래로 자연 처리 → 별도 로직 불필요

**카드 정보:**

| 카드 | 결제일 | 명세서 | 현재 기간 계산 | 비고 |
|------|--------|--------|---------------|------|
| 롯데카드 | 15일 | 2일 | 월 단위 | 12월 이용액 → 1/15 결제 |
| 우리카드 | 25일 | 16일 | 월 단위 (향후 11-10일 조정 가능) | 12월 이용액 → 1/25 결제 |
| 우리체크카드 | 즉시 | - | 해당 없음 | 시차보정 제외 (은행 거래로 이미 반영) |

**우리체크카드 제외 처리:**
- 은행 거래내역에서 "체크우리"로 구분 가능
- 카드 이용/승인 내역(woori_card)에서 체크카드 건 필터링 필요
- 방법: 은행 거래내역에서 "체크우리"로 구분 가능. 카드 이용/승인 내역에서는 `card_number` 또는 `description` 패턴으로 구분 (구현 시 데이터 확인하여 결정)
- 구현 전 필수: 우리카드 이용/승인 데이터에서 체크카드 건의 구분 필드 확인

**시차보정 공식 (카드별 분리):**
```python
# 기존 합산 → 카드별 분리
롯데_결제예상 = get_card_net(conn, entity_id, prev_year, prev_month, 'lotte_card')
우리_결제예상 = get_card_net(conn, entity_id, prev_year, prev_month, 'woori_card')
# 우리체크카드는 woori_card에서 필터링하여 제외

card_usage = 롯데_결제예상 + 우리_결제예상

# 시차보정 (카드별)
롯데_timing = 롯데_전월이용액 - 롯데_당월예상
우리_timing = 우리_전월이용액 - 우리_당월예상
timing_adj = 롯데_timing + 우리_timing
```

**forecast_closing 공식: 변경 없음**
```python
forecast_closing = opening + income - expense - card_usage + timing_adj
```

### 3.3 카드 결제 항목과 forecast의 관계 (이중 차감 방지)

**핵심 원칙:** 카드로 결제하는 항목(식비, 교통비 등)은 forecast에서 **추적용**이며, 잔고 계산에는 card_usage(이용/승인 기반)로만 차감.

**구현 방식:**
- forecast 항목에 `payment_method` 필드 추가 ('bank' | 'card')
- `payment_method = 'card'` 항목은 `forecast_expense`에 포함하지 않음 → 이중 차감 방지
- `payment_method`는 내부계정의 특성에 따라 자동 설정 (식비/교통/구독 등 카드 결제 계정은 'card', 임차료/급여 등은 'bank')
- 카드 결제 항목의 역할:
  - 내부계정별 지출 추적 (어디에 얼마)
  - 다음 달 카드 예상 사용액 산출 기초
  - 예상 vs 실적 비교 (학습)
- 잔고 차감: bank 항목은 forecast_expense로, card 항목은 card_usage(이용/승인 전월 합산)로만 처리

### 3.4 고정비 자동 생성

**대상:** `is_fixed = true` 항목
**자동 생성 시점:** 다음 달 forecast 생성 시 (copy-recurring 확장 또는 별도 API)
**금액 제안:** 전월 실적 그대로 (사용자 수정 가능)
**향후 개선 (Phase 4+):** AI가 축적된 데이터를 분석하여 최적의 예측 방식을 판단 (NotebookLM + Obsidian 워크플로우 활용). 단순 평균이 아닌 AI 기반 학습.

**첫 달 부트스트랩 (12월 → 1월):**
- 12월 거래내역 분석하여 고정비 항목과 금액을 초기 seed로 수동 등록
- 기존 `suggest-from-actuals` API 참고하되, `is_fixed` + `expected_day` 추가하여 등록

**한아원코리아 고정비 초기 seed:**

| 항목 | 금액 | 예상일 | 내부계정 |
|------|------|--------|---------|
| 급여 | 29,263,090 | 24일 | EXP-010-001 |
| 임차료 (스파크플러스) | 891,000 | 2일 | EXP-020-001 |
| 임차료 (기업정인자산) | 8,816,940 | 24일 | EXP-020-001 |
| 4대보험 (국민연금+건강+고용) | 4,282,720 | 10일 | EXP-080 |
| 원천세 | 1,004,270 | 3일 | EXP-080 |
| 사무실 청소 | 386,800 | 24일 | EXP-092-003 |

### 3.5 그래프 개선

**일별 시뮬레이션 변경:**
```
기존: 수입/지출 균등 분배 + 15일/25일 4x 스파이크

개선:
- day N (expected_day 지정, payment_method='bank'): 해당 금액 차감/추가
- day 15: 롯데카드 결제예상액 차감 (이용/승인 기반)
- day 25: 우리카드 결제예상액 차감 (이용/승인 기반)
- payment_method='card' 항목: 그래프에서 개별 차감 안함 (card_usage에 이미 포함)
- 나머지 (날짜 없는 bank 항목): 균등 분배

엣지 케이스:
- expected_day=31 & 해당 월 30일까지 → 말일(30일)로 처리
- expected_day=29,30,31 & 2월 → 28일(또는 29일)로 처리
```

**그래프 마커:**
- 카드 결제일: ReferenceLine (롯데=빨강 15일, 우리=파랑 25일)
- 고정비 (expected_day 지정): ReferenceDot + 라벨
- 라벨 글자 짤림 수정: 폰트 축소 또는 약칭 사용

**경고선:**
- 설정 가능한 최소 잔고선 (기본: 0원, 사용자 설정 가능)
- 예상 잔고가 경고선 아래로 내려가면:
  - 그래프에 빨간 영역 표시
  - 상단 경고 배너: "X월 Y일경 잔고 부족 예상 (예상 잔고: Z원)"
- **예정 지출 > 잔고 경고:** 특정 날짜의 예정 지출이 해당 시점 잔고보다 클 때도 경고
  - 예: "24일 급여(29,263,090) 지출 예정이나 예상 잔고 15,000,000원 — 14,263,090원 부족"

### 3.6 데이터 입력 흐름

**수시 + 월말 업로드:**
- 은행 거래내역 (우리은행)
- 카드 이용/승인 내역 (롯데/우리) — 기존 파서 사용

**Forecast → Actual → Learn 루프:**
1. 예상 설정: 고정비 자동 생성(전월 실적) + 변동비 수동 입력 + 카드 시차보정
2. 실적 업로드: 은행/카드 수시 업로드 → 내부계정 매핑
3. 비교 + 학습: 내부계정별 예상 vs 실적 → 다음 달 고정비 자동 조정

**목표:** 12월→1월→2월→3월 학습 후, 4월 예상은 카테고리별로 정확

## 4. 스코프 요약

### 포함

| 항목 | 내용 |
|------|------|
| 내부계정 재매핑 | 하이브리드 (거래처패턴 + Slack), 전체 재검토, 없는 계정 자동 생성 |
| forecasts 확장 | expected_day + is_fixed + payment_method 추가 |
| 고정비 자동 생성 | 전월 실적 기반, 수정 가능, 초기 seed 등록 |
| 카드별 시차보정 | 이용/승인 기반, 카드별 분리, 우리체크 제외 |
| 그래프 개선 | 날짜 기반 + 카드별 결제일 + 고정비 마커 + 글자 짤림 수정 |
| 경고 시스템 | 최소 잔고선 + 지출 초과 경고 |
| card_settings 초기화 | 롯데(결제15일), 우리(결제25일) |

### 제외

| 항목 | 이유 |
|------|------|
| 명세서 파서 | 향후 검증용으로 추가 |
| 선결제 별도 처리 | 은행 거래로 자연 처리 |
| 우리카드 11-10일 정밀 기간 | 월 단위로 시작, card_settings에서 날짜 변경만으로 향후 조정 가능 |
| 내부계정 → 표준계정 매핑 | 별도 리뷰 후 진행 |
| NotebookLM / 옵시디언 연동 | Phase 4+ |
| AI 기반 학습 공식 최적화 | Phase 4+ (NotebookLM + Obsidian 워크플로우), 현재는 전월 실적 그대로 |

## 5. 기존 코드 활용

| 기존 코드 | 활용 방식 |
|-----------|----------|
| `mapping_rules` + `learn_mapping_rule` | 재매핑 시 그대로 사용 |
| `auto_map_transaction` | 재매핑 배치에서 호출 |
| `calc_forecast_closing` | 공식 변경 없음 |
| `calc_card_timing_adjustment` | 카드별 분리로 확장 |
| `get_card_total_net` | 카드별 + source_type 파라미터 추가 |
| `suggest-from-actuals` API | 부트스트랩 참고 |
| `copy-recurring` API | 고정비 자동 생성 확장 |
| `card_settings` 테이블 | 비어있음 → 초기 데이터 삽입 |
| 카드 파서 (lotte_card, woori_card) | 이용/승인 업로드에 그대로 사용 |

# 거래 → 내부계정 자동 매핑 + 학습 설계

## 개요
거래 업로드 시 counterparty(거래처) 기반으로 내부계정을 자동 매핑하고, 사용자가 수정한 매핑을 학습하여 다음 거래부터 자동 적용하는 시스템.

## 범위
1. 업로드 시 자동 매핑 (mapping_rules 조회)
2. 사용자 수정 시 학습 (mapping_rules UPSERT)
3. 매핑룰 관리 페이지 (CRUD)

---

## 1. 업로드 시 자동 매핑

### 동작
- 거래 INSERT 직후, counterparty로 mapping_rules 정확 일치 조회
- 매칭 조건: `entity_id` 일치 + `counterparty_pattern` = `counterparty` (exact match) + `confidence >= 0.8`
- 매칭 시: `internal_account_id`, `standard_account_id`, `mapping_source='rule'`, `mapping_confidence` 자동 설정
- 미매칭 시: 미분류 상태 (internal_account_id = NULL)

### 위치
- `backend/routers/upload.py` — 기존 거래 INSERT 루프 내에서 mapping_rules 조회 추가
- 재매칭 API (`POST /upload/file/{file_id}/rematch`)에도 동일 로직 이미 존재 → 공통 함수로 추출

### 쿼리
```sql
SELECT internal_account_id, standard_account_id, confidence
FROM mapping_rules
WHERE entity_id = %s AND counterparty_pattern = %s AND confidence >= 0.8
ORDER BY confidence DESC, hit_count DESC
LIMIT 1
```

---

## 2. 사용자 수정 시 학습

### 동작
- 거래내역에서 내부계정 선택 즉시 (AccountCombobox onChange) → PATCH /transactions/{id} 호출
- 백엔드에서 internal_account_id 변경 감지 시 mapping_rules UPSERT

### UPSERT 로직
```
IF 같은 (entity_id, counterparty_pattern)의 룰이 존재:
  IF 같은 internal_account_id:
    hit_count += 1
    confidence = min(1.0, confidence + 0.05)
  ELSE (다른 계정으로 변경):
    internal_account_id = 새 값
    standard_account_id = 내부계정의 표준계정 (internal_accounts.standard_account_id)
    confidence = 0.8
    hit_count = 1
ELSE:
  INSERT 새 룰 (confidence=0.8, hit_count=1)
```

### 위치
- `backend/routers/transactions.py` — PATCH /{tx_id} 핸들러에 학습 로직 추가
- counterparty가 NULL인 거래는 학습 스킵

### standard_account_id 자동 설정
- 사용자가 내부계정만 선택해도, 해당 내부계정에 연결된 표준계정을 자동으로 mapping_rules와 거래에 모두 설정
- 쿼리: `SELECT standard_account_id FROM internal_accounts WHERE id = %s`

---

## 3. 매핑룰 관리 페이지

### 경로
- `/accounts/mapping-rules`
- 사이드바: "계정 관리" 그룹 아래 "매핑 규칙" 메뉴 추가

### API
- `GET /api/accounts/mapping-rules?entity_id=` — 목록 조회 (페이지네이션, 검색)
- `PATCH /api/accounts/mapping-rules/{id}` — 수정 (internal_account_id 변경)
- `DELETE /api/accounts/mapping-rules/{id}` — 삭제

### UI
- 테이블 컬럼: 거래처 패턴 | 내부계정 | 표준계정 | 신뢰도 | 적용 횟수 | 수정일
- 내부계정 셀: 클릭하면 AccountCombobox로 인라인 수정 (거래내역과 동일 UX)
- 삭제: 행 우측 삭제 버튼 (확인 다이얼로그)
- 검색: 거래처 패턴 텍스트 검색
- 정렬: hit_count DESC (많이 쓰인 룰 먼저)

---

## 기존 코드 변경

### upload.py
- 거래 INSERT 루프에 auto_map_transaction() 호출 추가
- rematch 로직과 공통 함수 추출 → `backend/services/mapping_service.py`

### transactions.py
- PATCH 핸들러에 learn_mapping_rule() 호출 추가
- internal_account_id 변경 시에만 학습 트리거

### sidebar.tsx
- "계정 관리" 그룹에 "매핑 규칙" 메뉴 추가

---

## DB 변경
- 없음. mapping_rules 테이블 이미 존재 (schema.sql #13)
- standard_account_id는 NOT NULL — 내부계정 선택 시 해당 내부계정의 standard_account_id를 자동으로 가져와서 함께 저장하므로 제약 변경 불필요

---

## 접근 방식
- 매핑 전략: 정확 일치 (exact match) — 1단계
- 학습 시점: 계정 선택 즉시 (confirm 불필요)
- 향후 확장: 데이터 충분히 쌓이면 Claude API 기반 유사 거래처 추천 (2단계, 별도 설계)

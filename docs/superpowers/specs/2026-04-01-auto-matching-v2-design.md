# 내부계정 자동 매칭 고도화 설계

> 승인일: 2026-04-01
> 상태: 승인됨

## 개요

기존 거래처 정확 일치 + 학습 시스템(mapping_service.py)을 확장하여:
1. 유사/퍼지 매칭 (거래처명 + 설명)
2. AI 기반 계정 추천 (하이브리드)
3. 새 내부계정 추가 시 표준계정 자동 추천

## 기능 1: 거래 → 내부계정 매칭 (하이브리드)

### 처리 흐름 (순서 필수)

```
1. 정확 일치 → 2. 유사 매칭 → 3. 키워드 규칙 → 4. Claude AI → 5. 수동
```

| 단계 | 방식 | 속도 | 비용 |
|------|------|------|------|
| 1. 정확 일치 | mapping_rules counterparty 정확 매칭 (기존) | 0.01초 | 무료 |
| 2. 유사 매칭 | counterparty + description 유사도 (pg_trgm similarity) | 0.05초 | 무료 |
| 3. 키워드 규칙 | description 키워드 패턴 매칭 | 0.01초 | 무료 |
| 4. Claude AI | 거래 정보 + 내부계정 목록 → 추천 + 학습 저장 | 1~3초 | API |
| 5. 수동 | 미분류 → 사용자 선택 → mapping_rules 학습 | - | - |

### 유사 매칭 범위 (선택: B)
- 거래처명 + 설명(description) 결합
- PostgreSQL `pg_trgm` 확장 사용
- similarity threshold: 0.3 이상

### AI fallback
- CLAUDE.md 원칙: "mapping_rules 테이블 우선 조회 후 Claude API 호출"
- AI 추천 결과는 mapping_rules에 자동 학습 (match_type='ai')
- 다음 동일 거래처는 로컬에서 즉시 처리

## 기능 2: 내부계정 → 표준계정 추천

### 처리 흐름

```
1. 상위계정 상속 → 2. 동일 법인 유사계정 참조 → 3. 일상어 사전 → 4. Claude AI
```

| 단계 | 설명 |
|------|------|
| 1. 상위계정 상속 | parent의 standard_account_id 상속 |
| 2. 동일 법인 유사계정 | 같은 entity의 유사 이름 계정 standard_account_id 참조 |
| 3. 일상어 사전 | 내장 키워드→표준계정 매핑 (회식→복리후생비, 택시→여비교통비 등) |
| 4. Claude AI | 내부계정 이름 + 카테고리 → 표준계정 추천 |

### 적용 시점
- 새 내부계정 생성 시 즉시 추천
- 기존 내부계정 중 standard_account_id가 NULL인 것 일괄 백필

## UX: 매칭 결과 표시 (선택: B)

### 모두 자동 적용 + 출처 표시 + 일괄 확정

- 매칭된 것은 모두 자동 적용 (is_confirmed=false)
- 출처 뱃지 색상:
  - 규칙(exact): 초록 `규칙 95%`
  - 유사(similar): 파랑 `유사 82%`
  - AI: 보라 `AI 72%`
  - 미분류: 회색
- "AI 매칭 N건 일괄 확정" 버튼
- 수동 변경 시 mapping_rules 자동 학습

## DB 스키마 변경

```sql
-- mapping_rules 확장
ALTER TABLE mapping_rules ADD COLUMN match_type varchar(20) DEFAULT 'exact';
-- 'exact' | 'similar' | 'keyword' | 'ai'

-- pg_trgm 확장 활성화
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 유사도 인덱스
CREATE INDEX idx_mapping_rules_trgm
  ON mapping_rules USING gin (counterparty_pattern gin_trgm_ops);

-- 키워드 규칙 테이블
CREATE TABLE keyword_mapping_rules (
  id serial PRIMARY KEY,
  entity_id int REFERENCES entities(id),
  keyword varchar(100) NOT NULL,
  match_field varchar(20) DEFAULT 'description',
  internal_account_id int REFERENCES internal_accounts(id),
  confidence numeric(3,2) DEFAULT 0.75
);

-- 일상어 → 표준계정 매핑 사전
CREATE TABLE standard_account_keywords (
  id serial PRIMARY KEY,
  keyword varchar(100) NOT NULL,
  standard_account_id int REFERENCES standard_accounts(id),
  confidence numeric(3,2) DEFAULT 0.80
);
```

## 구현 순서 (추천)

1. DB 마이그레이션 (pg_trgm, 테이블 생성)
2. mapping_service.py 확장 (유사 매칭 + 키워드 규칙)
3. Claude AI fallback 연동
4. 표준계정 추천 서비스
5. 프론트: 출처 뱃지 + 일괄 확정 UI
6. 기존 데이터 백필

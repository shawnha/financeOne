# Implementation Plan: Supabase Migration + Backend Refactoring

Date: 2026-03-26
Spec: `docs/superpowers/specs/2026-03-26-supabase-migration-design.md`
Branch: `deploy-production`
Supabase Project ID: `apfdwvvmsrvunuahlvae`
Schema: `financeone`

---

## Pre-requisites (수동)

1. Supabase Dashboard에서 `financeone` 스키마 생성:
   ```sql
   CREATE SCHEMA IF NOT EXISTS financeone;
   ```
2. Supabase connection string 확보:
   - Dashboard → Project Settings → Database → Connection string (Transaction pooler)
   - 형식: `postgresql://postgres.[project-ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres`

---

## Block 1: DB 연결 전환 (Task 1-2)

### 1.1 connection.py 수정
- [ ] `DATABASE_URL` → Supabase pooler URL
- [ ] `get_db()` 에서 `SET search_path TO financeone, public` 실행
- [ ] silent rollback `except Exception: pass` → 로깅 추가
- [ ] `.env.example` 업데이트 (Supabase URL 형식)

### 1.2 스키마 마이그레이션
- [ ] `schema.sql` 상단에 `CREATE SCHEMA IF NOT EXISTS financeone; SET search_path TO financeone;`
- [ ] `financial_statements` 테이블에 `base_currency TEXT DEFAULT 'KRW'` 컬럼 추가
- [ ] `transactions(file_id)` 인덱스 추가
- [ ] `forecasts` UNIQUE 제약에서 NULL subcategory 처리
- [ ] Supabase SQL Editor에서 스키마 실행
- [ ] 기존 Neon 데이터 → Supabase 이관 (pg_dump → psql 또는 수동 re-upload)

### 1.3 검증
- [ ] `.env`에 Supabase URL 설정
- [ ] `pytest backend/tests/ -v` → 70 passed
- [ ] 서버 기동 → `curl /health` + `curl /api/entities`

**커밋:** `feat: migrate DB from Neon to Supabase (financeone schema)`

---

## Block 2: 쿼리 최적화 (Task 3)

### 2.1 EXTRACT → range 변환
- [ ] `backend/utils/__init__.py` 생성
- [ ] `backend/utils/db.py` — `fetch_all()`, `build_date_range()` 유틸
- [ ] `cashflow_service.py` — 4개 쿼리 변환 (`get_bank_transactions`, `get_card_transactions`, `get_card_total_net`, `get_forecast_cashflow` 내 actual 쿼리)
- [ ] `backend/routers/dashboard.py` — KPI/차트 쿼리 변환
- [ ] cashflow 라우터의 card-expense 내부 쿼리 변환

### 2.2 fetch_all 적용
- [ ] 20+ 위치의 `cols = [d[0]...]; rows = [dict(zip...)]` → `fetch_all(cur)` 교체
- [ ] Grep으로 전수 확인

### 2.3 검증
- [ ] `pytest` → 70 passed
- [ ] 서버 기동 → cashflow API 응답 동일 확인

**커밋:** `refactor: EXTRACT→range queries + fetch_all utility`

---

## Block 3: statement_generator 분리 (Task 4)

### 3.1 디렉토리 구조
- [ ] `backend/services/statements/` 디렉토리 생성
- [ ] `__init__.py` — 기존 import 경로 유지 위한 re-export
- [ ] `helpers.py` — `_build_items()`, `_classify_account()`, `_quantize()` 등 공용 함수
- [ ] `balance_sheet.py` — `generate_balance_sheet()`
- [ ] `income_statement.py` — `generate_income_statement()`
- [ ] `cash_flow.py` — `generate_cash_flow_statement()`
- [ ] `trial_balance.py` — `generate_trial_balance()`
- [ ] `deficit.py` — `generate_deficit_treatment()`
- [ ] `consolidated.py` — `generate_consolidated_statements()` + `generate_all_statements()`

### 3.2 호환성
- [ ] `backend/services/statement_generator.py` → deprecated wrapper (import from statements/)
  ```python
  # Deprecated: import from backend.services.statements instead
  from backend.services.statements import *
  ```
- [ ] 기존 import 사용처 (routers/statements.py, tests/) 검증

### 3.3 검증
- [ ] `pytest backend/tests/test_phase2_statements.py -v` → 7 passed
- [ ] `pytest backend/tests/test_phase3_consolidation.py -v` → 5 passed

**커밋:** `refactor: split statement_generator.py (1074→6 modules)`

---

## Block 4: upload.py + 하드코딩 제거 (Task 5-6)

### 4.1 upload dedup 리팩토링
- [ ] `backend/services/dedup_service.py` — O(1) set 기반 중복 체크
- [ ] `upload.py`에서 dedup 로직 추출, 서비스 호출로 교체
- [ ] upload.py 목표: ~200줄

### 4.2 하드코딩 → DB 설정
- [ ] `notes.py` — `ENTITIES` dict → DB entities 테이블 조회
- [ ] `mercury.py` — `HOI_ENTITY_ID = 1` → settings 테이블 또는 env
- [ ] `bookkeeping_engine.py` — `CASH_ACCOUNT_CODE` → settings 테이블
- [ ] `cta_service.py` — `EQUITY_INCEPTION_DATE` → settings 테이블
- [ ] `main.py` — 버전 하드코딩 → `importlib.metadata` 또는 VERSION 파일

### 4.3 검증
- [ ] `pytest` → all passed
- [ ] upload API 테스트 (실제 Excel 파일)

**커밋:** `refactor: upload dedup O(n²)→O(1) + remove hardcoded values`

---

## Block 5: 통합 테스트 + 에러 핸들링 (Task 7-9)

### 5.1 API 통합 테스트
- [ ] `backend/tests/test_api_integration.py` 생성
- [ ] FastAPI TestClient 설정 (Supabase 연결)
- [ ] 주요 엔드포인트 7~10개 테스트
- [ ] 에러 케이스 테스트 (잘못된 entity_id, 빈 파일 업로드 등)

### 5.2 에러 핸들링 추가
- [ ] `dashboard.py` — try/except + 구체적 에러 메시지
- [ ] `cashflow.py` 라우터 — try/except
- [ ] `intercompany.py` DELETE — rollback 추가
- [ ] 파서 `except Exception: continue` → 로깅 추가

### 5.3 응답 표준화
- [ ] CRUD 응답 패턴 통일: `{"id": N, "status": "verb"}`
- [ ] 에러 응답: `{"detail": "메시지", "code": "ERROR_CODE"}`

### 5.4 검증
- [ ] `pytest` → 70 + 새 통합 테스트 전부 passed
- [ ] 프론트엔드 빌드 + 서버 기동 → 3탭 cashflow 동작 확인

**커밋:** `test: API integration tests + error handling standardization`

---

## Block 6: 최종 검증 + 정리

- [ ] 전체 `pytest` → ALL PASS
- [ ] 프론트엔드 `next build` → 성공
- [ ] 서버 기동 + browse 테스트 (cashflow 3탭)
- [ ] CHANGELOG.md 업데이트
- [ ] CLAUDE.md DB 섹션 업데이트 (Neon → Supabase)

**커밋:** `chore: finalize Supabase migration + update docs`

---

## 실행 요약

```
Block 1 (DB 연결 + 스키마)     ~20min
Block 2 (쿼리 최적화 + 유틸)   ~15min
Block 3 (statement 분리)       ~25min
Block 4 (upload + 하드코딩)     ~15min
Block 5 (통합 테스트 + 에러)    ~25min
Block 6 (최종 검증)             ~10min
─────────────────────────────────
총: ~2시간 (CC 기준)
```

## 주의사항

1. **Supabase connection string**은 `.env`에만 — 절대 커밋 금지
2. **데이터 이관**: 기존 Neon 데이터를 Supabase로 옮기는 건 Block 1에서 수동 처리
3. **프론트엔드 변경 없음** — API 인터페이스 동일 유지
4. **기존 테스트 70개 항상 통과** — 블록마다 검증

# Supabase Migration + Backend Refactoring

Date: 2026-03-26
Branch: deploy-production
Status: APPROVED (eng review embedded)

## Problem

FinanceOne은 Neon PostgreSQL을 사용 중. hanahone-erp와 통합하기 위해 Supabase로 전환하면서, 아키텍처 리뷰에서 발견된 기술부채를 함께 해소한다.

## Target

- Supabase 프로젝트 ID: `apfdwvvmsrvunuahlvae` (hanahone-erp 공유)
- 스키마: `financeone` (별도 스키마, public과 분리)
- 기존 psycopg2 + raw SQL 유지 (ORM 도입 안 함)

---

## Task 1: DB 연결 전환 (connection.py + .env)

**변경:**
- `DATABASE_URL` → Supabase pooler URL (transaction mode)
- `connection.py`: pool 초기화 시 `search_path = financeone` 설정
- Supavisor가 connection pooling 관리 → idle timeout 문제 해결

**connection.py 변경 사항:**
```python
# Pool 초기화 후 각 connection에 search_path 설정
def get_db():
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")
        cur.close()
        yield conn
    finally:
        conn.rollback()  # safety net
        pool.putconn(conn)
```

**검증:** 기존 70 pytest + curl API 테스트 전부 통과

---

## Task 2: 스키마 마이그레이션 (schema.sql)

**변경:**
- `CREATE SCHEMA IF NOT EXISTS financeone;`
- `SET search_path TO financeone;`
- 21개 테이블 그대로 (구조 변경 없음)
- **버그 수정:** `financial_statements`에 `base_currency` 컬럼 추가

**인덱스 개선:**
- `transactions(file_id)` — upload dedup 쿼리용
- `transactions(entity_id, date)` — cashflow range 쿼리 최적화 (EXTRACT 대신 range 사용)

**forecasts UNIQUE 제약 수정:**
- `subcategory` NULL 처리: `COALESCE(subcategory, '')` 사용하거나 `NULLS NOT DISTINCT` (PG15+)

---

## Task 3: EXTRACT → range 쿼리 변환

**현재 (비효율):**
```sql
WHERE EXTRACT(YEAR FROM date) = 2025 AND EXTRACT(MONTH FROM date) = 12
```

**변경 (인덱스 활용):**
```sql
WHERE date >= '2025-12-01' AND date < '2026-01-01'
```

**영향 파일:** cashflow_service.py, dashboard.py, cashflow.py (card-expense)

---

## Task 4: statement_generator.py 분리 (1074줄 → 6 모듈)

```
backend/services/statements/
├── __init__.py          — public API re-export
├── balance_sheet.py     — generate_balance_sheet()
├── income_statement.py  — generate_income_statement()
├── cash_flow.py         — generate_cash_flow_statement()
├── trial_balance.py     — generate_trial_balance()
├── deficit.py           — generate_deficit_treatment()
├── consolidated.py      — generate_consolidated_statements()
└── helpers.py           — _build_items(), _classify_account(), _quantize()
```

**기존 import 경로 유지:** `from backend.services.statement_generator import ...` → `__init__.py`에서 re-export

---

## Task 5: upload.py 리팩토링 (365줄, O(n^2) 제거)

**변경:**
- 중복체크: `parsed.index(tx)` → `seen = set()` 으로 O(1) lookup
- dedup 로직을 `services/dedup_service.py`로 추출
- upload.py → ~200줄로 감소

---

## Task 6: 하드코딩 → 설정 테이블

**새 테이블:** `financeone.app_settings`
```sql
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**이전할 하드코딩:**
| 현재 | 키 | 값 |
|------|-----|-----|
| `HOI_ENTITY_ID = 1` | `hoi_entity_id` | `1` |
| `CASH_ACCOUNT_CODE = "10100"` | `cash_account_code` | `"10100"` |
| `EQUITY_INCEPTION_DATE` | `equity_inception_date` | `"2023-01-01"` |
| `ENTITIES = {1:..}` (notes.py) | DB entities 테이블에서 직접 조회 | — |

---

## Task 7: API 통합 테스트

**새 파일:** `backend/tests/test_api_integration.py`

FastAPI TestClient로 주요 엔드포인트 테스트:
- `GET /api/entities` — 200 + 3개 법인
- `GET /api/cashflow/summary` — 200 + months 배열
- `GET /api/cashflow/actual` — 200 + rows 배열
- `POST /api/forecasts` — 201 + UPSERT
- `GET /api/dashboard` — 200 + KPI 구조
- `POST /api/upload` — 400 (빈 파일)
- `GET /api/statements` — 200

**주의:** 실제 DB (Supabase) 사용 — 테스트 데이터 정리 필요

---

## Task 8: DRY 개선 — 공통 유틸리티

**새 파일:** `backend/utils/db.py`
```python
def fetch_all(cur) -> list[dict]:
    """cursor → list of dicts. 20+ 위치에서 중복되는 패턴."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def build_date_range(year: int, month: int) -> tuple[str, str]:
    """EXTRACT 대신 range 쿼리용 날짜 범위 생성."""
    ...
```

---

## Task 9: 에러 핸들링 + 응답 표준화

**dashboard.py, cashflow.py 라우터:** try/except 추가
**응답 표준화:** 모든 CRUD에 `{"id": N, "status": "created|updated|deleted"}` 패턴 통일 (이미 forecasts/card_settings가 이 패턴)

---

## 실행 순서

```
Task 1 (DB 연결)      → Task 2 (스키마)    → Task 3 (쿼리 최적화)
                                            ↓
Task 4 (statement 분리) + Task 5 (upload)   → Task 6 (설정 테이블)
                                            ↓
Task 7 (통합 테스트)   → Task 8 (DRY)       → Task 9 (에러 핸들링)
```

**의존성:** Task 1-2가 선행 (DB 연결 필수). Task 4-6은 병렬 가능. Task 7-9는 마지막.

## NOT in scope

- Supabase Auth 통합 (Phase 4에서 별도 진행)
- Supabase JS SDK 도입 (FastAPI 백엔드이므로 불필요)
- ORM 도입 (raw SQL 유지)
- 프론트엔드 변경 (백엔드 API 인터페이스 변경 없음)
- Mercury/Codef DRY 통합 (사용량 낮아 ROI 부족)

## What already exists

- `psycopg2.pool.ThreadedConnectionPool` — Supabase도 동일 드라이버 사용
- `conftest.py` DB fixture — Supabase URL로 교체하면 그대로 작동
- `cashflow_service.py` 순수 함수들 — DB 무관, 변경 불필요
- 70 pytest — 스키마 마이그레이션 후 전부 통과해야 함

## Failure modes

| Codepath | 실패 시나리오 | 테스트? | 에러 핸들링? | 사용자 영향 |
|----------|-------------|---------|------------|-----------|
| Supabase 연결 실패 | pooler 다운 | ❌ | pool init에서 crash | 500 에러 |
| search_path 미설정 | public 스키마 참조 | Task 7에서 추가 | ❌ → ✅ | 빈 데이터 반환 |
| base_currency NULL | 연결재무제표 생성 실패 | ❌ → Task 2에서 수정 | 없음 → 500 | 재무제표 깨짐 |
| upload 대용량 파일 | 메모리 부족 | ❌ | ❌ | 서버 OOM |

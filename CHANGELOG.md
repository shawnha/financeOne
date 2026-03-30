# Changelog

All notable changes to FinanceOne will be documented in this file.

## [0.7.0] - 2026-03-30 — Slack 구조화 파싱 엔진

### Added
- **Claude Sonnet 구조화 파싱** — Slack 경비 메시지를 자동으로 구조화된 JSON으로 변환
  - vendor, category, 항목별 금액, VAT, 원천징수, 선금/잔금 추출
  - sync 시 자동 호출 (신규/변경 메시지만, 기존 건 스킵)
  - `parsed_structured` JSONB 컬럼으로 저장
  - Claude API 실패 시 기존 regex 결과로 fallback
- **Slack 카드 구조화 테이블** — 카드 펼침 시 항목/VAT/원천징수/결제조건 테이블 표시
- **원문 보기 토글** — 구조화 데이터 아래 원문 텍스트 접기/펼치기

### Changed
- **카드 접힌 상태** — 날짜를 이름 앞에 배치 (날짜순 정렬 기준)

## [0.6.1] - 2026-03-28 — 현금흐름 UI 재설계 (mockup 반영)

### Changed
- **탭 1 (실제 현금흐름) 차트**: Bar+Line -> Bar+Area 복합 차트, 선택 월 강조 (opacity 1 vs 0.35), 순현금흐름 Area fill (amber gradient)
- **탭 1 거래 리스트**: 5컬럼 그리드 (날짜/유형/항목/금액/잔고) + mockup 스타일 시작/기말 잔고 행
- **탭 2 (예상 현금흐름)**: 차트 제거, 안내 note box 추가, 테이블 전용 레이아웃
- **KPI 카드**: mockup 스타일 (10px uppercase label, 17px mono value)
- **전반적**: rounded-2xl 카드, 10px uppercase 헤더, mockup 색상/간격 반영

## [0.6.0] - 2026-03-26 — Supabase 마이그레이션 + 백엔드 리팩토링

### Changed
- **DB: Neon → Supabase** — hanahone-erp 프로젝트 (kxsofwbwzoovnwgxiwgi), financeone 스키마
- **connection.py** — SET search_path TO financeone, public + 로깅
- **schema.sql** — IF NOT EXISTS, base_currency 컬럼, idx_tx_file_id 인덱스, NULLS NOT DISTINCT
- **EXTRACT → range queries** — 11개 EXTRACT(YEAR/MONTH) → date >= / date < 변환 (인덱스 활용)
- **fetch_all 유틸** — 14개 파일 24개 위치의 cols/dict(zip) 패턴 → fetch_all(cur)
- **statement_generator 분리** — 1074줄 → 7 모듈 (balance_sheet, income_statement, cash_flow, trial_balance, deficit, consolidated, helpers)
- **upload dedup** — O(n²) → O(1) set 기반 중복 체크 (dedup_service.py)
- **하드코딩 제거** — ENTITIES dict, HOI_ENTITY_ID, CASH_ACCOUNT_CODE, EQUITY_INCEPTION_DATE → DB/env
- **VERSION 파일** — main.py 버전 하드코딩 → VERSION 파일 (0.5.0)
- **에러 핸들링** — dashboard, cashflow, intercompany 라우터 try/except + 파서 로깅

### Added
- `backend/utils/db.py` — fetch_all(), build_date_range() 유틸
- `backend/services/dedup_service.py` — O(1) 중복 감지 서비스
- `backend/services/statements/` — 7개 모듈로 분리
- `backend/tests/test_api_integration.py` — API 통합 테스트 10개
- 총 80 tests (70 기존 + 10 통합)

## [0.5.0] - 2026-03-26 — 현금흐름 3탭 재설계 + 프로덕션 배포

### Added
- **현금흐름 3탭 UI** — 실제/예상/비용 탭 구조 (green/amber/purple 색상 코딩)
- **cashflow_service.py** — 기초잔고 역산, 일별 running balance, 월별 요약, 카드 그룹핑, 시차보정 엔진
- **4 Cashflow API** — `/actual` (일별 거래+잔고), `/summary` (월별 차트), `/card-expense` (카드 그룹핑), `/forecast` (시차보정)
- **Forecasts CRUD API** — 예상 입금/출금 항목 생성·수정·삭제 (`/api/forecasts`)
- **card_settings 테이블+API** — 카드 결제일, 카드사 정보 관리 (`/api/card-settings`)
- **실제 현금흐름 탭** — ComposedChart(Bar+Line) + KPI 4개 + 거래 드릴다운 리스트 + 월 pill 네비
- **예상 현금흐름 탭** — forecast 항목 테이블 (7컬럼 토글) + 입력 모달 + 시차보정 박스 + 공식 표시
- **비용 (카드) 탭** — 카드/회원 아코디언 + 내부계정 breakdown + 월별 비교
- **opening_balance 저장** — 우리은행 Excel 업로드 시 기초잔고도 balance_snapshots에 저장
- **프로덕션 배포 설정** — Railway (nixpacks.toml, Procfile) + Vercel (vercel.json)
- **통화 포맷** — HOI=$, 한국법인=₩ entity-aware 포맷팅
- **Excel 파싱 개선** — 역순 정렬 처리, 동일키 중복 허용, 7가지 파싱 로직 수정
- 16 new pytest cases (cashflow) — 총 70 tests
- design-system/pages/cashflow.md 디자인 사양 문서

### Changed
- DB: 20 → 21 테이블 (card_settings 추가)
- dashboard.py → cashflow 엔드포인트를 전용 라우터로 분리
- cashflow/page.tsx → 3탭 셸로 교체
- Geist/Geist Mono 폰트 적용 (IBM Plex에서 전환)

### Fixed
- Recharts Bar opacity 함수 prop → 사전 계산 값으로 수정
- 우리은행 Excel 역순 정렬 시 기초/기말 잔고 뒤바뀜

## [Unreleased]

## [0.3.0] - 2026-03-23 — Phase 3: 3개 법인 연결재무제표

### Added
- **연결재무제표** — US GAAP 기준, USD 통화, 3법인 합산 + 내부거래 상계 + CTA
- **CTA 엔진** — 자산/부채=기말환율, 수익/비용=평균환율, 자본=역사적환율, 차이→AOCI(30400)
- **환율 서비스** — 기말/평균/역사적 환율 조회, 공휴일 직전 영업일 fallback (7일 이내)
- **GAAP 변환** — K-GAAP → US GAAP 코드 매핑 (gaap_mapping 테이블 활용)
- **내부거래 감지** — 자동 매칭 (금액+날짜±1일+반대타입) + 수동 확인 + 상계
- **환율 관리 API** — CRUD + closing/average 환율 조회 엔드포인트
- **내부거래 API** — detect/pairs/confirm/reject 엔드포인트
- **연결 탭** — EntityTabs "연결" 활성화 (보라색, entity=consolidated, USD 포맷)
- **사이드바** — "법인간 거래" + "환율 관리" 메뉴 추가
- **감사 추적** — consolidation_adjustments 테이블 (CTA, 상계, GAAP 변환 기록)
- 16 new pytest cases (환율 8 + 내부거래 2 + CTA/GAAP 6) — 총 54 tests

### Changed
- DB: 18 → 20 테이블 (intercompany_pairs, consolidation_adjustments)
- financial_statements: base_currency 컬럼 추가
- statement_generator: generate_consolidated_statements 함수 추가
- statements 라우터: POST /generate-consolidated 엔드포인트

## [0.2.0] - 2026-03-23 — Phase 2: 복식부기 엔진 + 재무제표

### Added
- **복식부기 엔진** — journal_entries + journal_entry_lines 테이블, sum(debit)==sum(credit) 강제 검증, 복합 분개(3줄+) 지원
- **재무제표 5종 자동 생성** — 재무상태표(자산=부채+자본 검증), 손익계산서, 현금흐름표(직접법, 독립 기말잔고 검증), 합계잔액시산표, 결손금처리계산서
- **거래 확정 → 자동 분개** — 거래 확정 시 동일 트랜잭션에서 분개 원자적 생성 (CLAUDE.md 원칙 #9)
- **Mercury API 연동** — HOI USD 거래 read-only 동기화, 페이지네이션, 중복 감지
- **Codef 샌드박스** — 우리은행/롯데카드/우리카드 거래 조회 (SANDBOX 전용)
- **재무제표 UI** — /statements 페이지, 5탭 전환, 생성 버튼, 검증 배지(균형/불균형), 인쇄 지원
- **설정 페이지** — /settings, Mercury/Codef 연결 테스트 UI
- **Excel Export** — 재무제표 다운로드 (openpyxl, K-GAAP 양식)
- **분개 API** — CRUD + 시산표 검증 + 벌크 생성 from-transactions
- 24 new pytest cases (복식부기 14 + 재무제표 10) — 총 38 tests

### Changed
- DB: 16 → 18 테이블 (journal_entries, journal_entry_lines 추가)
- Connection pool: 반환 시 rollback 추가 (stale transaction 방지)
- transactions.py: 확정/벌크 확정 시 자동 분개 + journal_error/journal_skipped 응답
- statements.py: fs.statement_type 참조 버그 수정 (스키마에 없는 컬럼)
- CORS: allow_methods/allow_headers 명시적 제한
- Sidebar: "재무제표" 메뉴 활성화

### Fixed
- statements.py fs.statement_type 참조 오류 (스키마에 없는 컬럼 제거)
- cashflow/page.tsx 미사용 AreaChart import 제거
- Codef 에러 메시지에 내부 정보 노출 방지
- 분개 중복 생성 race condition (UNIQUE INDEX on transaction_id)

## [0.1.0] - 2026-03-23 — Phase 1: 현금흐름 대시보드

### Added
- **Dashboard** — 4 KPI 카드 (잔고, 수입, 지출, 런웨이) + 현금흐름 차트 + 최근 거래 + Quick Actions
- **Transactions** — 11컬럼 dense table (체크박스, 날짜, 출처, 회원, 내역, 거래처, 수입, 지출, 내부계정, 표준계정, 신뢰도) + 필터 + 벌크 확정 + 인라인 편집
- **Upload** — 드래그앤드롭 Excel 업로드 (.xls/.xlsx) + 소스 자동 감지 + 프로그레스 바 + 히스토리
- **Cashflow** — 12개월 Area 차트 + 월별 breakdown 테이블 (기초/수입/지출/순/기말)
- **Slack Match** — 2-panel 매칭 UI (메시지 카드 + 후보 패널) + 키보드 단축키
- **Sidebar** — 4개 섹션 그룹핑 (요약/데이터/계정/관리), P2 disabled, 모바일 hamburger
- **Entity Tabs** — 3법인 전환 (?entity= 쿼리 파라미터), 연결 탭 Phase 3 disabled
- **Excel 파서** — 롯데카드/우리카드/우리은행/CSV 자동 감지 (BaseParser 공통 인터페이스)
- **체크카드 중복 감지** — 우리은행 '체크우리' ↔ 우리카드 '체크계좌' 자동 마킹
- **Slack 라우터** — 메시지 조회, 후보 매칭 (금액 ±1/±3%/VAT), 확정/무시
- **Cashflow 엔드포인트** — 월별 opening/income/expense/net/closing
- pytest 14 cases (파서 감지 + 파싱 + 중복 + 레지스트리)
- Playwright E2E 3 cases (대시보드, 엔티티 탭, 네비게이션)
- shadcn/ui 13개 컴포넌트 + sonner toast
- 공유 유틸리티 (formatKRW, fetchAPI)

### Changed
- DB connection: get_conn/put_conn → Depends(get_db) generator 패턴
- CORS: 하드코딩 → ALLOWED_ORIGINS 환경변수
- Dashboard KPI: 전월 대비 증감율 추가
- MASTER.md: KPI 크기 분리 (standalone 48px / inline 28px), A11y 사양, 반응형 전략 추가
- dashboard.md: Interaction States, 반응형, 법인 탭 동작, Quick Actions 구체화
- transactions.md: Interaction States, 반응형, 중복 표시 확정 (회색+취소선)

### Fixed
- Recharts ResponsiveContainer width/height 콘솔 경고 (minWidth={0})
- Sidebar h1 중복 (로고 div로 변경)
- Dashboard 터치 타겟 16px → 44px

## [0.0.0] - 2026-03-22 — Phase 0: 프로젝트 세팅

### Added
- PRD v2 완성 (docs/PRD.html)
- Neon dev 브랜치 (16 테이블, 48 표준계정, 28 GAAP 매핑)
- Frontend: Next.js 14 + Tailwind + shadcn/ui + Recharts
- Backend: FastAPI + psycopg2 + 6개 라우터
- 디자인 시스템: MASTER.md (UUPM dark OLED)
- Slack 매칭 엔진 설계 (docs/slack-matching-engine.md)
- Alembic 초기화, Railway/Vercel CLI 설치

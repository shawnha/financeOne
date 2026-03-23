# Changelog

All notable changes to FinanceOne will be documented in this file.

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

# Changelog

All notable changes to FinanceOne will be documented in this file.

## [Unreleased] - 2026-04-30 — Codef 신한은행 지원 (한아원홀세일 등)

### Added
- Codef BANK_ORGS 에 `shinhan_bank` (신한은행 BizBank) 추가
  - ORG_CODES: `0088` (Codef 표준 신한은행 코드)
  - ORG_LABELS: "신한은행"
  - VALID_CODEF_ORGS allowlist 도 갱신
- frontend `CodefOrg` type + `CODEF_ORG_LABELS` + `CODEF_ORG_ORDER` + `CODEF_BANK_ORGS` 에 신한은행 등록

### Changed
- `CodefClient.get_bank_account_list / get_bank_transactions / sync_bank_transactions`
  에 `org` 파라미터 추가 (default `"woori_bank"` — backward compat)
  - source_type 동적 결정 (`codef_woori_bank` / `codef_ibk_bank` / `codef_shinhan_bank`)
  - balance_snapshots account_name 도 org 기반 동적 ("우리은행 법인통장" / "신한은행 법인통장" 등)
  - 체크카드 cross-dedup ('체크우리') 은 woori_bank 한정으로 제한
- `POST /api/integrations/codef/sync-bank` 가 `organization` 필드 받아 동적 sync (미지정 시 woori_bank)
- scheduler `codef_sync_job` 이 `org` 인자를 sync_bank_transactions 에 전달
- frontend `syncCodefOrg`: 은행 판정을 `CODEF_BANK_ORGS.has(org)` 로 일반화 + organization 필드 POST body 에 포함

### Notes
- 한아원홀세일에서 신한은행 BizBank 인증서로 connected_id 등록 후 정상 sync 가능 예정
  (Codef 응답 구조는 우리은행과 동일 가정 — 첫 sync 후 검증 필요)

## [Unreleased] - 2026-04-30 — standard_accounts GAAP 분리 (US-GAAP COA 추가)

### Added
- `standard_accounts.gaap_type` 컬럼 추가 (`K_GAAP` | `US_GAAP`, default `K_GAAP`)
- US-GAAP COA 61건 seed (gaap_mapping 의 distinct us_gaap_code 추출)
  - normal_side 휴리스틱: 1xxx/5xxx → debit, 그 외 → credit
- `GET /api/accounts/standard?entity_id=X` 가 entity.type 기반 gaap_type 자동 필터
  - `US_CORP` (HOI) → US_GAAP
  - `KR_CORP` (HOK/HOR/HOW) → K_GAAP
  - `?gaap_type=US_GAAP|K_GAAP` 명시 override 가능
- 응답에 `gaap_type` 필드 노출

### Changed
- `code` UNIQUE 제약 → `(code, gaap_type)` 복합 UNIQUE (US/K-GAAP namespace 분리)
- `parent_code` FK 제거 (단일 unique 깨짐 → application-level 트리)
- 기존 `WHERE code = X` lookup 모두 `AND gaap_type = 'K_GAAP'` 명시
  - `bookkeeping_engine._get_cash_account_id`, `_get_accounts_payable_id`
  - `invoice_service._lookup_account_id`
  - `salesone.py` sales_acc 조회
  - `statements/cash_flow.py` 현금 잔액 4 곳 (10100)
- `standard_account_recommender`: US_CORP entity 는 keyword_dict 단계 skip
  (현재 keyword 사전이 K-GAAP 가정이라 잘못된 추천 방지)

### Notes (다음 세션)
- HOI 의 internal_accounts 40 건은 여전히 K-GAAP standard 를 가리킴 → 수동 재매핑 필요
  (자동 매핑은 신뢰도 부족, 검토 후 진행)

## [Unreleased] - 2026-04-30 — 한아원홀세일(HOW) 법인 추가 + Codef 동적 법인 리스트

### Added
- 4번째 법인 `HOW` (주식회사 한아원홀세일) 추가
  - Alembic 마이그레이션: `n4o5p6q7r8s9_add_how_entity.py` (ON CONFLICT idempotent)
  - `seed.py`: 4 entities 로 업데이트
  - 그룹 구조: HOI(US 모회사) → HOK / HOR / HOW (한국 자회사 3개)

### Changed
- 설정 페이지 Codef 법인 선택을 entities API 기반 동적 리스트로 전환
  - 기존 hardcoded `[{id:2}, {id:3}]` → `KR_CORP` + `is_active` 필터링된 entities
  - 향후 한국 법인 추가 시 코드 수정 없이 자동 등장

## [Unreleased] - 2026-04-30 — 내부 계정과목 다른 회사 복사 기능

### Added
- 내부 계정과목 페이지에 "다른 회사에서 복사" 기능
  - `POST /api/accounts/internal/copy` — source/target 법인 지정, depth 기반 정렬로 부모-자식 관계 보존
  - 모드: `merge`(같은 code skip, 추천) / `replace`(기존 비활성화 후 복사)
  - 옵션: 표준계정 매핑 / 고정설정(is_recurring) 포함 여부 토글
  - `preview: true` 로 시뮬레이션 후 rollback — 실행 전 변경 건수 미리보기
  - 단일 트랜잭션 원자성, code unique 충돌 자동 처리

## [Unreleased] - 2026-04-29 — Codef 자동 sync 마지막 실행 시각 노출 (Vercel 호환)

### Added
- 자동 sync 스케줄러: 기관별 마지막 sync 시각을 DB(`settings.codef_last_sync_*`) 영구 기록 기반으로 표시
  - `GET /api/integrations/codef/scheduler/status` 응답에 `last_sync_by_target[]`, `serverless` 필드 추가
  - 설정 페이지 → 통합 → 자동 sync 카드 안에 "기관별 마지막 sync (DB 영구 기록)" 섹션 + 상대시간(예: "3시간 전")
  - Vercel 배포(스케줄러 비활성, cold start 회피)에서도 마지막 시각 정상 표시 + serverless 안내 배너

## [Unreleased] - 2026-04-19 — Codef 카드 파싱 + 프로덕션-레디 연동

### Added
- Codef 카드 승인내역 파싱 (롯데/우리/신한) — `sync_card_approvals` + 정규화 파이프라인
- Codef 샌드박스↔프로덕션 환경 토글 (`CODEF_ENV` / `CODEF_BASE_URL`)
- Codef `create_connected_id` — id/pw 및 공동인증서 기반 연계 계정 등록
- Codef connected_id settings 저장 (`codef_connected_id_{org}` 키)
- Codef API: `POST /codef/connect`, `GET/POST/DELETE /codef/connections`
- 설정 페이지 Codef 카드 확장 — 환경 배지, 기관별 연결 상태·동기화·해제 버튼, 기간 선택
- 36개 Codef 테스트 (정규화·환경 토글·중복감지·설정 저장·sync 플로우)

### Changed
- Codef sync 엔드포인트: connected_id 미지정 시 settings에서 자동 조회
- 카드 source_type: `codef_{card_type}` (예: `codef_lotte_card`) — Excel 업로드와 구분
- 은행 source_type: `codef_woori_bank` (기존 `codef_api`에서 변경)

## [Unreleased] - 2026-04-08 — Slack 컨텍스트 매핑 + UX 개선

### Added
- mapping_rules에 Slack 컨텍스트 컬럼 추가 (description_pattern, vendor, category)
- 거래내역에서 내부계정 변경 시 Slack 매칭 정보 자동 학습
- 거래처+description 조합으로 복수 매핑 규칙 지원 (같은 거래처도 항목별 다른 계정 가능)
- 거래내역 일괄 취소 처리 버튼 (is_cancel 토글)
- 거래내역 내부계정 필터 드롭다운
- 멤버 카드번호 매칭 fallback (이름 매칭 실패 시 card_number로 연결)
- 멤버 이름/카드번호 변경 시 기존 거래 자동 재연결
- 체크카드 양방향 중복 감지 (우리은행 ↔ 우리카드)
- 예상 페이지 + 거래내역에서 내부계정 인라인 추가 (AccountCombobox)
- Warnings 카드 (잔고 부족 + 예산 초과 통합, 접기/펼치기)
- 거래 단건 조회 API에 entity_id 추가

### Changed
- is_cancel 필터를 모든 집계 쿼리에 적용 (대시보드, 현금흐름 14곳, 분개, 법인간 거래)
- 잔고 부족 경고: 매일 반복 → 처음 마이너스 되는 날만 1건
- Slack 매칭 카드 상단 KRW 금액: parsed_structured.total_amount_krw 우선
- 매칭 후보 통화 표시: t.currency 대신 entity_id 기반 (HOI=USD, 한국=KRW)
- Slack 동기화 속도 개선: 변경 없는 메시지(텍스트+reply_count+structured 동일) 완전 스킵
- useGlobalMonth: 초기값을 localStorage에서 즉시 읽기 (페이지 네비게이션 시 월 동기화 개선)
- PRD: Neon → Supabase, Railway 제외 반영, Phase 1/2 진행 상태 표시

### Fixed
- 8건 기존 체크우리 중복 거래 취소 처리 (Slack/거래 정합성 회복)
- 75개 매핑 규칙에 Slack 컨텍스트 소급 적용 (12월~3월)

## [0.7.1] - 2026-03-31 — 다중 항목 개별 매칭

### Added
- Slack 메시지의 다중 비용 항목을 각각 별도 거래에 개별 매칭하는 워크플로우
- 후보 패널에 [전체 매칭] / [개별 매칭] 탭 (shadcn/ui Tabs)
- 항목 테이블: 클릭 시 해당 금액 기준 후보 검색, 개별 확정
- 확정 후 자동으로 다음 미매칭 항목 이동 + 토스트 알림
- 메시지 카드에 매칭 진행률 Badge (예: 2/3)
- 개별 매칭 확정 취소(undo) 기능
- 부분 매칭 메시지 무시 시 경고 다이얼로그 + 매칭 레코드 자동 정리

### Changed
- transaction_slack_match 테이블에 item_index, item_description 컬럼 추가
- confirm API에 item_index/item_description 파라미터 지원
- candidates API에 item_index 쿼리 파라미터 지원
- list_messages 응답에 item_matches, match_progress 필드 추가
- 메시지 상태에 partial (부분 매칭) 추가

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

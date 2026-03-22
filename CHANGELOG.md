# Changelog

All notable changes to FinanceOne will be documented in this file.

## [Unreleased]

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

# FinanceOne v2 — Development Guide

## Project
한아원 그룹 (HOI, 한아원코리아, 한아원리테일) 내부 회계 BPO 시스템

## Core Principles
1. 모든 테이블에 entity_id 포함 — 절대 빠뜨리지 말 것
2. 재무제표: sum(debit) == sum(credit) 항상 검증
3. 현금흐름: 기말잔고 = 기초잔고 + 수입 - 지출 루프 검증
4. AI 매핑: mapping_rules 테이블 우선 조회 후 Claude API 호출
5. HOI = US GAAP (FinanceOne 직접 처리), 한국 법인 = K-GAAP
6. 연결재무제표 = US GAAP 기준 (모회사 HOI). K-GAAP 뷰 토글 지원
7. US GAAP ↔ K-GAAP 변환: gaap_mapping 테이블 사용
8. QuickBooks = 검증 + 초기 AI 학습 데이터 (HOI 기본 회계는 FinanceOne 직접)
9. 거래 확정 = 1 DB transaction (transactions + journal_entries + mapping_rules 원자성)

## Design Reference
- 항상 design-system/MASTER.md 먼저 확인
- 화면별: design-system/pages/[screen].md 있으면 우선 적용
- 컴포넌트: shadcn/ui / 차트: Recharts / 아이콘: Lucide
- UUPM 스타일: Financial Dashboard (#9), Bento Box Grid (#21), Executive Dashboard (#3)

## DB
- 스키마: backend/database/schema.sql
- 연결: DATABASE_URL (Neon dev 브랜치 connection string)
- 로컬 개발도 Neon dev 브랜치 사용 — SQLite 사용 금지
- 14개 테이블 (13 + gaap_mapping)
- 3개 법인 초기 데이터: seed.py 실행

## Stack
- Frontend: Next.js 14 App Router
- Backend: FastAPI (Python)
- DB: Neon PostgreSQL (dev/prod 브랜치 분리)
- Deploy: Vercel (frontend) + Railway (backend)

## Directory
- frontend/src/app: Next.js 페이지
- backend/routers: FastAPI 라우터
- backend/services: 비즈니스 로직 (bookkeeping_engine, mapping_service 등)
- scripts/: 월별 브리핑 등 자동화
- design-system/: UI 디자인 시스템 (UUPM 생성)
- docs/: PRD, 설계 문서

## Error Handling Rules
- Claude API JSONParseError → mapping_rules fallback + 수동 매핑 UI
- Claude 할루시네이션 → standard_accounts/gaap_mapping에 없는 코드면 confidence=0, is_confirmed=0, 수동 매핑 유도
- MissingCarryForwardError → 경고 + 0 초기화 옵션 제공
- ConnectionPoolError → exponential backoff (1s, 2s, 4s) 재시도 + '서버 연결 지연' 메시지
- 프롬프트 인젝션 → 거래처명 sanitize 후 Claude API 전달
- OAuth 토큰 만료 → refresh token 로직 + 재인증 안내

## Edge Case Rules
- 거래 0건인 월 → 빈 재무제표 생성 (0원, 정상 표시)
- 공휴일 환율 → 직전 영업일 환율 사용
- 한 법인만 데이터 → 있는 법인만 합산 + 경고 표시

## Interaction State Coverage
모든 화면에 아래 상태를 구현:
- LOADING: 스켈레톤 UI (카드/테이블 형태에 맞게)
- EMPTY: 따뜻한 메시지 + 다음 액션 버튼 (예: "데이터를 업로드해보세요" + 업로드 버튼)
- ERROR: 구체적 에러 메시지 + 재시도/대안 안내
- SUCCESS: 정상 데이터 표시
- PARTIAL: 경고 배너 + 가용 데이터 표시

## Testing
- pytest: 복식부기 (debit==credit), 재무상태표 항등식, 현금흐름 루프, GAAP 변환, CTA 계산
- Playwright E2E: 대시보드 잔고, 법인 전환, 업로드→거래, 재무제표 항등식

## Logging
- AI 매핑 로그: 거래→계정, 신뢰도, 출처 (rule/ai/manual)
- 복식부기 검증 로그: 항등식 성공/실패
- API 연동 로그: Mercury/QuickBooks/Codef 호출 성공/실패/응답시간

## Git Workflow
- 작업 시작 전: git pull origin main
- 작업 완료 후: 자동 commit + push
- CHANGELOG.md 업데이트 필수

## Agent/Skill Workflow
- Phase 시작 → /plan-eng-review
- 비즈니스 로직 변경 → /plan-ceo-review
- UI 구현 완료 → /design-review
- PR 머지 전 → /review
- 배포 → /ship
- 버그 → /investigate
- 재무 로직 정확도 → /codex (적대적 검증)
- Phase 완료 후 → 리뷰 (/plan-eng-review + /design-review + /review)

## Phase별 Agent/Skill 사용 (상세: docs/PRD.html #agent-skill-map)

### Phase 1 — 현금흐름 대시보드
- FastAPI 라우터: Claude Code 직접 ("entity_id 없는 엔드포인트 금지")
- 대시보드 UI: **UUPM** Financial Dashboard 스타일 ("design-system/MASTER.md 먼저 읽고 구현")
- 현금흐름 차트: **UUPM** chart 도메인 ("Recharts 사용, UUPM chart 가이드 적용")
- Excel 파서: v1 코드 재활용 ("v1 파서 로직 변경 금지, 정규화만 수정")
- E2E 검증: Playwright ("매 Phase 완료 시 E2E 테스트 실행")

### Phase 2 — 재무제표 정확도
- 복식부기 엔진: 직접 구현 ("sum(debit)==sum(credit) 실패 시 즉시 중단")
- 재무제표 UI: **UUPM** Executive Dashboard
- Mercury API: 직접 구현 ("Read-only 토큰만, 쓰기 절대 금지")
- Codef 샌드박스: 직접 구현 ("SANDBOX 환경에서만 테스트")

### Phase 3 — 3개 법인 연결
- 내부거래 감지: 직접 구현 ("is_intercompany=1 시 counterparty_entity_id 필수")
- 연결재무제표: 직접 구현 ("내부거래 상계 후 합산, 환율 평균환율 적용")
- 통합 대시보드 UI: **UUPM** ("법인 전환 시 데이터 완전 재로딩 필수")

### Phase 4 — Obsidian + NotebookLM 자동화
- 월별 재무 요약: **obsidian-markdown** (frontmatter, wikilinks, callouts)
- 거래처 노트: **obsidian-markdown** (새 거래처 첫 등장 시 자동 생성)
- Vault 검색: **obsidian-cli** (`obsidian search query="..."`)
- 거래처 DB: **obsidian-bases** (Bases 필터/정렬)
- NotebookLM: notebooklm-py (scripts/monthly_briefing.py)

### Phase 5 — n8n 자동화
- 워크플로우 설계: **n8n-skills** (patterns, mcp-tools)
- 스케줄러/Webhook/에러처리: **n8n-skills**

## Skills & Agents 사용 규칙

### UI 작업 시 필수
- 모든 새 화면 개발 전: design-system/MASTER.md 읽기
- 화면별 override 확인: design-system/pages/[screen].md
- UUPM Pre-Delivery Checklist 통과 후 커밋

### Obsidian 작업 시 필수 (Phase 4+)
- obsidian-markdown skill 활성화 후 노트 생성
- frontmatter 형식: date, tags, entity 포함 필수
- wikilinks 문법: [[노트명]] (대괄호 2개)

### n8n 작업 시 (Phase 5)
- n8n-mcp MCP 서버 활성 상태 확인
- 프로덕션 워크플로우 직접 수정 절대 금지 — 항상 복사본에서 테스트 후 적용

### 세션 관리
- 컨텍스트 70% 이상: /clear 후 CLAUDE.md + 현재 Phase 파일 재로드
- Phase 완료 시: MEMORY.md 업데이트 + git commit
- 30분+ 비활성: conversations/ 폴더에 세션 요약 저장

## Reference Architecture
- Bigcapital: PostgreSQL 재무제표 생성 쿼리 패턴
- Frappe Books: Python 복식부기 로직 (전기이월, 마감 순서)
- hledger: 다중 통화 환율 처리 알고리즘

## CTA (환산차이) 처리
- 자산/부채: 기말환율
- 손익: 월평균환율
- 자본: 역사적환율
- 차이: CTA로 자본의 기타포괄손익누계액에 반영

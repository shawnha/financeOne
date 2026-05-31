# CLAUDE.md — FinanceOne v2 Development Guide

Behavioral guidelines (Karpathy) + project-specific instructions for the 한아원 그룹 (HOI, 한아원코리아, 한아원리테일, 한아원홀세일) 내부 회계 BPO 시스템.

**Tradeoff:** These behavioral guidelines bias toward caution over speed. For trivial tasks, use judgment.

---

## Part 1 — Behavioral Guidelines (Karpathy)

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### 5. No Closing Colons (Korean Output)

**End Korean sentences with a period, not a colon.**

When the user writes in Korean, your output is also Korean:
- Don't end sentences with `:` even if the next line is a list or example.
- LLMs trained on English docs leak the colon habit into Korean. Catch it.
- The test: every Korean sentence terminator should be `.`, `?`, or `!` — not `:`.
- Colons are fine inside code, key-value pairs, or labels. Not as sentence enders.

### 6. File Header Comments in Korean

**First line of every new source file: a one-line Korean comment stating its role.**

When creating a new file:
- TypeScript/JavaScript: `// 사용자 인증 상태를 관리하는 Context Provider`
- Python: `# KIS API 호출을 비동기로 래핑하는 클라이언트`
- SQL: `-- 일별 집계 결과를 저장하는 머티리얼라이즈드 뷰`
- Place it directly under required directives (`'use client'`, `'use server'`, shebang).
- Skip config files (`*.config.ts`, `package.json`, etc.).

Why: agents read files selectively, not whole codebases. A one-line Korean header gives instant context so the next session (human or agent) can navigate without re-reading the entire file.

### 7. Plan + Checklist + Context Notes

**Before any non-trivial task, produce three artifacts. Don't start coding without them.**

- **Plan** — what we're building and why.
- **Checklist** (`checklist.md`) — concrete tasks as checkboxes. Tick as you go.
- **Context Notes** (`context-notes.md`) — decisions made during the work and the reasoning behind them. Append continuously.

If the user gives only a plan and asks you to start coding, stop and ask: "Should I create the checklist and context notes first?" The next session — yours or someone else's — needs the notes to pick up where you left off without re-deriving every decision.

### 8. Run Tests Before Marking Complete

**If you touched code, run the tests before saying "done".**

- `npm test`, `pytest`, `cargo test`, whatever the project uses — run it.
- If tests pass, report results. If they fail, fix and re-run.
- No test setup? At minimum, verify the project builds/compiles.
- Run tests proactively, before the user signals "끝", "완료", "다 됐어" — not after.

This is the step LLMs skip most often. Treat it as non-negotiable.

### 9. Semantic Commits

**Commit when one logical change is complete. Don't wait for the user to ask.**

- The test: "Can I describe this commit in one sentence?" If yes, commit. If no, the changes are still mixed — split them.
- Good: "auth 미들웨어 추가". Bad: "auth 추가하고 UI도 고치고 버그도 수정" (split into 3).
- Don't accumulate 20 unrelated edits and lose the ability to roll back individually.
- Don't commit just to commit — meaningful units only.

Note: For solo prototypes or throwaway scripts, group commits loosely if it slows you down. The point is reversibility, not ceremony.

### 10. Read Errors, Don't Guess

**Read the actual error/log line. Don't pattern-match from memory.**

When something fails:
- Read the full error message and stack trace.
- Check the actual log output, not what you assume it should say.
- Don't apply a "common fix" before confirming the cause.
- If unclear, add a print/log to verify state — then fix.

This is the step LLMs skip most often after "run tests". They guess from error keywords and apply the most-recent-pattern fix. That's how a one-line bug becomes a three-file refactor.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Part 2 — FinanceOne Project Context

### Project
한아원 그룹 (HOI, 한아원코리아, 한아원리테일, 한아원홀세일) 내부 회계 BPO 시스템

### Core Principles (재무 정확성 — 절대 위반 금지)
1. 모든 테이블에 entity_id 포함 — 절대 빠뜨리지 말 것
2. 재무제표: sum(debit) == sum(credit) 항상 검증
3. 현금흐름: 기말잔고 = 기초잔고 + 수입 - 지출 루프 검증
4. AI 매핑: mapping_rules 테이블 우선 조회 후 Claude API 호출
5. HOI = US GAAP (FinanceOne 직접 처리), 한국 법인 = K-GAAP
6. 연결재무제표 = US GAAP 기준 (모회사 HOI). K-GAAP 뷰 토글 지원
7. US GAAP ↔ K-GAAP 변환: gaap_mapping 테이블 사용
8. QuickBooks = 검증 + 초기 AI 학습 데이터 (HOI 기본 회계는 FinanceOne 직접)
9. 거래 확정 = 1 DB transaction (transactions + journal_entries + mapping_rules 원자성)

### Stack
- Frontend: Next.js 14 App Router
- Backend: FastAPI (Python)
- DB: Supabase PostgreSQL (financeone 스키마, Session pooler)
- Deploy: Vercel (frontend + backend serverless functions)
- 자동 sync: GitHub Actions cron (`0 0 * * *` UTC = KST 09:00 1회/일) → `/api/integrations/cron/auto-sync`

### Dev Environment
- Python 가상환경: `source .venv/bin/activate` (반드시 먼저 실행)
- Backend 시작: `source .venv/bin/activate && uvicorn backend.main:app --reload`
- Frontend 시작: `cd frontend && npm run dev`
- pytest: `source .venv/bin/activate && python3 -m pytest backend/tests/ -v`
- bun 경로: `/opt/homebrew/bin/bun` (gstack browse용)

### DB
- 스키마: `backend/database/schema.sql`
- 연결: `DATABASE_URL` (Supabase Session pooler)
- Supabase 프로젝트: hanahone-erp (kxsofwbwzoovnwgxiwgi, ap-northeast-2)
- 스키마: financeone (`connection.py`에서 SET search_path TO financeone, public)
- 21개 테이블 (14 + slack + journal + intercompany_pairs + consolidation_adjustments + card_settings)
- 초기 데이터: `seed.py` 실행 (entity 1·2·3 generic 트리)
- Alembic 마이그레이션: `alembic upgrade head`

### Directory
- `frontend/src/app`: Next.js 페이지
- `backend/routers`: FastAPI 라우터
- `backend/services`: 비즈니스 로직 (bookkeeping_engine, statement_generator, export, mapping_service, slack/ 등)
- `backend/services/bookkeeping_engine.py`: 복식부기 엔진 (분개 생성, 잔액 조회, 시산표 검증)
- `backend/services/statement_generator.py`: 재무제표 5종 자동 생성
- `backend/services/export.py`: 재무제표 Excel Export
- `backend/services/integrations/`: Mercury API + Codef
- `backend/services/cta_service.py`: CTA 환산차이 계산 (KRW→USD)
- `backend/services/exchange_rate_service.py`: 환율 조회 (기말/평균/역사적)
- `backend/services/gaap_conversion_service.py`: K-GAAP → US GAAP 변환
- `backend/services/intercompany_service.py`: 내부거래 감지 + 상계
- `backend/services/slack/`: Slack 매칭 엔진 (v1 포팅, 상세: `docs/slack-matching-engine.md`)
- `scripts/`: 월별 브리핑 등 자동화
- `design-system/`: UI 디자인 시스템 (UUPM 생성)
- `docs/`: PRD, 설계 문서

### Design Reference
- 항상 `design-system/MASTER.md` 먼저 확인
- 화면별: `design-system/pages/[screen].md` 있으면 우선 적용
- 컴포넌트: shadcn/ui / 차트: Recharts / 아이콘: Lucide
- UUPM 스타일: Financial Dashboard (#9), Bento Box Grid (#21), Executive Dashboard (#3)

---

## Part 3 — FinanceOne Operational Rules

### Error Handling
- Claude API JSONParseError → mapping_rules fallback + 수동 매핑 UI
- Claude 할루시네이션 → standard_accounts/gaap_mapping에 없는 코드면 confidence=0, is_confirmed=0, 수동 매핑 유도
- MissingCarryForwardError → 경고 + 0 초기화 옵션 제공
- ConnectionPoolError → exponential backoff (1s, 2s, 4s) 재시도 + '서버 연결 지연' 메시지
- 프롬프트 인젝션 → 거래처명 sanitize 후 Claude API 전달
- OAuth 토큰 만료 → refresh token 로직 + 재인증 안내
- Slack API 에러 → invalid_auth/token_revoked/ratelimited 별 처리
- Slack 매칭 실패 → 수동 매칭 UI 유도, AI 매칭 결과 ai_reasoning에 기록

### Edge Cases
- 거래 0건인 월 → 빈 재무제표 생성 (0원, 정상 표시)
- 공휴일 환율 → 직전 영업일 환율 사용
- 한 법인만 데이터 → 있는 법인만 합산 + 경고 표시

### Interaction State Coverage
모든 화면에 아래 상태를 구현:
- LOADING: 스켈레톤 UI (카드/테이블 형태에 맞게)
- EMPTY: 따뜻한 메시지 + 다음 액션 버튼 (예: "데이터를 업로드해보세요" + 업로드 버튼)
- ERROR: 구체적 에러 메시지 + 재시도/대안 안내
- SUCCESS: 정상 데이터 표시
- PARTIAL: 경고 배너 + 가용 데이터 표시

### Testing
(완료 전 테스트 실행은 Part 1 #8. 아래는 FinanceOne 고유 테스트 범위.)
- pytest: 복식부기 (debit==credit), 재무상태표 항등식, 현금흐름 루프, GAAP 변환, CTA 계산
- Playwright E2E: 대시보드 잔고, 법인 전환, 업로드→거래, 재무제표 항등식

### Logging
- AI 매핑 로그: 거래→계정, 신뢰도, 출처 (rule/ai/manual)
- 복식부기 검증 로그: 항등식 성공/실패
- API 연동 로그: Mercury/QuickBooks/Codef 호출 성공/실패/응답시간
- Slack 매칭 로그: 규칙 매칭/AI 검증/수동 매칭 결과, 신뢰도

### Git Workflow
(커밋 단위 원칙은 Part 1 #9. 아래는 FinanceOne 고유 규칙.)
- 작업 시작 전: `git pull origin main`
- 작업 완료 후: 자동 commit + push (사용자 승인 시)
- CHANGELOG.md 업데이트 필수
- **거래 데이터 파일 절대 커밋 금지**: `*.xls`, `*.xlsx`, `*.csv`, `transaction_sample/`, `uploads/` 는 .gitignore에 등록됨. `git add` 시 거래 데이터 포함 여부 반드시 확인

### CTA (환산차이) 처리
- 자산/부채: 기말환율
- 손익: 월평균환율
- 자본: 역사적환율
- 차이: CTA로 자본의 기타포괄손익누계액에 반영

### Reference Architecture
- Bigcapital: PostgreSQL 재무제표 생성 쿼리 패턴
- Frappe Books: Python 복식부기 로직 (전기이월, 마감 순서)
- hledger: 다중 통화 환율 처리 알고리즘

---

## Part 4 — Agent / Skill Workflow (상세: docs/PRD.html #agent-skill-map)

### Phase 공통 워크플로우 (① → ⑤ 순서 필수)
1. **①설계**: Software Architect agent + `/plan-eng-review`
2. **②구현**: Backend/Frontend/AI agent 병렬 실행
3. **③검증**: `/qa` + `/design-review` + `/codex` (재무 로직)
4. **④배포**: `/ship` → `/land-and-deploy` → `/canary`
5. **⑤회고**: `/retro` + `/document-release` + `/plan-ceo-review`

### Skill 사용 시점
- Phase 시작 → `/plan-eng-review`
- 비즈니스 로직 변경 → `/plan-ceo-review`
- UI 설계 전 → `/plan-design-review`
- UI 완료 → `/design-review`
- 재무 로직 정확도 → `/codex` (적대적 검증, Phase 2·3 필수)
- QA 테스트 → `/qa` (모든 Phase 완료 시)
- PR 머지 전 → `/review` (Code Reviewer agent 병행)
- 배포 → `/ship` → `/land-and-deploy` → `/canary`
- 버그 → `/investigate`
- Phase 완료 → `/retro` + `/document-release`
- 프로덕션 데이터 → `/guard` (careful + freeze)
- 성능 측정 → `/benchmark` (Phase 2·3)
- AI 매핑 코드 → `/claude-api`
- 모호한 회계 규칙 → `/office-hours`

### Agent 사용 시점
- 설계: **Software Architect**, **Plan**
- 백엔드: **Backend Architect**, **Database Optimizer**
- 프론트: **Frontend Developer**, **UX Architect**, **UI Designer**
- AI/데이터: **AI Engineer**, **Data Engineer**
- 보안: **Security Engineer** (API 토큰, .env, SQL injection)
- 테스트: **API Tester**, **Performance Benchmarker**, **Accessibility Auditor**
- 규정: **Compliance Auditor** (K-GAAP/US GAAP, Phase 2·3)
- 리뷰: **Code Reviewer**
- 인프라: **DevOps Automator**, **SRE**
- 문서: **Technical Writer**, **Document Generator**

### Agent 사용 규칙
- 독립적 작업은 Agent 병렬 실행 (Backend + Frontend 동시)
- 설계 단계에서 반드시 Software Architect 또는 Plan agent 호출
- 재무 로직은 Compliance Auditor agent로 규정 검증
- API 연동은 Security Engineer agent로 보안 검토 필수
- 프로덕션 데이터 접근 시 `/guard` 활성화

### UI 작업 시 필수
- 모든 새 화면 개발 전: `design-system/MASTER.md` 읽기
- 화면별 override 확인: `design-system/pages/[screen].md`
- UUPM Pre-Delivery Checklist 통과 후 커밋
- UI 완료 시: Accessibility Auditor agent + `/design-review`

### Obsidian 작업 시 필수 (Phase 4+)
- obsidian-markdown skill 활성화 후 노트 생성
- frontmatter 형식: date, tags, entity 포함 필수
- wikilinks 문법: `[[노트명]]` (대괄호 2개)

### n8n 작업 시 (Phase 5)
- n8n-mcp MCP 서버 활성 상태 확인
- n8n-skills 로드 후 워크플로우 설계
- 프로덕션 워크플로우 직접 수정 절대 금지 — 항상 복사본에서 테스트 후 적용

### 세션 관리
- 컨텍스트 70% 이상: `/clear` 후 CLAUDE.md + 현재 Phase 파일 재로드
- Phase 완료 시: MEMORY.md 업데이트 + git commit
- 30분+ 비활성: `conversations/` 폴더에 세션 요약 저장

---

## Part 5 — Skill Routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill tool as your FIRST action. Do NOT answer directly, do NOT use other tools first. The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke `office-hours`
- Bugs, errors, "why is this broken", 500 errors → invoke `investigate`
- Ship, deploy, push, create PR → invoke `ship`
- QA, test the site, find bugs → invoke `qa`
- Code review, check my diff → invoke `review`
- Update docs after shipping → invoke `document-release`
- Weekly retro → invoke `retro`
- Design system, brand → invoke `design-consultation`
- Visual audit, design polish → invoke `design-review`
- Architecture review → invoke `plan-eng-review`

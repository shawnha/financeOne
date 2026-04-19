# TODOs

## Design

### ~~cashflow.md 디자인 문서 작성~~ ✅ DONE (2026-03-26)
- 완료: `design-system/pages/cashflow.md` 생성 (plan-design-review에서)

### Cashflow UI 리디자인 — Treasury 워크스페이스 전환 (향후)
- **What:** 현재 stacked dashboard 레이아웃을 primary workspace + secondary rail 구조로 전환
- **Why:** Codex design critique (2026-04-01): KPI 카드 크롬 과다, 색상 너무 많음, 여러 섹션이 동일 정보 반복. 내부 회계 시스템에 맞는 뉴트럴/미니멀 디자인 필요.
- **Context:** 현재 UI가 작동 중이고 사용자 1-2명이라 긴급하지 않음. forecast 기능 완성 후 별도 PR로 진행. Codex 지적: (1) KPI를 inline summary로 압축, (2) 색상 간소화 (뉴트럴 + red/green만), (3) 비교 박스/수식/KPI 중복 제거, (4) 드릴다운 1단계로 제한.
- **Depends on:** 이번 PR(재매핑+예상현금흐름) 완료 후

## Backend

### daily-schedule API → AI 예측 확장 (Phase 4+)
- **What:** `GET /api/cashflow/daily-schedule` 엔드포인트를 AI 기반 학습 공식으로 확장
- **Why:** 현재 전월 실적 기반 단순 예측 → NotebookLM + Obsidian 워크플로우로 카테고리별 정확 예측
- **Context:** TENSION-2 결정으로 백엔드에 일별 시뮬레이션 API 생성. 이 엔드포인트가 AI 예측의 확장점. 프론트는 렌더링만 하므로 백엔드만 수정하면 됨.
- **Depends on:** Phase 4+ NotebookLM 연동, 3개월 이상 데이터 축적 (12월→3월)

### ExpenseOne 일 1회 자동 동기화 cron (P2)
- **What:** ExpenseOne 승인 경비를 FinanceOne으로 매일 01:00 KST 자동 pull
- **Why:** CEO가 '동기화 버튼 누르는 것도 잊는' 리스크 제거. 월말 결산 직전에 한꺼번에 돌리면 누락/지연 발생 가능.
- **Context:** CEO 리뷰 2026-04-19에서 SELECTIVE EXPANSION #1로 ACCEPTED됐으나, Backend 호스팅 미결정 상태 (CLAUDE.md Railway 기록 stale, 실제 FastAPI 배포 위치 미정)로 DEFERRED. Supabase는 Python 런타임 없음 → Edge Function (Deno rewrite) vs FastAPI 외부 배포(Fly/Render/Cloud Run) 결정 필요.
- **Depends on:** Backend hosting 전략 결정 세션
- **Effort:** S (스크립트 자체) + backend deploy 의존
- **Priority:** P2

### ExpenseOne source_type 부분 인덱스 (P2)
- **What:** `CREATE INDEX idx_tx_source_type ON transactions(source_type) WHERE source_type LIKE 'expenseone_%'`
- **Why:** 대시보드 배지 카운트 쿼리 + 필터 쿼리가 LIKE 사용 → 거래 수 증가 시 slow.
- **Context:** CEO 리뷰 2026-04-19 — Section 7 (Performance) 지적. 현재 거래량 작아 당장 문제 없지만 Phase 3 이후 거래 축적 시 필요.
- **Depends on:** 없음. 당장 추가해도 무방 (마이그레이션 1줄).
- **Priority:** P2

### ExpenseOne 동기화 실패 재시도 큐 (P3)
- **What:** sync_to_financeone에서 실패한 expense를 재시도 큐에 저장, 다음 동기화 때 우선 처리
- **Why:** 현재는 errors[] 로그만 남음. 자동 재시도 없음. 일시적 DB 에러 시 데이터 누락 가능.
- **Context:** CEO 리뷰 2026-04-19 — 소규모 팀엔 수동 재동기화로 충분. 데이터량 늘면 필요.
- **Depends on:** cron 구현 이후 (자동화된 경우에만 유의미)
- **Priority:** P3

### ExpenseOne row → 원본 앱 링크 (P3)
- **What:** transactions 테이블 row에서 expense_id 있으면 ExpenseOne 앱의 해당 expense 상세 페이지로 링크
- **Why:** 첨부파일(영수증, 견적서) 확인이 필요한 경우 바로 이동. 현재는 수동으로 ExpenseOne 접속 → 검색.
- **Context:** CEO 리뷰 2026-04-19 — 사용자 검증 후 추가. ExpenseOne URL 규칙 `{NEXT_PUBLIC_APP_URL}/expenses/{id}`.
- **Depends on:** ExpenseOne 공개 URL 확정
- **Priority:** P3

### CLAUDE.md 배포 스택 기록 정정 (P2)
- **What:** CLAUDE.md `Deploy: Vercel (frontend) + Railway (backend)` 라인 업데이트
- **Why:** Railway 기록은 stale. 실제로는 backend hosting 미결정 상태. QBO Production 전환 시점에 "Render/Fly.io 등" 언급 (project_resume.md).
- **Context:** CEO 리뷰 2026-04-19에서 발견. 문서와 실제 상태 불일치.
- **Depends on:** Backend hosting 결정 세션
- **Priority:** P2

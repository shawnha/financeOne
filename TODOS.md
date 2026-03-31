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

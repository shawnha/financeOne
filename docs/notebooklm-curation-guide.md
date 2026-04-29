---
tags: [phase4, notebooklm, ai학습]
date: 2026-04-29
---

# NotebookLM 학습 자료 큐레이션 가이드 (Phase 4)

NotebookLM 은 사용자가 직접 자료를 업로드해야 하는 RAG 시스템.
이 문서는 FinanceOne v2 의 회계 컨텍스트를 가르치기 위한 자료 우선순위.

## 단계 1 — 회계 기본 가이드 (필수, 8시간)

### 1-A. K-GAAP / US GAAP 코드북
- 출처: 한국채택국제회계기준 (K-IFRS) 또는 회계법인 표준계정과목표 PDF
- 업로드 형식: PDF
- 목적: AI 가 K-GAAP 코드 → 의미 → US GAAP 코드 변환 학습

### 1-B. FinanceOne v2 PRD
- 경로: `docs/PRD.html` (160KB)
- 변환: `defuddle docs/PRD.html > docs/PRD.md` 후 업로드
- 목적: 시스템 구조 + 비즈니스 룰 학습

### 1-C. CLAUDE.md
- 경로: `CLAUDE.md`
- 업로드: 그대로
- 목적: 프로젝트 핵심 원칙 학습 (entity_id 필수, debit==credit 등)

## 단계 2 — 25년 결산자료 (실무 학습, 필수)

### 2-A. 한아원코리아 K-GAAP 결산서
- 경로: `25년 결산자료/한아원코리아_2025_결산.pdf`
- 위치: `project_finalized_reports.md` 참고
- 목적: 실제 K-GAAP 재무제표 양식 + 계정 분포 학습

### 2-B. HOI US GAAP 결산서
- 경로: `25년 결산자료/HOI_2025_GL.pdf`
- 목적: US GAAP 양식 + Cash basis vs Accrual 차이 학습

### 2-C. 회계법인 피드백 노트
- 경로: `obsidian-vault/회계법인_피드백/*.md` (현재 비어있음)
- 작업: 회계법인 이메일/피드백 정리 후 markdown 노트화
- 목적: 회계 실무 판단 기준 학습 (예: "이 거래는 매입원가 vs 비용 어디?")

## 단계 3 — 거래처/벤더 컨텍스트 (운영 효율)

### 3-A. 주요 거래처 1-pager
- 거래처별 1장씩: 사업 형태, 계약 조건, 대표 거래 패턴
- 위치: `obsidian-vault/거래처/[거래처명].md` (현재 비어있음)
- 자동 생성: `scripts/generate_counterparty_notes.py` (P4-3a 작업)

### 3-B. SaaS / 벤더 카탈로그
- Adobe, Notion, Slack, AWS, Anthropic 등의 사용 목적 + 매핑 계정
- 형식: 표 형태 markdown
- 목적: SaaS 자동 매핑 정확도 향상

## 단계 4 — 운영 데이터 (월별 리포트)

### 4-A. 월별 재무 요약
- 자동 생성됨: `scripts/generate_monthly_notes.py`
- 위치: `obsidian-vault/월별 리포트/2026/2026-MM-법인명.md`
- 업로드 주기: 월말 결산 후 추가
- 목적: 시계열 패턴 학습 (계절성, 트렌드)

### 4-B. CEO 월간 브리핑
- 자동 생성됨: `scripts/monthly_briefing.py`
- 목적: 의사결정 컨텍스트 학습

## NotebookLM 업로드 순서 (권장)

| 순서 | 자료 | 노트북 분리 권장 |
|---|---|---|
| 1 | K-GAAP 코드북 + US GAAP 매핑 | "회계기준" 노트북 |
| 2 | PRD + CLAUDE.md | "FinanceOne 시스템" 노트북 |
| 3 | 25년 결산자료 (HOI/HOK PDF) | "결산자료" 노트북 |
| 4 | 회계법인 피드백 | "회계법인 피드백" 노트북 |
| 5 | 월별 자동 노트 (점진 추가) | "월별 운영" 노트북 |
| 6 | 거래처 1-pager | "거래처" 노트북 |

**노트북 분리 이유**: NotebookLM 은 노트북 단위로 쿼리.
모든 걸 한 노트북에 섞으면 답변 품질 떨어짐. 도메인별 분리가 정확도 핵심.

## 활용 워크플로우

### 일상
- 모호한 거래 매핑 → "회계기준" 노트북에 질문
- 거래처 컨텍스트 필요 → "거래처" 노트북에 질문

### 월간 결산
- 월별 노트북에 신규 월 노트 추가
- "지난 3개월 트렌드" 질문 → 시계열 분석 답변

### 분기/연간
- 회계법인 피드백 노트북 업데이트
- 결산자료 노트북에 신규 결산서 추가

## FinanceOne v2 와의 연결

NotebookLM 결과 활용:
1. 사용자가 NotebookLM 에서 답변 받음
2. **수동으로** Obsidian 의 해당 노트에 결과 정리
3. (장기) NotebookLM API 가 공개되면 자동 매핑 fallback 으로 활용

현재는 사용자 ↔ NotebookLM 직접 상호작용 → Obsidian 정리 단계.
FinanceOne 자체는 NotebookLM 직접 호출 안 함 (API 공개 전).

## 관련 작업

- 키워드 사전 (P4-4/P4-5): 261개 → confirmed 거래 늘면 자동 확장
- Obsidian 자동 노트 (이미 main): `scripts/generate_monthly_notes.py`
- Obsidian vault 구조: 거래처/이상거래/월별 리포트/회계법인_피드백

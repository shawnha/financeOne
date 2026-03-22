# FinanceOne v2

한아원 그룹 내부 회계 BPO 시스템 — CEO 전용 재무 관리 도구

## Overview

3개 법인(HOI · 한아원코리아 · 한아원리테일)의 재무를 실시간으로 파악하는 내부 시스템.
거래내역 업로드 → AI 자동 분류 → 재무제표 생성까지 자동화.

### 핵심 목표
> 오늘 잔고가 얼마이고, 다음달 말에 얼마가 남을지 30초 안에 파악

### 법인 구조
```
HOI Inc. (미국 모회사, Delaware C-Corp) ← USD, US GAAP
  └── 주식회사 한아원코리아 (한국 자회사) ← KRW, K-GAAP
        └── 주식회사 한아원리테일 (한국 손회사) ← KRW, K-GAAP
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router) + shadcn/ui + Tailwind |
| UI Design | UI UX Pro Max Skill (161 UX rules) |
| Backend | FastAPI (Python) |
| DB | Neon PostgreSQL (14 tables, dev/prod branch) |
| AI | Anthropic Claude API + mapping_rules 학습 |
| Charts | Recharts |
| Deploy | Vercel (frontend, free) + Railway (backend, free) |

## Development Phases

| Phase | Duration | Goal |
|-------|----------|------|
| 1 | 3~4 days | Cash flow dashboard |
| 2 | 4~5 days | Financial statements + API verification |
| 3 | 3~4 days | Multi-entity consolidation (US GAAP) |
| 4 | 1~2 days | Obsidian + NotebookLM automation |
| 5 | 1~2 days | n8n automation + Slack alerts |

Total: ~2-3 weeks (Claude Code based)

## Key Features

- **현금흐름 대시보드** — 잔고, 예측, 예측 정확도 피드백 루프
- **AI 계정과목 매핑** — mapping_rules 우선 → Obsidian 컨텍스트 → Claude API
- **복식부기 엔진** — sum(debit)==sum(credit) 상시 검증, T계정 시각화
- **재무제표 자동 생성** — 재무상태표, 손익계산서, 합계잔액시산표, 현금흐름표
- **연결재무제표** — US GAAP 기준 (모회사 HOI), K-GAAP 뷰 토글, CTA 환산차이 반영
- **회계법인 검증 모드** — PDF 업로드 → 항목별 자동 비교
- **AI 자기학습** — 사용할수록 매핑 정확도 향상 (mapping_rules + Obsidian)

## External Integrations

| Service | Role | Cost |
|---------|------|------|
| Mercury API | HOI 거래내역 (read) | Free |
| QuickBooks API | 검증 + AI 학습 데이터 | Free (Builder tier) |
| Codef.io | 한국 은행/카드 거래 | Free (sandbox) |
| 한국은행 환율 API | 일별 환율 자동 수집 | Free |

## Setup

```bash
# Prerequisites
node --version  # v20+
python3 --version  # 3.10+

# Clone
git clone https://github.com/shawnha/financeOne.git
cd financeOne

# Environment
cp .env.example .env
# Edit .env with your Neon connection string + API keys

# Design system (UUPM)
uipro init --ai antigravity
```

See `docs/PRD.html` for full specification.

## Project Structure

```
financeOne/
├── frontend/src/app/          # Next.js pages
├── frontend/src/components/   # React components
├── backend/routers/           # FastAPI routes
├── backend/services/          # Business logic
├── backend/models/            # DB models + Alembic
├── scripts/                   # Automation (monthly briefing)
├── design-system/             # UUPM generated
├── docs/PRD.html              # Product Requirements Document
├── CLAUDE.md                  # AI development guide
└── CHANGELOG.md               # Work history
```

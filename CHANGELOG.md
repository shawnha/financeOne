# Changelog

All notable changes to FinanceOne will be documented in this file.

## [Unreleased]

### 2026-03-22 — Project Setup
- PRD v2 완성 (docs/PRD.html)
- CEO Review 완료 — 5개 cherry-pick 수락 (회계법인 검증, 환율 API, AI 신뢰도, T계정, 예측 피드백)
- Eng Review 완료 — DB 트랜잭션 원자성, CTA 로직 추가
- Design Review 완료 — 상태 커버리지 + 네비게이션 구조 추가 (6/10 → 8/10)
- US GAAP / K-GAAP 이중 기준 구조 확정 (gaap_mapping 테이블)
- QuickBooks 역할: 검증 + 초기 AI 학습 데이터 (HOI 회계는 FinanceOne 직접 처리)
- 참고 아키텍처 3종 추가 (Bigcapital, Frappe Books, hledger)
- GSD 제거 → Claude Code 내장 Agent/Skill로 대체
- Git 초기화 + 프로젝트 구조 생성

### 2026-03-22 — Phase 0 Infrastructure
- Neon dev 브랜치 생성 (ap-southeast-1)
- DB 스키마 14개 테이블 생성 (PostgreSQL)
- seed.py: 3개 법인, 68개 K-GAAP 표준계정, 28개 US GAAP 매핑, 7개 설정
- Frontend: Next.js 14 + Tailwind v3 + shadcn/ui v2 + Recharts + Lucide
- Backend: FastAPI + psycopg2 + 6개 라우터 (entities, transactions, accounts, upload, dashboard, statements)
- UUPM 설치 (ui-ux-pro-max skill)
- Obsidian Skills 설치 (5종: defuddle, json-canvas, obsidian-bases, obsidian-cli, obsidian-markdown)
- 디자인 시스템: MASTER.md + 페이지별 가이드 (dashboard, transactions)
- notebooklm-py v0.3.4 설치
- Obsidian vault 구조 생성 (obsidian-vault/ 내 6개 폴더 + 템플릿)
- Vercel CLI v50, Playwright v1.58 설치
- LLMFit v0.8.1 설치 (brew — Rust CLI 도구)
- Statusline: 기존 ~/.claude/statusline-command.sh 확인 (model, branch, ctx%)

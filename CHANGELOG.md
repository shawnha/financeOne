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

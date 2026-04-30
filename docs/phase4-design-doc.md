---
title: Phase 4 Design Doc
date: 2026-04-30
stage: ceo-review-complete
status: approved
ceo_mode: HOLD_SCOPE
---

# Phase 4 — Design Doc (Office Hours 통과)

## TL;DR

Phase 4 의 wedge 는 **매핑 정확도 끌어올리기**. 본인(CEO) 의 매월 결산 시간을 회수하는 것이 1순위 가치. NotebookLM 통합과 AI 기반 is_recurring 제안은 보류.

## 1. WHY (Office Hours 6 Questions)

### Q1 — Demand Reality
- **관찰됨**: 매핑 충실도 HOK 96.9~99.2%, 미매핑 132건 (Stage 0 진단 결과)
- **관찰됨**: `standard_account_keywords` 14개 + cascade 미통합 (dead table)
- **추측 (검증 필요)**: 매월 매핑 처리 시간 + 노트 정리 시간 추정 5시간

### Q2 — Status Quo
- 매핑: 월 결산 마감 직전 미매핑 일괄 수동 처리
- 노트: 거래 csv → 엑셀 정리 → 회계법인 메일
- 컨텍스트: 회계법인 답변 이메일에 흩어져 검색 어려움

### Q3 — Desperate Specificity
- **1순위: 본인 (CEO)** — 사적 시간 잡아먹힘
- 2순위: 회계법인 — 양식 reformat 부담 (2차)
- 3순위: 향후 경리직원 — 미고용, 우선순위 낮음

### Q4 — Narrowest Wedge
- **선택: A. 매핑 정확도 끌어올리기** (키워드 사전 + cascade + 학습 루프)
- B (Obsidian 자동 노트) 는 follow-up
- C (NotebookLM), D (is_recurring AI) 보류

### Q5 — Observation vs Speculation
- **관찰**: 매핑 96.9%, 미매핑 132건, dead table 14개, mapping_rules 799개
- **추측**: "월 5시간 절감" → Phase 4 종료 시 실측 검증
- **추측**: "회계법인이 자동 노트 좋아할 것" → 검증 안 함, 본인 시간 회수에 집중

### Q6 — Future-Fit
- **유효**: 키워드 사전 + cascade — 매핑 로직은 변동 적음
- **위험 (보류)**: NotebookLM API 공개되면 통합 자동화 가능, 지금 통합하면 재작업
- **위험 (보류)**: AI is_recurring — 6개월+ 운영 데이터 후 재평가

## 2. WHAT (Scope)

### 진행 (Phase 4 In-Scope)
- **P4-A**: 도메인 키워드 사전 (수작업 ~150개)
- **P4-B**: `global_keyword_match` cascade 통합 + 단위 테스트
- **P4-C**: 학습 루프 자동화 (confirmed → 키워드 자동 추출, 월 cron)

### 보류 (Phase 4 Out-of-Scope)
- NotebookLM 통합 (API 공개 후 별도 Phase)
- AI 기반 is_recurring 동적 제안 (6개월 데이터 후 별도 Phase)
- Obsidian 거래처 1-pager / 이상거래 노트 (P4 follow-up 또는 별도 Phase)

## 3. WHO

- **사용자**: 본인 (CEO)
- **수혜 시나리오**: 월 결산 시 미매핑 거래 자동 처리율 ↑

## 4. 성공 기준 (3개월 후 측정)

| 지표 | Before (2026-04-30) | Target (2026-07-30) |
|---|---|---|
| 매핑 충실도 (HOK) | 96.9% | ≥ 99% |
| 미매핑 거래수 (월별) | 132건 | ≤ 30건 |
| `standard_account_keywords` 활용도 | dead (0%) | cascade 4단계로 활성 |
| 매월 매핑 수동 시간 (추정) | ~3-4시간 | ≤ 1시간 |

## 5. 위험 / 가설

| 위험 | 완화 |
|---|---|
| 자동 학습이 노이즈 키워드 등록 (USA, CITY 등) | purity ≥ 0.90 + hit ≥ 5 + stopword 확장 |
| 키워드 사전 중복으로 cascade 충돌 | 길이 우선 + confidence 우선 정렬 |
| "월 5시간 절감" 추측 검증 실패 | 종료 시 실측 → 가설 검증 → 다음 phase 결정 |

## 6. 참고

- 이전 시도 (revert 됨): commit `3a73846` — gstack 리뷰 없이 진행했던 P4-4/P4-5
- Stage 0 (revert): commit `029f472`
- 진단 데이터: `.claude-tmp/consolidation-diagnosis.json`, `.claude-tmp/consolidation-stages.json`

## 7. CEO Review 결과 (Stage 2)

**선택: Mode 3 — HOLD SCOPE** + rigor 보강

### Hold scope 보강 사항
- 각 sub-task 마다 `/codex challenge` 통과 의무
- 매핑 정확도 metric 자동 측정 (before/after)
- noise filter 강화 (purity ≥ 0.90, hit ≥ 5, stopword 확장)
- cascade 4단계 통합 시 단위테스트 의무

### 거부된 모드
- Mode 1 (Expansion): scope 5배 확장 → 본인 시간 회수 지연, NotebookLM 미공개 위험
- Mode 2 (Selective): P4-D 수요 검증 안 됨
- Mode 4 (Reduction): P4-C 없으면 키워드 사전 stale

### 보류 항목 (백로그)
별도 메모리 `project_phase4_scope_backlog.md` 로 저장:
- Trigger A (Phase 4 종료 시): P4-D Obsidian 거래처 1-pager, P4-E 이상거래 감지
- Trigger B (6개월+ 데이터 후): AI is_recurring 자동 제안, 금액 예측 고도화
- Trigger C (NotebookLM API 공개 후): NotebookLM cascade 통합
- Trigger D (외부 감사/투자 직전): 회계법인 자동 리포트, BS 자동 검증 알림

## 8. Eng Review 결과 (Stage 3)

### 6 가지 아키텍처 결정 (모두 권장안 채택)

| 결정 | 옵션 |
|---|---|
| **D1** cascade 위치 | C — entity_keyword ∪ global_keyword 통합 SQL (length × confidence 정렬) |
| **D2** internal_account 추론 | A — entity 의 standard_account 매핑 자동 추론, 없으면 NULL |
| **D3** Idempotency | A — ON CONFLICT (keyword) DO NOTHING (불변) |
| **D4** Noise filter | A — 다층 (stopwords + purity ≥ 0.90 + hit ≥ 5 + 길이 ≥ 3 + 정규화) |
| **D5** Metric | A — `measure_mapping_accuracy.py` + JSON snapshot |
| **D6** Test | Unit 3/3 + Integration 2/3 + codex 3/3 (E2E 스킵) |

### Stopwords 초기 리스트 (D4)
```
주식회사, (주), 주식, 회사, 법인,
하나, 국민, 신한, 우리, 기업,
카드, 체크, 신용,
지점, 점, 역, 센터, 본점, 지사,
월, 일, 년, 원, 월급여,
USA, INC, CORP, LLC, LTD, CITY, CULVER
```

### 통합 cascade SQL 시그니처
```sql
SELECT internal_account_id, standard_account_id, confidence, match_type
FROM (
  SELECT k.internal_account_id, ia.standard_account_id, k.confidence,
         length(k.keyword) AS w, 'entity_keyword' AS match_type
  FROM keyword_mapping_rules k
  JOIN internal_accounts ia ON k.internal_account_id = ia.id
  WHERE k.entity_id = %s AND %s ILIKE '%%' || k.keyword || '%%'
  UNION ALL
  SELECT NULL, sak.standard_account_id, sak.confidence,
         length(sak.keyword), 'global_keyword'
  FROM standard_account_keywords sak
  WHERE %s ILIKE '%%' || sak.keyword || '%%'
) merged
ORDER BY w DESC, confidence DESC
LIMIT 1
```

## 9. 다음 단계

Stage 4 `/plan-design-review` → **스킵** (UI 변경 없음)
Stage 5 → 구현 시작 (P4-A → P4-B → P4-C → 측정)

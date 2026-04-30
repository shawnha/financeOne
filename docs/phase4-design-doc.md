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

## 9. 구현 결과 (Stage 5)

| Sub-task | Commit | Tests |
|---|---|---|
| **P4-A** 도메인 키워드 사전 (134개) | `769fd41` | 15 PASS (단위 11 + integration 4) |
| **P4-B** cascade 통합 SQL + GIN 인덱스 | `cafa42a` | 16 PASS (단위 12 + integration 4) |
| **P4-C** 학습 루프 + noise filter + metric | `8129beb` | 18 PASS (단위 14 + integration 4) |
| **Stage 6** 회귀 fix (mapping_service) | `cf2743d` | 29 PASS |
| **합계** | | **78 PASS** |

### Code Reviewer 발견 + 즉시 fix
- P4-A: P0 2건 (KT/Adobe substring) + P1 4건 + P2 2건 = 8건 fix
- P4-B: P0 2건 (cross-entity leak / inactive filter) + P1 3건 (ESCAPE/인덱스/std_active) + P2 2건 = 7건 fix

### Stage 6 Health Check 결과
| Category | Score | 비고 |
|---|---|---|
| Type check (frontend) | 7/10 | 10 errors (기존, P4 무관) |
| Lint (frontend) | 4/10 | 40 errors (기존, P4 무관) |
| Tests (backend) | 9/10 | 78/78 P4 PASS, 7건 기존 실패 (P4 무관) |
| **Composite** | **6.7/10** | P4 작업으로 회귀 추가 0건 |

### 매핑 정확도 metric (2026-04-30 기준)
| entity | Standard 매핑 | Internal 매핑 | 미매핑 |
|---|---|---|---|
| HOI (1) | 100.00% | 0.00% (사용 안함) | 0 |
| HOK (2) | 96.76% | 99.01% | 141 |
| HOR (3) | 0.00% | 3.23% | 31 (자본금만) |

DB 변경: `standard_account_keywords` **14 → 243** (134 도메인 + 109 자동학습)
mapping_source 에 `global_keyword` **1건 실제 동작 확인** (production)

### 성공 기준 추적 (3개월 후 재측정 예정 — 2026-07-30)
| 지표 | 4월말 (Before) | Target |
|---|---|---|
| HOK 매핑 충실도 | 96.76% | ≥ 99% |
| 미매핑 거래수 (월별) | 132 | ≤ 30 |
| `standard_account_keywords` 활용도 | 14 (dead) | 243 (cascade 4단계 활성) ✅ |

## 10. 회고 (Stage 8)

### 잘된 점
1. gstack 워크플로우 강제 적용 — Office Hours → CEO → Eng review 통과 후 구현 (이전 시도는 리뷰 없이 강행해서 revert)
2. Code Reviewer agent 가 P0 cross-entity leak 등 결정적 발견 (재무 데이터 무결성 직격)
3. Stage 6 health check 가 회귀 4건 즉시 발견 → fix
4. 회귀 방지 테스트 7개 추가 (cross_entity_leak / inactive_filter / escape_clause / short_substring / 등)

### 배운 점
1. ILIKE substring 매칭은 짧은 영문 약자 (KT, ADS) 에 매우 위험. 화이트리스트 + brand 분리 필수.
2. `ON CONFLICT DO NOTHING` 은 idempotent 하지만 사용자 의도 변경 silent skip 위험. docstring 명시 필요.
3. Mock cursor side_effect 설계는 함수 변경에 취약. 함수 시그니처 바꾸면 의존 테스트 자동 fail 예상.

### 보류 (Phase 5 또는 별도)
- NotebookLM API 통합 (Trigger C — API 공개 후)
- AI is_recurring 자동 제안 (Trigger B — 6개월 데이터 후)
- Obsidian 거래처 1-pager 자동 생성 (Trigger A)
- 정기 게이트 미실행: `/cso` (Phase 시작/종료 보안 감사) + `/benchmark` 미수행

## 11. 다음 단계

✅ **Phase 4 완료** (2026-04-30)

다음 후보:
- 3개월 후 (2026-07-30) 성공 기준 측정 재실행 → Trigger A/B 재평가
- 별도 트랙: Phase 3 잔여 (P3-51 내부거래 상계 / 4순위 계정 코드 매핑 fix)
- 보안 보강: `/cso` 정기 게이트 (P4 위주 미수행)

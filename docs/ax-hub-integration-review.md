# FinanceOne → ax-hub 통합 전략 리뷰

> **작성일**: 2026-03-23
> **Revisit 시점**: Phase 4 시작 전
> **결론**: 지금은 개발 완성, Phase 2-3 안정화 후 통합

---

## 1. 배경

한아원 그룹 메인 플랫폼 **ax-hub** (`github.com/HanahOne/ax-hub`)에 FinanceOne을 통합해야 함.
ax-hub의 ops 모듈이 FinanceOne 역할을 일부 커버 (원가/재무 관리, 규제 컴플라이언스).

## 2. 스택 차이

| 항목 | ax-hub | FinanceOne (현재) |
|------|--------|-------------------|
| Framework | Next.js 16 + React 19 + TS | Next.js 14 (FE) + FastAPI/Python (BE) |
| DB | Supabase (PostgreSQL + pgvector) | Neon PostgreSQL (psycopg2) |
| State | Zustand | - |
| Icons | Phosphor Icons | Lucide |
| 배포 | Vercel (서버리스) | Vercel (FE + BE serverless) |
| 모노레포 | pnpm workspace | 단일 프로젝트 |
| AI | Anthropic SDK + OpenAI SDK | Anthropic SDK |

## 3. 리뷰 결과 (3개 관점 만장일치)

### Software Architect
- 도메인 복잡도가 높아 "한 번에 하나만 바꾸기" 원칙 필수
- 스택 전환 + 로직 구현 동시 진행 시 버그 원인 구분 불가
- Strangler Fig 패턴으로 점진적 통합 권장

### Backend Architect
- Python `Decimal` → JS `number` 정밀도 리스크 **치명적** (1원 차이 = 복식부기 검증 실패)
- `@supabase/supabase-js`는 명시적 트랜잭션(BEGIN/COMMIT) 미지원 → 원자성 재설계 필요
- 테스트 golden dataset 없이 포팅하면 regression 감지 불가
- 마이그레이션 작업량 추정: 20-32일

### DevOps
- Vercel 서버리스 환경에서 운영 중 (이전 Railway 계획 폐기됨)
- 서버리스 10초 타임아웃 → AI 매핑(Claude API 호출) 등에서 문제 가능
- DB 마이그레이션(Neon → Supabase)은 둘 다 PostgreSQL이라 비교적 쉬움
- 백엔드 제로 다운타임 전환은 운영 복잡도 매우 높음

## 4. 핵심 기술 리스크 (즉시 통합 시)

| 리스크 | 심각도 | 설명 |
|--------|--------|------|
| Decimal 정밀도 | 치명적 | `0.1 + 0.2 ≠ 0.3`. `decimal.js` 래핑 필요하나 Python처럼 언어 레벨 보장 안 됨 |
| 트랜잭션 원자성 | 높음 | Supabase SDK에 BEGIN/COMMIT 없음. `rpc()` 또는 PL/pgSQL 프로시저 필요 |
| 테스트 기준선 부재 | 높음 | 복식부기/GAAP/현금흐름 테스트 없이 포팅하면 검증 불가 |
| 서버리스 제약 | 중간 | 10초 타임아웃, stateless, 파일 I/O 읽기 전용 |
| 파서 포팅 | 중간 | xlrd/openpyxl → xlsx/exceljs + EUC-KR 인코딩 처리 차이 |

## 5. 결정: 개발 완성 후 통합

### 통합 아키텍처 (중간 단계)

```
ax-hub (Vercel)
  └── ops 모듈 (TypeScript)
        └── Anti-Corruption Layer (API Client)
              └── FinanceOne API (FastAPI on Vercel serverless)
                    └── Supabase PostgreSQL
```

### 통합 시작 조건 (Phase 4 시점에 재평가)

- [ ] Phase 2 (재무제표 생성) 완료 및 안정화
- [ ] Phase 3 (GAAP 변환/연결재무제표) 설계 확정
- [ ] DB 스키마 변경이 안정기 진입
- [ ] 핵심 테스트 golden dataset 확보 (복식부기, 재무상태표, 현금흐름, GAAP, CTA)
- [ ] ax-hub 모노레포 CI/CD 파이프라인 검증 완료

### 통합 시 실행 계획

**Phase A — 마이그레이션 준비**
1. PostgreSQL 프로시저로 핵심 트랜잭션 로직 래핑
2. TypeScript `decimal.js`로 Decimal 연산 레이어 구축 + Python golden dataset cross-validation
3. Supabase에 스키마 마이그레이션 (pg_dump → pg_restore)

**Phase B — 점진적 전환 (Strangler Fig)**
1. 읽기 전용 API부터 전환 (dashboard, statements 조회)
2. 쓰기 API는 DB 프로시저 + `supabase.rpc()` 경유로 전환
3. 각 단계마다 golden dataset으로 결과 비교 검증
4. 전체 전환 완료 후 Python 백엔드 제거

**Phase C — 최종 선택 (3가지 옵션)**
- (a) FinanceOne을 독립 마이크로서비스로 유지
- (b) 핵심 로직을 TypeScript로 포팅하여 ax-hub에 내재화
- (c) Supabase Edge Function + pg 직접 연결 하이브리드

## 6. 지금부터 준비할 것 (비용 거의 없음)

- [x] Neon 스키마가 표준 PostgreSQL → Supabase 호환 확인됨
- [x] entity_id 기반 설계 → Supabase RLS 정책 적용 용이
- [ ] OpenAPI 스펙 저장 (FastAPI `/docs`에서 자동 생성)
- [ ] 서버리스 10초 제한에 걸릴 작업 목록 정리
- [ ] ax-hub `packages/shared`에 공유 타입 선행 정의 (계정과목, GAAP 매핑)

## 7. Neon → Supabase DB 전환 (참고)

FinanceOne은 Neon 고유 기능을 사용하지 않음:
- Neon Serverless Driver 미사용 (psycopg2 사용)
- Neon Branching API 미사용
- Neon Pooler 미사용

**DB 전환은 `.env`의 `DATABASE_URL`을 Supabase 연결 문자열로 교체하는 수준.**
진짜 작업은 FastAPI 비즈니스 로직의 TypeScript 포팅.

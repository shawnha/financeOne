# 계정 트리 재설계 — 컨텍스트 노트 (결정·근거 누적)

작업 중 내린 결정과 이유를 계속 덧붙인다. 다음 세션이 재유도하지 않도록.

## 2026-06-07 — 운영 태그 3종 확정
- **결정**: 직교 운영 태그 = cost_behavior(고정/변동) · is_subscription(구독여부) · cost_center(부문/프로젝트). 담당자 제외.
- **이유**: 부문/프로젝트는 처음엔 보류였으나, 코리아 cost-center 분포 실측(마트약국10·ODD7·리테일4·3PL3)이 실사용을 증명 → 필요 확정. 담당자는 결제가 1인이라 분류 가치 없음. 구독여부는 이미 OpEx 구독관리 탭이 사용 중(키워드 감지) → 태그로 정식화.
- **모델 원칙**: 운영 태그는 **트리 부모가 아니다**. 표준 트리(통제계정)는 순수 GAAP 골격, 내부계정(보조 잎)은 standard_account_id로 매달림. 채널/사업(마트약국 등)은 자식이 여러 표준에 걸쳐 표준 부모가 못 되므로 cost_center 태그로 직교 분리.

## 2026-06-07 — 첫 액션 = 읽기전용 사전점검 스냅샷
- **결정**: Software Architect 정식설계로 바로 점프하지 않고, 먼저 DB 사실 스냅샷을 만든다.
- **이유**: 적대적 리뷰 2건이 공통으로 "사실 기반 사전점검표"를 요구. 마이그레이션 리스크(P0/P1)가 전부 실제 DB 상태에 의존 — 42 중복그룹의 정확한 FK 폭발반경, gaap_mapping 공백, 25300 8건의 실제 성격, 법인별 GL 유무/desync. 설계는 이 수치 위에서만 정확해진다. 읽기전용이라 리스크 0.

## 2026-06-07 — A(secret 로테이션) 종결
- 사장님 결정: 로테이션 안 함. 노출 범위가 로컬 세션로그+Anthropic 파이프라인뿐(공개 유출 아님), .env·Vercel 보관은 정상. 현 CODEF/Gowid/SsArt 자격증명 유지. (이 항목은 계정트리와 무관하나, 같은 세션 결정이라 기록.)

## 2026-06-07 — 사전점검 실측이 plan을 일부 뒤집음 (중요)
findings: `account-tree-preflight-2026-06-07.md`. plan 수정 사항.
- **25300 처리 변경**: plan은 "25300 선수금→미지급금 개명"이었으나 실측은 **개명 부적절**. 25300 실제 booking = 차량할부(현대캐피탈 ₩395,369×3)·매입 인보이스(LG유플러스 등) 오분류, **진짜 고객 선수금 0건**. 게다가 선수금 명칭이 3코드(20700/25300/25900) + 25300에 standard_account_keywords 67개. → 블라인드 개명 금지, 8건 개별 재분류 + 67키워드 재배선 + 선수금 canonical(결산권위, 25900 유력) 확정.
- **gaap_mapping 역전 확인**: 일부 canonical(고사용) 코드가 gaap=0인데 폐기 레거시가 gaap=1 보유(차량유지비 82200, 통신비 81400). 일원화 = gaap 이관 동반 필수(안 하면 연결서 누락). 한국 결산코드 ~12개가 사용>0·gaap=0.
- **마이그 P0 확정**: 홀세일 GL 0건(재무제표=transactions 단독)·HOI GL std 11/109·마감장치(is_closing/기간잠금 테이블) 전무 → 과거 재무제표 freeze 수단 부재. 정식설계서 기간잠금+remap감사+GL재전기 원자성 선설계 필수.
- **8 FK 테이블 확정**: 표준 폐기 시 transactions·internal_accounts·invoices·journal_entry_lines·mapping_rules·standard_account_keywords·transaction_splits·gaap_mapping 전부 트랜잭션내 재배선.
- **코리아 PoC 재확인**: 가장 깨끗(GL std 98%·NULL 22) → 1번 맞음. HOI 최후(desync·NULL 최악).

## 열린 결정 (정식설계에서 확정)
- transaction.standard: 도출(컬럼 제거) vs 동기화 유지 → **권장 동기화**(기존 쿼리 영향 최소). 사전점검 후 재확인.
- 표준 중복 deprecate vs 삭제 → **권장 is_active=false**(이력 보존).
- 롤업 권위: 현재 category/subcategory가 롤업 구동(parent_code 아님). 트리는 입력/UI용 유지 vs 진짜 트리롤업 구현 → 정식설계 결정.

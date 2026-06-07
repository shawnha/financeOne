# Changelog

All notable changes to FinanceOne will be documented in this file.

## [Unreleased] - 2026-06-08 — 계정 트리 재설계 UI 배선 (계정관리 표준 골격 뷰)

### Changed
- `backend/routers/accounts.py` — `list_internal_accounts`에 표준 `standard_category`·`standard_subcategory`·`standard_account_id`·`standard_sort_order` 추가. `list_standard_accounts`(entity 지정)에 `is_backbone`(entity_standard_accounts EXISTS) 추가
- `frontend/src/app/accounts/internal/page.tsx` — 내부계정 메뉴를 **parent_id(수입/지출) 트리 → 표준 골격 기반(카테고리 > 표준 > 잎)** 으로 재설계(목표 트리 = `docs/account_menu_mockup.html`). 빈 표준 골격도 "비어있음 · 거래 시 잎 추가"로 표시(entity_standard_accounts), 기능그룹은 잎 태그, 정리(평탄화/잡탕)된 "기타 X" 잎은 "정리됨" 마커, 골격 표준은 "골격" 배지, 미분류 잎은 "표준 지정 필요" 섹션. parent_id 드래그 정렬 제거(표준 그룹핑으로 대체)
- `frontend/src/components/account-combobox.tsx` — 거래내역 내부계정 선택 드롭다운을 **표준 골격 기준(표준 코드+이름 헤더 > 잎)** 으로 그룹핑(옵션에 표준정보 있을 때, 없으면 기존 parent_id fallback). 평탄화 후 길어진 잎 나열의 혼란 해소. `frontend/src/app/transactions/page.tsx` — InternalAccount 인터페이스에 표준 필드 추가

## [Unreleased] - 2026-06-08 — 계정 트리 재설계 M6a 잎 표준교정 + drift 정렬 (코리아, 재무 영향)

### Added
- `scripts/account_tree_m6a_korea_mapping.py` — 코리아(2) 잎 표준교정 + drift 정렬(2026 열림분). 결산 reconciliation + drift 성격분류 기반. JEL std라인 in-place 교체(§2.4, 99.2% PDF 보호). dry-run 기본·게이트(가짜매출 비탐지·debit==credit·잔여drift 0)

### Changed
- 코리아 거래내역 표준 정렬 — 불변식 #1(거래std=BS·잎=P&L = 복식부기 다른 다리 KEEP 60건, 스마트스토어 외상매출금 20건 포함, 결산 대조 확인). 명시 잎교정 5종: 차입금이자비용+이자지급3→이자비용93100(₩2.14M 영업외비용 신규)·카드대금 정식/선결제→26200 미지급비용·통신비 dedup 82800→81400·관리비 84000→81500·퇴직금 80500→80800. 휴리스틱 ALIGN 83건(판관비 내부정렬, 총액 불변)
  - prod 적용 완료(2026-06-08). 검증: 상품매출 ₩70.6M 불변·판관비 ₩656.3M 불변·debit==credit 어긋남0·잔여drift0. 2025 잠김 18·대여금 dup·차입금 엣지·tx7100(BS-only)은 후속

## [Unreleased] - 2026-06-08 — 계정 트리 재설계 M3 구조 정리 (코리아 내부계정 평탄화)

### Added
- `scripts/account_tree_m3_korea_structure.py` — 코리아(2) 내부계정 구조 정리. 멱등·dry-run 기본·각 행 이름/거래수 사전 단언. 재무 net 0(parent_id/name/is_active만, standard_account_id·거래·분개 불변)

### Changed
- 코리아 내부계정 트리 평탄화(123→117 활성). ①평탄화 8: 빈 그룹 6(매출·서비스매출·인건비·복리후생·임차료·수수료) 자식 위로+비활성 / 이중역할 2(교통·세금공과, 직접거래 보유) 자식 위로+"기타 여비교통비"·"기타 세금과공과금" 리네임(유지). ②잡탕 리네임 5(임차료→기타 지급임차료·사무용품→기타 사무용품비·이자수익→기타 이자수익·통신비→기타 통신비·법인세→기타 법인세등). ③죽은시드 0(코리아 시드 원본·후보 전부 backbone)
  - prod 적용 완료(2026-06-08). 검증: transactions 5373 불변·새 고아거래 0(기존 IA 373 Google Workspace 2건은 M3 무관). 채널그룹→cost_center·매핑교정은 M6/별도

## [Unreleased] - 2026-06-08 — 계정 트리 재설계 M2 마감 잠금 (코리아 2025 동결)

### Added
- `backend/alembic/versions/n0o1p2q3r4s5_account_tree_lock_triggers.py` — `trg_fiscal_period_lock_guard`(M1 생성)를 `transactions`·`journal_entry_lines`·`transaction_splits`에 BEFORE INSERT/UPDATE/DELETE 바인딩. 잠긴 (entity, period) 쓰기 거부, `financeone.allow_locked_write=on` 세션만 우회. 가역(DROP TRIGGER)
- `scripts/account_tree_m2_korea_lock.py` — 코리아(2) 2025-01~2025-12 `fiscal_period_locks` 등록(basis=both, 12행). 25년귀속 회계법인 신고완료 동결. 멱등·dry-run 기본
  - prod 적용 완료(2026-06-08). 통합테스트 7/7(코리아 2025 tx/UPDATE/split/JEL 차단·2026 통과·타법인 통과·bypass 허용) + 라이브 트리거 재검증. 2026 전체 열림(가결산 대조 가능). 재무 영향 0

## [Unreleased] - 2026-06-08 — 계정 트리 재설계 M4(표준6 추가) + M1b(코리아 51 골격) 적용

### Added
- `scripts/account_tree_m4_m1b_korea.py` — M4(표준 6 추가·18400 명칭) + M1b(코리아 51 표준 골격 ESA 등록) 멱등 적용 스크립트(dry-run 기본, `--apply`로 COMMIT). 정식설계 §3.5·§3.6·§1.1
  - 신규 표준 6 (전부 형제 계정 미러링, 결산 read-only 대조) — `80800 퇴직급여`·`83101 지급수수료(구매대행)`·`92200 사업양도이익`(코리아)·`81500 수도광열비`(홀세일)·`23100 영업권`·`26100 미지급세금`(리테일). 코리아 3개는 0거래 backbone placeholder → 재무 영향 0
  - `18400` 명칭 `회사설정계정과목` → `종속기업투자주식`(코드·category 고정, 순수 재라벨, 코쿼핏 ₩50M 정체 라벨 해소)
  - `entity_standard_accounts` 코리아(2) 51 골격 INSERT(source='settlement', is_backbone). 롤업 영향 0
  - prod 적용 완료(2026-06-08). 검증: ESA 51/51·코리아만·18400 라벨·internal_accounts·transactions 불변·트리거 바인딩 0

## [Unreleased] - 2026-06-08 — 계정 트리 재설계 M1 스키마 신설 (코리아 PoC 토대)

### Added
- `backend/alembic/versions/m9n0o1p2q3r4_account_tree_schema.py` — 계정 트리 재설계 M1 스키마 마이그레이션(가역, 기존 데이터 무변경). 정식설계 `docs/account-tree-redesign-design.md` §1·§2, 스코프 A'(plan-eng-review 2026-06-07)
  - `entity_standard_accounts` — 법인별 표준 골격(결산 union). 잎 없는 빈 GAAP 표준도 골격으로 유지. 롤업 영향 0(롤업 권위=category/subcategory)
  - `fiscal_period_locks` — 기간 동결(경량 historical 쓰기 가드). 2025-12 이하 잠금 대상(등록은 M2)
  - `canonical_remap` — 중복 표준코드 일원화 매핑(old→canonical, 같은 gaap_type 내). 채움은 M5
  - `remap_audit` — 행별 old→new 기록(batch_id 역재생). entity_id로 영향 법인 추적
  - `internal_accounts` +3 운영 직교태그 — `cost_behavior`(fixed/variable)·`is_subscription`·`cost_center`. 어떤 재무제표 롤업도 안 읽음 → 재무 숫자 영향 0
  - 트리거 함수 2종 `trg_fiscal_period_lock_guard`·`trg_sync_standard_from_internal` — **함수만 생성, 어떤 테이블에도 바인딩 안 함**(발화 0). 잠금 바인딩=M2, 표준 도출 sync 바인딩=M3(잎 교정 후, 불변식 #1)
  - prod 적용 완료(2026-06-08, dry-run+diff+명시승인 게이트 통과). 검증: 4테이블 rows=0·신규컬럼 3·is_subscription 0/560 TRUE·트리거 바인딩 0

## [Unreleased] - 2026-06-07 — clobe(클로브) 세금계산서 importer + 코리아 B2B 매출 정상화

### Added
- `backend/services/parsers/clobe_tax_invoice.py` — clobe.ai 세금계산서 다운로드 엑셀 파서. 국세청(홈택스) 직접 연동이 없어 clobe(공동인증서로 홈택스 수집)의 공식 "엑셀 다운로드"를 브릿지로 사용(스크래핑 불필요). '매출 매입 유형' 컬럼으로 direction 직접 판별, 음수=수정(취소) 세금계산서
- `backend/services/clobe_import_service.py` — 파싱 행을 `invoices`(source_kind='tax_invoice')로 멱등 적재. '내 사업자번호'→`entities.business_number` 매핑(멀티법인), **dedup 자연키 (entity, direction, 작성일자, 합계금액)** — 기존 tax_invoice 행이 counterparty_biz_no=NULL·vat=0·amount=합계로 저장돼 공통 신뢰 필드가 합계(total)뿐이라서
- `backend/routers/invoices.py` — `POST /api/invoices/import-clobe`(업로드 + dry_run + only_entity_id/only_direction)
- `backend/tests/test_clobe_tax_invoice.py` — 파서·자연키 dedup 단위테스트 13건

### Changed
- 한아원코리아(entity 2) 매출 정상화 — clobe 매출 세금계산서 신규 10건(2~4월, 공급가 ₩65.85M·세액 ₩6.58M·합계 ₩72.43M) prod 적재. Tier 1 배선 후 invoices만 읽던 `/pnl` 코리아 매출이 2월 ₩11.9M→₩62.5M·3월 ₩0.2M→₩10.8M·4월 ₩6.4M→₩17.5M로 정상화. 기존 1월 5건은 자연키 dedup으로 skip
  - 보류: 1월 수정세금계산서(−13.4M)는 기존 vat=0 legacy와 엉켜 세무 확인 후 별도. 매입 146건은 발생주의 재무제표 쪽으로 후속

## [Unreleased] - 2026-06-06 — 홀세일 외상매출(미수/수금율) SIMS 코드조인 정확화

### Changed
- `backend/services/receivables_service.py` — 한아원홀세일(entity 13)의 수금 집계를 은행 입금 이름매칭(payee_aliases) → **SIMS `customer_collections`(입금) 거래처 코드 기준**으로 전환. `summary`/`monthly`/`daily` 모두 분기(`_WHOLESALE_ENTITIES`). 다른 법인은 기존 로직 유지
  - 기존 이름매칭은 카드정산·점주 개인명 입금 ₩3.93B를 매칭 못 해 **수금 과소·미수 과대**였음. 코드조인은 매출 거래처 238/238 정합(customer_name==payee_name)
  - 정확 미수 = 2025 기초잔고 ₩150.4M + 매출 − 수금 = **₩283.0M**(수금율 97.8%). 이수마트 ₩71.7M 등 지난 대사와 원단위 일치

### Added
- 수금방식 분해 — 보통예금/카드결제/더샵몰/중외몰/새로팜 별 금액·건수·비중 (`collection_methods`)
- 과수금/선수금 거래처 섹션 — outstanding < 0 필터(기초 반영 후 전체기간 0건)
- `/receivables` 프론트(`receivables-content.tsx`) — 수금방식 분해 바·과수금 카드·홀세일 전용 부제

## [Unreleased] - 2026-06-06 — SsArt SIMS OpenAPI 연동 (한아원홀세일 매출/매입/입출금/거래처/제품 자동화)

### Added
- `backend/services/integrations/ssart.py` — SsArt(신성아트컴) SIMS OpenAPI 클라이언트. 수동 매출/매입관리 xlsx 업로드를 API 자동 pull로 대체
  - `SsArtClient` — 2단계 인증(ACCESS_TOKEN 2주 → USE_TOKEN 48h), **cp949(EUC-KR) 응답 디코딩**, 날짜별 페이지네이션(E0005/레이트리밋 회피)
  - 매출/매입: `sync_sales`/`sync_purchases` → 기존 `wholesale_service.import_*` 재사용(스키마 변경 0). `OUT_AMT/IN_AMT`=합계(VAT포함), 공급가는 TAX_YN 따라 ÷1.1 역산. dedup 키가 매출관리 xlsx(SIMS 생성물)와 동일 → 겹치는 기간 재sync 안전
  - 입출금: `sync_acc_trans` → 신규 `customer_collections`(거래처별 수금 raw 거래)
  - 기초자료: `sync_customers`/`sync_products` → 신규 `ssart_customers`(1283)·`ssart_products`(81)
- `backend/routers/integrations.py` — `POST /api/integrations/ssart/sync`(types=sales/purchase/collections/customers/products) + `GET /api/integrations/ssart/status`
- 일일 자동 동기화 — `cron_auto_sync`에 SsArt 추가(최근 7일 롤링 + 마스터). GitHub Actions `auto-sync.yml`(매일 KST 09:00)가 자동 호출, codef sync와 격리
- DB 마이그레이션 — `k7l8m9n0o1p2`(customer_collections), `l8m9n0o1p2q3`(ssart_customers/ssart_products)
- `backend/tests/test_ssart.py` — transform 단위테스트 11건(VAT 역산·면세·dedup 키·마스터)

### Notes
- 검증: 5/30 매출 67행·5/29 매입 7행이 기존 DB와 합계금액까지 정확 일치, SIMS 거래처원장과 원단위 정합. 가이드 PPT의 2개 함정 교정(응답 cp949·요청 flat 파라미터)
- 6월 매출 ₩11.7억·매입 ₩10.3억 + 1~6월 입출금 1872건 prod 적재. 이수마트 선수금 대사로 환불 처리 정합성 데이터 확증

## [Unreleased] - 2026-05-31 — 그룹 대시보드 환율 합산 하드닝 (가짜 $123M 총액 수정)

### Fixed
- 그룹 대시보드 환율 합산: 환율이 stale(>7일)일 때 `dashboard_service._fx_rate`가 `Decimal("1")`을 반환해 원화 잔고를 달러 총액에 1:1로 더하던 버그 수정. 그룹 총액이 가짜로 **$123,196,125**로 표시되던 것을 실제 환산값(**$87,765.97**)으로 정정
  - 이제 `ExchangeRateNotFoundError` 시 `get_historical_rate`(가용 환율 중 최근접, 역환율 1/rate 지원)로 폴백하고, 환율쌍 자체가 없을 때만 명시적으로 실패 (조용한 1:1 위조 금지)
  - `backend/tests/test_dashboard_service_unit.py` — 회귀 테스트 3건 추가 (same-currency / stale-uses-real-rate / no-rows-raises)
- (데이터) 프로덕션 환율 갱신 — 수출입은행 API로 5/13~5/29 backfill (USD/KRW 1505.80 @ 2026-05-29). 코드 diff 외 별도 데이터 작업

## [Unreleased] - 2026-05-20 — 거래내역 Excel 다운로드: 은행/카드 분리 + 한글 출처 라벨

### Added
- `backend/services/export.py` — `export_transactions_excel(conn, entity_id, year, month, kind='all'|'bank'|'card')`
  - `EXPORT_BANK_SOURCES` / `EXPORT_CARD_SOURCES` 상수 (cashflow_service 와 동일)
  - kind 별 SQL `source_type = ANY(%s)` 필터
  - 워크북 sheet 타이틀 / 상단 제목에 종류 표시 ("— 은행" / "— 카드")
- `SOURCE_LABELS` 매핑 — Excel 출처 컬럼에 한글 라벨 표시
  - `codef_woori_bank` → "우리은행" / `codef_lotte_card` → "롯데카드" 등
  - `codef_` 접두사 사라지고 사용자 친화적 명칭 (우리은행/IBK기업은행/신한은행/Mercury/수기입력/우리카드/롯데카드/신한카드)
- `backend/routers/transactions.py` `/export` — `kind` 쿼리 파라미터 추가
  - 파일명 suffix: `_은행` / `_카드` (all 은 suffix 없음)
- `frontend/src/app/transactions/page.tsx` — 드롭다운 메뉴 3개로 분리
  - "Excel 다운로드 (전체)" / "Excel 다운로드 (은행만)" / "Excel 다운로드 (카드만)"

## [Unreleased] - 2026-05-19 — 자금소요 일정 + 휴일 보정 + 자금 마련 필요 KPI

### Added
- `backend/utils/business_day.py` — 한국 영업일 보정 유틸 (`adjust_to_business_day`, `is_business_day`, `default_rule_for_account`)
  - `holidays==0.60` 패키지 의존, 연도별 `_kr_holidays` lru_cache
  - 룰 3가지: `none` / `before` (급여 통례, 휴일이면 앞당김) / `after` (4대보험·세금·카드결제, 휴일이면 미룸)
  - 다른 월로 넘어가면 같은 월 안의 반대 방향 영업일로 fallback
  - `default_rule_for_account` — 내부계정 이름 키워드 매칭으로 룰 자동 추정
- `forecasts.holiday_rule` 컬럼 (마이그레이션 `f2g3h4i5j6k7`) — `'none'|'before'|'after'` CHECK 제약
- `generate_daily_schedule` 응답에 `outflow_schedule[]`, `cash_gap`, `card_projection[]`, `last_actual_day` 신규 필드
  - `outflow_schedule`: 일별 출금 이벤트 + running balance + 휴일 보정 정보 (original_date/adjusted_date/shifted)
  - `cash_gap`: 첫 부족일 / 누적 최대 부족액 / `funding_needed` (월 전체 deficit 회피에 필요한 금액) / `funding_needed_by_date` (마감일)
  - `card_projection`: 전월 실제 사용액 기반 카드별 결제 추정
- `frontend/src/app/cashflow/forecast-tab.tsx` — `CashOutflowSchedule` 컴포넌트
  - cashGap 있을 때 빨간 그라데이션 헤더 + "⚠️ 자금소요 일정" + 자금 마련 필요 금액 + D-day 배지
  - 카드 결제 추정 inline display + 일별 출금 이벤트 펼치기/접기
  - 휴일 보정 적용된 항목은 `shifted` 플래그로 표시

### Financial accuracy
- `cash_gap` 계산은 출금 이벤트가 없는 날도 검사 (daily_undated_out 누적으로 잔고가 음수로 갈 수 있음)
- `funding_needed = max(deficit over remaining month)` — 한 번 마련하면 모든 부족일이 해결되는 최소 금액
- `running_balance` = 오늘까지 실제 잔고 + 오늘 이후 forecast 이벤트 누적

### Refactor
- `_build_forecast_item` 헬퍼 추출 — `_holiday_dates` 호출을 item당 1회로 통합 (기존 3회)

## [Unreleased] - 2026-05-18 — P&L entity 분기 (wholesale vs transactions)

### Fixed
- `backend/services/pnl_service.py` — 한아원코리아 (entity 2) / 한아원리테일 (3) / HOI (1) P&L 매출 0 으로 표시되던 버그
  - 기존: 매출/매출원가를 `wholesale_sales` 테이블에서만 조회 (entity_id=13 한아원홀세일 전용)
  - 수정: `_WHOLESALE_ENTITIES = (13,)` 도입, wholesale entity 외 법인은 `transactions` 의
    `s.category='수익' AND s.subcategory='매출'` (매출), `s.category='비용' AND s.subcategory='매출원가'` (매출원가) 합산
  - 영향 함수: `get_pnl_summary`, `get_pnl_daily`, `get_revenue_breakdown`, `get_cogs_breakdown`
  - VAT 처리: `standard_accounts.is_vat_taxable` 기반 (opex 와 동일 패턴), 과세 항목 /1.1
- breakdown group_by:
  - wholesale entity: 기존 `wholesale_sales.product_name` / `payee_name`
  - 그 외 entity: `transactions.counterparty` (payee), `standard_accounts.name` (product proxy)

### Verified
- 한아원코리아 2026-04: 매출 ₩25,539,480 (임성재(이수마트약국) 1건), 매출원가 ₩519,013 (주식회사 빌드 1건)
- 한아원홀세일 2026-04 회귀: 매출 ₩3,299,687,404 / 매출원가 ₩3,261,338,377 / 1,073건 변동 없음

### Notes
- 동반 DB row 변경 3건 (git untracked):
  - tx 21732 (2026-05-11 ₩100M 한아원홀세일 대여): standard_account 96000 잡손실 → 11400 단기대여금
  - tx 9053 (2026-04-03 채효리 ₩1.17M 상품매출): `is_cancel=true` + note (마진 0 의심 검토 보류)
  - tx 22178 (2026-04-13 주식회사 빌드 ₩519,013): 신규 insert (45100 상품매출원가, 임성재 매출 대응)
- 후속 작업 (별도):
  - `internal_accounts.id=510 "대여금"` default `standard_account_id=321 (잡손실)` → 단기대여금 (10900 / 11400) 으로 변경 필요. 결산자료 cross-check 후
  - 5월 entity 2 codef dedup: 14603/14604 (out, 하나임성재) — 14605/14606 (in, 임성재) 합쳐서 들어온 단일 거래의 중복. ₩45M 가짜 매출원가 inflation
  - entity 3 (한아원리테일) 매출 데이터 자체 부재 — P&L 0 정상

## [Unreleased] - 2026-05-08 — 외상매출금 페이지 신설 (payee_aliases 활용)

### Added
- `backend/services/receivables_service.py` — get_receivables_summary / get_receivables_monthly
  - payee_aliases + 자기 매칭 base 로 매출관리 vs 거래내역 입금 통합
  - 거래처별 발생/회수/외상/회수율 계산
  - 월별 추이 (누적 외상매출금 포함)
- `/api/receivables/summary` / `/monthly` endpoint
- `/receivables` 페이지 신설
  - 4 KPI 카드 (발생/회수/외상/회수율)
  - 월별 발생 vs 회수 + 누적 외상 듀얼 Y축 chart
  - 거래처별 detail (top 50, 회수율 색상 indicator)
  - alias 없는 입금 별도 섹션 (payee_aliases 보강 필요 알림)
- 사이드바 "외상매출금" 메뉴 추가 (TrendingDown 아이콘)

### Verified (한아원홀세일)
- 발생 매출 ₩7,547M / 회수 ₩2,517M / 외상매출금 ₩5,029M / 회수율 33.4%
- 월별: 1월 57% / 2월 53% / 3월 62% (도매업 특성 — 다음 달 회수)
- 4월 매출 ₩3.3B 는 5월부터 회수 시작
- 회수율 0% 거래처 다수 → payee_aliases 추가 매칭 필요 (다음 step)

## [Unreleased] - 2026-05-08 — 거래처명 별칭 + 매핑 direction 인지 + UI 명확화

### Added
- DB migration `x4y5z6a7b8c9` — `payee_aliases` 테이블 신설
  - `(canonical_name, alias)` 매핑 — 약국 사장 개인명 ↔ 약국 정식명 연결
  - 1차 자동 매칭 30건 등록 (예: "이희성(아이튼" → "동탄)아이튼튼약국")
  - ambiguous 8건 + no_match 39건은 향후 사용자 검토용
- DB migration `y5z6a7b8c9d0` — `mapping_rules.applicable_directions TEXT[]`
  - `['sales']` / `['purchase']` / NULL (전체) 로 룰 적용 방향 제한
  - 새로엠에스(주) 매출 룰 → sales 전용으로 정정 (매입 invoice 잘못 매핑 방지)
  - 기존 잘못 매핑된 매입 invoice 2건 NULL 처리 → 재매핑 시 정상 분류
- `auto_map_transaction(direction='sales'|'purchase')` 시그니처 + exact_match/similar_match 에 direction 필터링
- transactions auto-map endpoint: `type='in'` → sales / `out` → purchase 자동 매핑
- invoices auto-map endpoint: invoices.direction 그대로 사용

### Changed
- P&L 페이지 부제 명확화 — "운영 직관 view (현금주의 OpEx). 외상 거래/K-GAAP 정합은 재무제표 페이지"
- 1-3월 매입 invoices 31건 자동 매핑 + 4월 잘못 매핑된 6건 재매핑 (3건 정상화)

## [Unreleased] - 2026-05-07 — 옵션 ② VAT 면세/과세 분리 (K-GAAP 정합)

### Added
- DB migration `w3x4y5z6a7b8` — `standard_accounts.is_vat_taxable` BOOLEAN 컬럼 + 인덱스
  - 면세 항목 (`is_vat_taxable=false`): 80200 직원급여, 80500 잡급, 81700 세금과공과금, 93100 이자비용, 90100 이자수익
  - 그 외 비용 표준계정 = 과세 (default true)
- `pnl_service.get_pnl_summary` 의 `opex_excl_vat` 정밀 계산
  ```sql
  SUM(CASE WHEN s.is_vat_taxable THEN amount/1.1 ELSE amount END)
  ```
  - 인건비 (₩42M, 36% 비중) 면세 처리로 절대값 정확
  - K-GAAP 손익계산서 base 와 정합
- `operating_profit_excl_vat` / `net_income_excl_vat` 모두 새 `opex_excl_vat` 사용
- `pnl_monthly` 응답에도 `opex_excl_vat` 추가

### Verified (4월 한아원홀세일)
- VAT 포함 운영비 ₩37.8M / VAT 제외 ₩36.0M (면세 ₩17.9M 그대로 + 과세 ₩19.9M /1.1)
- VAT 포함 영업이익 +₩533K / VAT 제외 -₩1,172K
- 이전 옵션 ③ (운영비 그대로) 의 -₩2,952K 보다 ₩1,780K 정확화

### Why 옵션 ② 채택
PDF 가결산 손익계산서 (K-GAAP) 와의 정합성. 옵션 ① (일괄 /1.1) 은 인건비도 /1.1 처리해 ₩4M 가량 절대값 부정확. is_vat_taxable 분류는 향후 재무제표 페이지에서도 재사용.

## [Unreleased] - 2026-05-07 — 자동 매핑 표준/내부 분리 (Phase 0)

### Added
- `/api/transactions/auto-map` endpoint 에 `target` query param 추가
  - `internal`: internal_account_id 만 update
  - `standard`: standard_account_id 만 update
  - `both` (default): 둘 다 update (기존 동작)
- `only_unmapped=true` 모드도 target 별 NULL 컬럼 검사 (internal/standard/both 분기)
- 거래내역 페이지의 "자동 매핑" 메뉴를 dropdown sub-menu 로 분리
  - 둘 다 / 표준계정만 (회계) / 내부계정만 (사업) — 각 sub 메뉴에 "비어있는 것만" / "전체 재매핑"
- toast 메시지에 target 라벨 추가 (`표준계정 자동 매핑: 신규 N건...`)

### Why
표준계정 (K-GAAP 회계 분류) 과 내부계정 (운영/사업 분류) 은 서로 다른 결정. 함께 매핑하면 사용자가 표준만/내부만 부분 수정/검증하기 어려움. 분리로 세밀한 컨트롤 가능 — 옵션 B (VAT 정합) 작업의 전제 조건.

### Verified
- target=standard + only_unmapped=true → 표준계정 NULL 인 1건 매핑 ✓
- target=internal + only_unmapped=true → internal NULL 인 5건 중 4건 매핑 ✓
- target=both → 기존 동작 유지 ✓
- target=foo → 422 validation 에러 ✓

## [Unreleased] - 2026-05-07 — P&L VAT 포함/제외 toggle (K-GAAP 정합)

### Added
- `pnl_service.get_pnl_summary` 응답에 VAT 제외 필드 8개 추가
  - `revenue_excl_vat` (`SUM(supply_amount)`, NULL 시 `total_amount/1.1` fallback)
  - `cogs_excl_vat` = 매출 row × cogs_unit_price / 1.1 (cogs 단가는 VAT 포함 가정)
  - `purchases_total_excl_vat` (`SUM(supply_amount)`)
  - 파생: `gross_profit_excl_vat` / `gross_margin_pct_excl_vat` / `operating_profit_excl_vat` / `operating_margin_pct_excl_vat` / `net_income_excl_vat` / `net_margin_pct_excl_vat`
  - `pnl_service.get_pnl_monthly` 도 동일 필드 추가
- `pnl-content.tsx` 헤더에 `VAT 포함` / `VAT 제외 (K-GAAP)` toggle 버튼
  - localStorage `financeone-pnl-vat` 에 mode 저장 (mount 후 복원, hydration 안전)
  - KPI 카드 / P&L 표 / 월별 차트 / 집중도 분석 / 매입 section 모두 mode 반영
  - OpEx (판관비) / 영업외 (비용/수익) 은 거래내역 base 라 mode 영향 없음

### Verified (entity 13, 2026-04)
- VAT 포함: 매출 ₩3,299M / 영업이익 +₩533K (BEP 근접) / 순이익 -₩926K
- VAT 제외: 매출 ₩2,999M / **영업이익 -₩2,952K (적자)** / 순이익 -₩4,413K
- VAT 제외 view 가 사업의 진짜 손익 상태 드러냄 — VAT 포함 base 로 BEP 처럼 보이던 게 실은 적자

## [Unreleased] - 2026-05-07 — P&L 집중도 분석 (사업 리스크 시각화)

### Added
- `frontend/src/app/pnl/pnl-content.tsx` 에 `ConcentrationCard` 컴포넌트 추가
  - 제품별 매출 / 거래처별 매출 / 매입처별 매입 — top 5 의 가로 bar + list + 위험 indicator
  - 30% 초과 (제품/거래처 위험), 50% 초과 (매입처 critical) 시 red 알림 박스
  - 30% 미만 시 emerald "분산 양호" 표시
  - P&L 표 아래 / 매입 (도매) section 위에 배치
  - 한아원홀세일 (entity 13) 전용 — 다른 entity 는 sales_count=0 이라 자동 hide

### Verified (entity 13, 2026-04)
- 제품: 마운자로 5mg 37%, top 5 = 94.8% → 🔴 단일 제품 의존 위험
- 거래처: 동탄아이엠유 18.8% → 🟢 분산 양호
- 매입처: 유진약품 51.8%, top 5 = 98% → 🚨 절반 이상 단일 공급. 백업 공급선 필요

## [Unreleased] - 2026-05-07 — API 문서 URL 수정

### Fixed
- `docs/api-wholesale-upload.md` 의 production base URL 을 추측값 (`finance.hanah1.com`) 에서 실제 Vercel 배포 URL (`financeone-api.vercel.app`) 로 교체. curl/Python/Node 예시 모두 동일하게 수정.

## [Unreleased] - 2026-05-07 — API 문서에 key 발급/관리 절차 보강

### Added
- `docs/api-wholesale-upload.md` §1 인증 섹션에 4개 subsection 추가:
  - §1.1 API key 생성 (openssl/PowerShell/Python 명령)
  - §1.2 Vercel env 설정 (Dashboard + CLI 절차)
  - §1.3 외부 프로그램 전달 — 권장/금지 채널
  - §1.4 회전 (Rotation) 권장 주기와 절차
  - §1.5 보안 체크리스트
  - §1.6 향후 다중 key/rate limit 계획

## [Unreleased] - 2026-05-07 — 도매 업로드 alert + 외부 자동 업로드 API 문서

### Added
- `wholesale_service.compute_sales_alerts` / `compute_purchases_alerts` — 회계 이상 패턴 감지
  - 매출 3종: 매입가(장부) ≠ 매입가(실), 마진 음수 (손실 판매), 매입가 누락
  - 매입 2종: 매입단가 장부 vs 실 차이, 매입단가 누락
- `wholesale_service.ImportResult` 에 `alerts` 필드 추가
- `/api/upload/wholesale-sales` / `/api/upload/wholesale-purchases` 응답에 `alerts` 노출
- `frontend/src/components/wholesale-upload.tsx` 에 `AlertsPanel` 컴포넌트 — details/summary 패턴, top 10 row 노출
- `backend/utils/auth.py` — 옵션 API key 인증 (env `FINANCEONE_API_KEY` 설정 시만 강제)
- `docs/api-wholesale-upload.md` — 외부 자동 업로드 API 문서 (curl/Python/Node 예시, cron 패턴, 에러 처리)

### Verified (한아원홀세일 entity 13, 4월)
- 손실 판매 20건 감지 (매입가 오기재 의심 / 재고 처분)
- 매입가 누락 20건 (매출원가 미반영)
- 매입가 장부≠실 1건 (₩0 무시 가능)

## [Unreleased] - 2026-05-07 — transactions hydration 에러 fix

### Fixed
- `useGlobalMonth` (`hooks/use-global-month.ts`) useState initializer 가 `typeof window` 분기로 localStorage 즉시 읽음 → SSR ("2026-05") vs CSR (localStorage="2026-04") mismatch. `currentMonth()` 로 시작 → useEffect 에서 localStorage 복원으로 변경.
- `transactions/page.tsx:336` 동일한 안티패턴 (filters initial state 에서 localStorage 즉시 읽기) 제거. 기존 `globalMonth sync effect (line 380)` 가 마운트 후 filters 동기화.

### Verified
- 콘솔 hydration 에러 0건 확인 (이전 도메인당 수십개 mismatch + Error: Hydration failed)
- 페이지 정상 로드, 데이터 fetch 정상

## [Unreleased] - 2026-05-07 — P&L 월별 매출 vs 매출원가 vs 매입 비교 chart

### Added
- `pnl_service.get_pnl_monthly` 응답에 `purchases_total` / `gross_margin_pct` / `sales_count` / `purchases_count` 추가
- frontend pnl-content.tsx 에 신규 ComposedChart Card "월별 매출 · 매출원가 · 매입 추이"
  - grouped bar 3종 (매출/매출원가/매입) + 매출총이익률 line (우측 Y axis %)
  - tooltip: 건수, 매출 대비 비율, 매출총이익, 매출총이익률 통합 표시
  - bar 클릭 시 선택 월 전환 (기존 chart 와 동일 패턴)

### Verified (entity 13, 2026-04)
- 매출 ₩3,299,687,404 / 매출원가 98.8% / 매입 103.3% / 매출총이익률 1.16% — 한눈에 마진 압박 인지 가능

## [Unreleased] - 2026-05-07 — P&L 매출/매입 drilldown (제품·거래처별 분석)

### Added
- `backend/services/pnl_service.py` — `get_revenue_breakdown` / `get_cogs_breakdown` / `get_purchases_breakdown`
  - `_breakdown_rows` 헬퍼: top N rows + 기타 + 합계 형식
  - `group_by`: `'product'` (제품명) | `'payee'` (매출은 거래처 / 매입은 매입처)
- `backend/routers/pnl.py` — 3 신규 endpoint
  - `GET /api/pnl/revenue-breakdown?entity_id&year&month&group_by&limit`
  - `GET /api/pnl/cogs-breakdown` — 매출 row × cogs_unit_price 기준 매출원가 분석
  - `GET /api/pnl/purchases-breakdown` — `wholesale_purchases` 기준 매입 분석
- `frontend/src/app/pnl/pnl-content.tsx`
  - `BreakdownPanel` 컴포넌트: 기준 toggle (제품별/거래처별) + top N + 기타 + 합계 row
  - 매출/매출원가 PnlRow → expandable + lazy fetch (영업외비용 패턴 동일)
  - 매입 (도매) section 신설 — P&L 표 하단 별도 Card (KPI subtext 노출만 됐던 매입 정보 drilldown 가능)
  - 월/entity 변경 시 drilldown 캐시 무효화

### Verified (한아원홀세일 entity 13, 2026-04)
- 매출 drilldown 합계 ₩3,299,687,404 = `summary.revenue` ✓
- 매출원가 drilldown 합계 -₩3,261,338,377 = `-summary.cogs` ✓
- 매입 drilldown 합계 ₩3,409,300,549 = `summary.purchases_total` ✓
- 인사이트: 마운자로 4종 = 매출 90.6% / 유진약품 1곳 = 매입 51.8% (집중도 높음)

## [Unreleased] - 2026-05-01 — Codef 공공기관 + 카드 청구서 (Phase 2/3/4)

### Added — Phase 4 (카드 청구서)
- `card_billings` 테이블 (Alembic `t0u1v2w3x4y5`)
- `CodefClient.get_card_billings` + `sync_card_billings`
  - Codef `/v1/kr/card/b/account/billing-list`
  - `_normalize_card_billing_row` (resCardNo / resBillingMonth / resPaymentDate)
- `POST /api/integrations/codef/sync-card-billing`
- `GET /api/integrations/card-billings?entity_id&months`
- 신규 frontend 페이지 `/card-billings` + 사이드바 메뉴 "카드 청구서"

### Added — Phase 2 (사업자번호 검증)
- `CodefClient.check_business_status(biz_no)` — Codef `/v1/kr/public/nt/business/status`
- `POST /api/integrations/codef/business-status` — `{biz_no: '1968103665'}` 입력
- 응답: 휴폐업 상태, 과세유형, 상태 변경일 등

### Added — Phase 3 (국세 납부내역)
- `CodefClient.get_tax_payment_list` — Codef `/v1/kr/public/nt/payment/payment-list`
- `POST /api/integrations/codef/tax-payments`
- `tax_type`: `all` / `vat` (부가세) / `corporate` (법인세) / `income` (원천세)
- 응답: 세목/납부일/금액/상태 정규화 list (DB 저장 X, 조회용)

### Notes
- Phase 2/3 endpoint 동작 검증은 Codef demo quota (CF-00012 일 100건) 리셋 후 가능
- Phase 2/3 frontend UI 는 추후 — 사업자번호 검증 버튼 (invoice form 옆), 부가세 위젯 (dashboard) 등

## [Unreleased] - 2026-05-01 — 세금계산서 ↔ 플랫폼 매출 분리 (Phase 1)

### Added
- `invoices.source_kind` 컬럼 (Alembic `s9t0u1v2w3x4`)
  - `'tax_invoice'` (홈택스/직접) / `'platform_sales'` (NAVER/Shopify 등) / `'manual'`
  - `(entity_id, source_kind)` 인덱스
  - backfill: `note LIKE 'salesone:%'` + NAVER/SHOPIFY/AMAZON/TIKTOK counterparty → `'platform_sales'`
- `GET /api/invoices?source_kind=tax_invoice|platform_sales|manual` 필터
- list_invoices 응답에 `source_kind` 노출

### Changed
- `create_invoice` 함수에 `source_kind` 파라미터 추가 (default `'tax_invoice'`)
- `salesone.sync_orders_to_invoices` 가 `source_kind='platform_sales'` 명시
- `codef.sync_tax_invoices` 가 `source_kind='tax_invoice'` 명시 (홈택스 통합조회)
- frontend 세금계산서 페이지가 `source_kind=tax_invoice` 만 호출 — NAVER 등 플랫폼 매출 제외

### Verified (production DB after backfill)
- HOK invoices 269건 → tax_invoice 44 + platform_sales 225 분리
- 세금계산서 화면 = 진짜 세금계산서 44건만 (이전 269건 모두 표시 → 정정)

## [Unreleased] - 2026-04-30 — ExpenseOne 매칭 N:M 지원 (분할/합산)

### Added
- `transaction_expenseone_match` 1:1 → N:M (Alembic `r8s9t0u1v2w3`)
  - 기존 `expense_id` UNIQUE 제거 → 복합 `(expense_id, transaction_id)` UNIQUE
  - 1 expense ↔ N transactions (분할 결제) 또는 N expenses ↔ 1 transaction (집합 입금) 가능
- `POST /expenseone-match/expenses/{expense_id}/confirm` body 확장
  - `transaction_ids: list[int]` 받아 분할 매칭
  - `replace_existing: bool` (default true) — 기존 매칭 정리 후 재등록
  - 자동 method `manual_split` 라벨링 + reasoning 자동 생성
- `POST /expenseone-match/transactions/{transaction_id}/match-group` 신규 endpoint
  - 여러 expense 를 단일 transaction 에 일괄 매칭 (N → 1)
- list_expenses 응답에 `match.count` 노출 — 분할 매칭 건수
- 거래내역 페이지 `matchStatusBadge` 에 `(분할 N)` 라벨

### Changed
- 매칭 후보 패널 ("분할 매칭" 체크박스 토글)
  - ON 시 각 후보 행에 체크박스 등장
  - footer 에 선택 N건 합계 + expense.amount 비교 (정확 일치 ✓ 표시)
  - "{N}개 합산 매칭" 버튼 — 2건 이상 선택 시 활성화

### Notes (다음 세션)
- Reverse UX (N expense → 1 transaction UI) 는 backend endpoint 만 준비됨
- expense list 다중선택 + tx ID 검색 UI 후속 작업

## [Unreleased] - 2026-04-30 — 표준계정 자동매핑 + 거래 자동매핑 옵션 + K-GAAP 14개 보강

### Added
- K-GAAP standard_accounts 14건 보강 (Alembic `p6q7r8s9t0u1`)
  - 단기대여금 11400, 미수수익 11600, 선급비용 13300, 선수금 25900,
    단기차입금 26000, 장기차입금 29300, 통신비 81400, 전력비 81600,
    수선비 82000, 차량유지비 82200, 교육훈련비 82500, 도서인쇄비 82600,
    건물관리비 83700, 이자비용 93100
  - HOW seed 39 → 53 완성, keywords 18 → 매핑 가능
- `POST /api/accounts/internal/auto-map-standard` — 표준계정 자동매핑 endpoint
  - 매칭 0순위: internal_code = standard_code 정확 매칭 (confidence 0.99 즉시 채택)
  - 1순위: name similarity (pg_trgm) + counterparty 빈도 통계 (2025 결산 keywords 학습)
  - 가중치 동적 조정 — kw 신호 있으면 0.4 name + 0.6 kw, 없으면 0.9 name 단독
  - preview/apply 모드 + only_unmapped 토글 + min_confidence 슬라이더
  - reason 필드 (`exact_code_match` / `name_sim+kw_freq` / `name_sim_only`)
- 내부계정 페이지 "표준계정 자동매핑" 버튼 + Dialog
  - 미리보기에 entity GAAP/대상/채택/미달 + 후보별 reason/conf 표시 (최대 30건 스크롤)
- 거래 페이지 "자동 매핑" 메뉴 두 갈래로 분리
  - "비어있는 것만" — `only_unmapped=true`, 기존 매핑 보존
  - "전체 재매핑" — 기존 동작 (manual/confirmed 빼곤 모두 갱신)

### Changed
- `POST /api/transactions/auto-map?only_unmapped=true|false` 쿼리 파라미터 추가
  (default false — backward compat)

## [Unreleased] - 2026-04-30 — 2025 확정 결산자료 기반 standard_accounts/keywords/HOW seed

### Added
- HOI 실제 운영 COA 85건으로 교체 (`backend/scripts/import_hoi_finalized_coa.py` + `seed_data/hoi_coa_2025.py`)
  - source: `BS_123125_Finalized_032026.pdf` + `PL_123125_Finalized_031926.pdf`
  - 코드 체계: `HOI-BS-####` / `HOI-PL-####` (parent 33 + leaf 52)
  - 기존 generic US-GAAP placeholder 61건 비활성화 (data 보존)
- K-GAAP `standard_account_keywords` 1593 신규 (`backend/scripts/import_kgaap_ledger_keywords.py`)
  - source: 한아원코리아 25년 + 도팜인 24·25년 = 3년치 142시트 36,440건
  - vendor 별 최빈 standard_code 매핑, confidence = 빈도 비율 보정
- HOW(한아원홀세일) `internal_accounts` 39건 seed (`backend/scripts/seed_how_from_dopamin_25.py`)
  - source: 도팜인 25년 ledger 시트명 53개
  - 14건은 K-GAAP standard_accounts 누락 코드(통신비 81400 등)로 skip — follow-up

### Notes (다음 세션)
- K-GAAP standard_accounts 14개 누락 코드 보강 필요 (단기대여금 11400, 미수수익 11600, 선급비용 13300, 선수금 25900, 단기차입금 26000, 장기차입금 29300, 통신비 81400, 전력비 81600, 수선비 82000, 차량유지비 82200, 교육훈련비 82500, 도서인쇄비 82600, 건물관리비 83700, 이자비용 93100)
- 위 보강 후 `seed_how_from_dopamin_25 --apply` 재실행 시 39 → 53 완성

## [Unreleased] - 2026-04-30 — Codef 신한은행 지원 (한아원홀세일 등)

### Added
- Codef BANK_ORGS 에 `shinhan_bank` (신한은행 BizBank) 추가
  - ORG_CODES: `0088` (Codef 표준 신한은행 코드)
  - ORG_LABELS: "신한은행"
  - VALID_CODEF_ORGS allowlist 도 갱신
- frontend `CodefOrg` type + `CODEF_ORG_LABELS` + `CODEF_ORG_ORDER` + `CODEF_BANK_ORGS` 에 신한은행 등록

### Changed
- `CodefClient.get_bank_account_list / get_bank_transactions / sync_bank_transactions`
  에 `org` 파라미터 추가 (default `"woori_bank"` — backward compat)
  - source_type 동적 결정 (`codef_woori_bank` / `codef_ibk_bank` / `codef_shinhan_bank`)
  - balance_snapshots account_name 도 org 기반 동적 ("우리은행 법인통장" / "신한은행 법인통장" 등)
  - 체크카드 cross-dedup ('체크우리') 은 woori_bank 한정으로 제한
- `POST /api/integrations/codef/sync-bank` 가 `organization` 필드 받아 동적 sync (미지정 시 woori_bank)
- scheduler `codef_sync_job` 이 `org` 인자를 sync_bank_transactions 에 전달
- frontend `syncCodefOrg`: 은행 판정을 `CODEF_BANK_ORGS.has(org)` 로 일반화 + organization 필드 POST body 에 포함

### Notes
- 한아원홀세일에서 신한은행 BizBank 인증서로 connected_id 등록 후 정상 sync 가능 예정
  (Codef 응답 구조는 우리은행과 동일 가정 — 첫 sync 후 검증 필요)

## [Unreleased] - 2026-04-30 — standard_accounts GAAP 분리 (US-GAAP COA 추가)

### Added
- `standard_accounts.gaap_type` 컬럼 추가 (`K_GAAP` | `US_GAAP`, default `K_GAAP`)
- US-GAAP COA 61건 seed (gaap_mapping 의 distinct us_gaap_code 추출)
  - normal_side 휴리스틱: 1xxx/5xxx → debit, 그 외 → credit
- `GET /api/accounts/standard?entity_id=X` 가 entity.type 기반 gaap_type 자동 필터
  - `US_CORP` (HOI) → US_GAAP
  - `KR_CORP` (HOK/HOR/HOW) → K_GAAP
  - `?gaap_type=US_GAAP|K_GAAP` 명시 override 가능
- 응답에 `gaap_type` 필드 노출

### Changed
- `code` UNIQUE 제약 → `(code, gaap_type)` 복합 UNIQUE (US/K-GAAP namespace 분리)
- `parent_code` FK 제거 (단일 unique 깨짐 → application-level 트리)
- 기존 `WHERE code = X` lookup 모두 `AND gaap_type = 'K_GAAP'` 명시
  - `bookkeeping_engine._get_cash_account_id`, `_get_accounts_payable_id`
  - `invoice_service._lookup_account_id`
  - `salesone.py` sales_acc 조회
  - `statements/cash_flow.py` 현금 잔액 4 곳 (10100)
- `standard_account_recommender`: US_CORP entity 는 keyword_dict 단계 skip
  (현재 keyword 사전이 K-GAAP 가정이라 잘못된 추천 방지)

### Notes (다음 세션)
- HOI 의 internal_accounts 40 건은 여전히 K-GAAP standard 를 가리킴 → 수동 재매핑 필요
  (자동 매핑은 신뢰도 부족, 검토 후 진행)

## [Unreleased] - 2026-04-30 — 한아원홀세일(HOW) 법인 추가 + Codef 동적 법인 리스트

### Added
- 4번째 법인 `HOW` (주식회사 한아원홀세일) 추가
  - Alembic 마이그레이션: `n4o5p6q7r8s9_add_how_entity.py` (ON CONFLICT idempotent)
  - `seed.py`: 4 entities 로 업데이트
  - 그룹 구조: HOI(US 모회사) → HOK / HOR / HOW (한국 자회사 3개)

### Changed
- 설정 페이지 Codef 법인 선택을 entities API 기반 동적 리스트로 전환
  - 기존 hardcoded `[{id:2}, {id:3}]` → `KR_CORP` + `is_active` 필터링된 entities
  - 향후 한국 법인 추가 시 코드 수정 없이 자동 등장

## [Unreleased] - 2026-04-30 — 내부 계정과목 다른 회사 복사 기능

### Added
- 내부 계정과목 페이지에 "다른 회사에서 복사" 기능
  - `POST /api/accounts/internal/copy` — source/target 법인 지정, depth 기반 정렬로 부모-자식 관계 보존
  - 모드: `merge`(같은 code skip, 추천) / `replace`(기존 비활성화 후 복사)
  - 옵션: 표준계정 매핑 / 고정설정(is_recurring) 포함 여부 토글
  - `preview: true` 로 시뮬레이션 후 rollback — 실행 전 변경 건수 미리보기
  - 단일 트랜잭션 원자성, code unique 충돌 자동 처리

## [Unreleased] - 2026-04-29 — Codef 자동 sync 마지막 실행 시각 노출 (Vercel 호환)

### Added
- 자동 sync 스케줄러: 기관별 마지막 sync 시각을 DB(`settings.codef_last_sync_*`) 영구 기록 기반으로 표시
  - `GET /api/integrations/codef/scheduler/status` 응답에 `last_sync_by_target[]`, `serverless` 필드 추가
  - 설정 페이지 → 통합 → 자동 sync 카드 안에 "기관별 마지막 sync (DB 영구 기록)" 섹션 + 상대시간(예: "3시간 전")
  - Vercel 배포(스케줄러 비활성, cold start 회피)에서도 마지막 시각 정상 표시 + serverless 안내 배너

## [Unreleased] - 2026-04-19 — Codef 카드 파싱 + 프로덕션-레디 연동

### Added
- Codef 카드 승인내역 파싱 (롯데/우리/신한) — `sync_card_approvals` + 정규화 파이프라인
- Codef 샌드박스↔프로덕션 환경 토글 (`CODEF_ENV` / `CODEF_BASE_URL`)
- Codef `create_connected_id` — id/pw 및 공동인증서 기반 연계 계정 등록
- Codef connected_id settings 저장 (`codef_connected_id_{org}` 키)
- Codef API: `POST /codef/connect`, `GET/POST/DELETE /codef/connections`
- 설정 페이지 Codef 카드 확장 — 환경 배지, 기관별 연결 상태·동기화·해제 버튼, 기간 선택
- 36개 Codef 테스트 (정규화·환경 토글·중복감지·설정 저장·sync 플로우)

### Changed
- Codef sync 엔드포인트: connected_id 미지정 시 settings에서 자동 조회
- 카드 source_type: `codef_{card_type}` (예: `codef_lotte_card`) — Excel 업로드와 구분
- 은행 source_type: `codef_woori_bank` (기존 `codef_api`에서 변경)

## [Unreleased] - 2026-04-08 — Slack 컨텍스트 매핑 + UX 개선

### Added
- mapping_rules에 Slack 컨텍스트 컬럼 추가 (description_pattern, vendor, category)
- 거래내역에서 내부계정 변경 시 Slack 매칭 정보 자동 학습
- 거래처+description 조합으로 복수 매핑 규칙 지원 (같은 거래처도 항목별 다른 계정 가능)
- 거래내역 일괄 취소 처리 버튼 (is_cancel 토글)
- 거래내역 내부계정 필터 드롭다운
- 멤버 카드번호 매칭 fallback (이름 매칭 실패 시 card_number로 연결)
- 멤버 이름/카드번호 변경 시 기존 거래 자동 재연결
- 체크카드 양방향 중복 감지 (우리은행 ↔ 우리카드)
- 예상 페이지 + 거래내역에서 내부계정 인라인 추가 (AccountCombobox)
- Warnings 카드 (잔고 부족 + 예산 초과 통합, 접기/펼치기)
- 거래 단건 조회 API에 entity_id 추가

### Changed
- is_cancel 필터를 모든 집계 쿼리에 적용 (대시보드, 현금흐름 14곳, 분개, 법인간 거래)
- 잔고 부족 경고: 매일 반복 → 처음 마이너스 되는 날만 1건
- Slack 매칭 카드 상단 KRW 금액: parsed_structured.total_amount_krw 우선
- 매칭 후보 통화 표시: t.currency 대신 entity_id 기반 (HOI=USD, 한국=KRW)
- Slack 동기화 속도 개선: 변경 없는 메시지(텍스트+reply_count+structured 동일) 완전 스킵
- useGlobalMonth: 초기값을 localStorage에서 즉시 읽기 (페이지 네비게이션 시 월 동기화 개선)
- PRD: Neon → Supabase, Railway 제외 반영, Phase 1/2 진행 상태 표시

### Fixed
- 8건 기존 체크우리 중복 거래 취소 처리 (Slack/거래 정합성 회복)
- 75개 매핑 규칙에 Slack 컨텍스트 소급 적용 (12월~3월)

## [0.7.1] - 2026-03-31 — 다중 항목 개별 매칭

### Added
- Slack 메시지의 다중 비용 항목을 각각 별도 거래에 개별 매칭하는 워크플로우
- 후보 패널에 [전체 매칭] / [개별 매칭] 탭 (shadcn/ui Tabs)
- 항목 테이블: 클릭 시 해당 금액 기준 후보 검색, 개별 확정
- 확정 후 자동으로 다음 미매칭 항목 이동 + 토스트 알림
- 메시지 카드에 매칭 진행률 Badge (예: 2/3)
- 개별 매칭 확정 취소(undo) 기능
- 부분 매칭 메시지 무시 시 경고 다이얼로그 + 매칭 레코드 자동 정리

### Changed
- transaction_slack_match 테이블에 item_index, item_description 컬럼 추가
- confirm API에 item_index/item_description 파라미터 지원
- candidates API에 item_index 쿼리 파라미터 지원
- list_messages 응답에 item_matches, match_progress 필드 추가
- 메시지 상태에 partial (부분 매칭) 추가

## [0.7.0] - 2026-03-30 — Slack 구조화 파싱 엔진

### Added
- **Claude Sonnet 구조화 파싱** — Slack 경비 메시지를 자동으로 구조화된 JSON으로 변환
  - vendor, category, 항목별 금액, VAT, 원천징수, 선금/잔금 추출
  - sync 시 자동 호출 (신규/변경 메시지만, 기존 건 스킵)
  - `parsed_structured` JSONB 컬럼으로 저장
  - Claude API 실패 시 기존 regex 결과로 fallback
- **Slack 카드 구조화 테이블** — 카드 펼침 시 항목/VAT/원천징수/결제조건 테이블 표시
- **원문 보기 토글** — 구조화 데이터 아래 원문 텍스트 접기/펼치기

### Changed
- **카드 접힌 상태** — 날짜를 이름 앞에 배치 (날짜순 정렬 기준)

## [0.6.1] - 2026-03-28 — 현금흐름 UI 재설계 (mockup 반영)

### Changed
- **탭 1 (실제 현금흐름) 차트**: Bar+Line -> Bar+Area 복합 차트, 선택 월 강조 (opacity 1 vs 0.35), 순현금흐름 Area fill (amber gradient)
- **탭 1 거래 리스트**: 5컬럼 그리드 (날짜/유형/항목/금액/잔고) + mockup 스타일 시작/기말 잔고 행
- **탭 2 (예상 현금흐름)**: 차트 제거, 안내 note box 추가, 테이블 전용 레이아웃
- **KPI 카드**: mockup 스타일 (10px uppercase label, 17px mono value)
- **전반적**: rounded-2xl 카드, 10px uppercase 헤더, mockup 색상/간격 반영

## [0.6.0] - 2026-03-26 — Supabase 마이그레이션 + 백엔드 리팩토링

### Changed
- **DB: Neon → Supabase** — hanahone-erp 프로젝트 (kxsofwbwzoovnwgxiwgi), financeone 스키마
- **connection.py** — SET search_path TO financeone, public + 로깅
- **schema.sql** — IF NOT EXISTS, base_currency 컬럼, idx_tx_file_id 인덱스, NULLS NOT DISTINCT
- **EXTRACT → range queries** — 11개 EXTRACT(YEAR/MONTH) → date >= / date < 변환 (인덱스 활용)
- **fetch_all 유틸** — 14개 파일 24개 위치의 cols/dict(zip) 패턴 → fetch_all(cur)
- **statement_generator 분리** — 1074줄 → 7 모듈 (balance_sheet, income_statement, cash_flow, trial_balance, deficit, consolidated, helpers)
- **upload dedup** — O(n²) → O(1) set 기반 중복 체크 (dedup_service.py)
- **하드코딩 제거** — ENTITIES dict, HOI_ENTITY_ID, CASH_ACCOUNT_CODE, EQUITY_INCEPTION_DATE → DB/env
- **VERSION 파일** — main.py 버전 하드코딩 → VERSION 파일 (0.5.0)
- **에러 핸들링** — dashboard, cashflow, intercompany 라우터 try/except + 파서 로깅

### Added
- `backend/utils/db.py` — fetch_all(), build_date_range() 유틸
- `backend/services/dedup_service.py` — O(1) 중복 감지 서비스
- `backend/services/statements/` — 7개 모듈로 분리
- `backend/tests/test_api_integration.py` — API 통합 테스트 10개
- 총 80 tests (70 기존 + 10 통합)

## [0.5.0] - 2026-03-26 — 현금흐름 3탭 재설계 + 프로덕션 배포

### Added
- **현금흐름 3탭 UI** — 실제/예상/비용 탭 구조 (green/amber/purple 색상 코딩)
- **cashflow_service.py** — 기초잔고 역산, 일별 running balance, 월별 요약, 카드 그룹핑, 시차보정 엔진
- **4 Cashflow API** — `/actual` (일별 거래+잔고), `/summary` (월별 차트), `/card-expense` (카드 그룹핑), `/forecast` (시차보정)
- **Forecasts CRUD API** — 예상 입금/출금 항목 생성·수정·삭제 (`/api/forecasts`)
- **card_settings 테이블+API** — 카드 결제일, 카드사 정보 관리 (`/api/card-settings`)
- **실제 현금흐름 탭** — ComposedChart(Bar+Line) + KPI 4개 + 거래 드릴다운 리스트 + 월 pill 네비
- **예상 현금흐름 탭** — forecast 항목 테이블 (7컬럼 토글) + 입력 모달 + 시차보정 박스 + 공식 표시
- **비용 (카드) 탭** — 카드/회원 아코디언 + 내부계정 breakdown + 월별 비교
- **opening_balance 저장** — 우리은행 Excel 업로드 시 기초잔고도 balance_snapshots에 저장
- **프로덕션 배포 설정** — Railway (nixpacks.toml, Procfile) + Vercel (vercel.json)
- **통화 포맷** — HOI=$, 한국법인=₩ entity-aware 포맷팅
- **Excel 파싱 개선** — 역순 정렬 처리, 동일키 중복 허용, 7가지 파싱 로직 수정
- 16 new pytest cases (cashflow) — 총 70 tests
- design-system/pages/cashflow.md 디자인 사양 문서

### Changed
- DB: 20 → 21 테이블 (card_settings 추가)
- dashboard.py → cashflow 엔드포인트를 전용 라우터로 분리
- cashflow/page.tsx → 3탭 셸로 교체
- Geist/Geist Mono 폰트 적용 (IBM Plex에서 전환)

### Fixed
- Recharts Bar opacity 함수 prop → 사전 계산 값으로 수정
- 우리은행 Excel 역순 정렬 시 기초/기말 잔고 뒤바뀜

## [Unreleased]

## [0.3.0] - 2026-03-23 — Phase 3: 3개 법인 연결재무제표

### Added
- **연결재무제표** — US GAAP 기준, USD 통화, 3법인 합산 + 내부거래 상계 + CTA
- **CTA 엔진** — 자산/부채=기말환율, 수익/비용=평균환율, 자본=역사적환율, 차이→AOCI(30400)
- **환율 서비스** — 기말/평균/역사적 환율 조회, 공휴일 직전 영업일 fallback (7일 이내)
- **GAAP 변환** — K-GAAP → US GAAP 코드 매핑 (gaap_mapping 테이블 활용)
- **내부거래 감지** — 자동 매칭 (금액+날짜±1일+반대타입) + 수동 확인 + 상계
- **환율 관리 API** — CRUD + closing/average 환율 조회 엔드포인트
- **내부거래 API** — detect/pairs/confirm/reject 엔드포인트
- **연결 탭** — EntityTabs "연결" 활성화 (보라색, entity=consolidated, USD 포맷)
- **사이드바** — "법인간 거래" + "환율 관리" 메뉴 추가
- **감사 추적** — consolidation_adjustments 테이블 (CTA, 상계, GAAP 변환 기록)
- 16 new pytest cases (환율 8 + 내부거래 2 + CTA/GAAP 6) — 총 54 tests

### Changed
- DB: 18 → 20 테이블 (intercompany_pairs, consolidation_adjustments)
- financial_statements: base_currency 컬럼 추가
- statement_generator: generate_consolidated_statements 함수 추가
- statements 라우터: POST /generate-consolidated 엔드포인트

## [0.2.0] - 2026-03-23 — Phase 2: 복식부기 엔진 + 재무제표

### Added
- **복식부기 엔진** — journal_entries + journal_entry_lines 테이블, sum(debit)==sum(credit) 강제 검증, 복합 분개(3줄+) 지원
- **재무제표 5종 자동 생성** — 재무상태표(자산=부채+자본 검증), 손익계산서, 현금흐름표(직접법, 독립 기말잔고 검증), 합계잔액시산표, 결손금처리계산서
- **거래 확정 → 자동 분개** — 거래 확정 시 동일 트랜잭션에서 분개 원자적 생성 (CLAUDE.md 원칙 #9)
- **Mercury API 연동** — HOI USD 거래 read-only 동기화, 페이지네이션, 중복 감지
- **Codef 샌드박스** — 우리은행/롯데카드/우리카드 거래 조회 (SANDBOX 전용)
- **재무제표 UI** — /statements 페이지, 5탭 전환, 생성 버튼, 검증 배지(균형/불균형), 인쇄 지원
- **설정 페이지** — /settings, Mercury/Codef 연결 테스트 UI
- **Excel Export** — 재무제표 다운로드 (openpyxl, K-GAAP 양식)
- **분개 API** — CRUD + 시산표 검증 + 벌크 생성 from-transactions
- 24 new pytest cases (복식부기 14 + 재무제표 10) — 총 38 tests

### Changed
- DB: 16 → 18 테이블 (journal_entries, journal_entry_lines 추가)
- Connection pool: 반환 시 rollback 추가 (stale transaction 방지)
- transactions.py: 확정/벌크 확정 시 자동 분개 + journal_error/journal_skipped 응답
- statements.py: fs.statement_type 참조 버그 수정 (스키마에 없는 컬럼)
- CORS: allow_methods/allow_headers 명시적 제한
- Sidebar: "재무제표" 메뉴 활성화

### Fixed
- statements.py fs.statement_type 참조 오류 (스키마에 없는 컬럼 제거)
- cashflow/page.tsx 미사용 AreaChart import 제거
- Codef 에러 메시지에 내부 정보 노출 방지
- 분개 중복 생성 race condition (UNIQUE INDEX on transaction_id)

## [0.1.0] - 2026-03-23 — Phase 1: 현금흐름 대시보드

### Added
- **Dashboard** — 4 KPI 카드 (잔고, 수입, 지출, 런웨이) + 현금흐름 차트 + 최근 거래 + Quick Actions
- **Transactions** — 11컬럼 dense table (체크박스, 날짜, 출처, 회원, 내역, 거래처, 수입, 지출, 내부계정, 표준계정, 신뢰도) + 필터 + 벌크 확정 + 인라인 편집
- **Upload** — 드래그앤드롭 Excel 업로드 (.xls/.xlsx) + 소스 자동 감지 + 프로그레스 바 + 히스토리
- **Cashflow** — 12개월 Area 차트 + 월별 breakdown 테이블 (기초/수입/지출/순/기말)
- **Slack Match** — 2-panel 매칭 UI (메시지 카드 + 후보 패널) + 키보드 단축키
- **Sidebar** — 4개 섹션 그룹핑 (요약/데이터/계정/관리), P2 disabled, 모바일 hamburger
- **Entity Tabs** — 3법인 전환 (?entity= 쿼리 파라미터), 연결 탭 Phase 3 disabled
- **Excel 파서** — 롯데카드/우리카드/우리은행/CSV 자동 감지 (BaseParser 공통 인터페이스)
- **체크카드 중복 감지** — 우리은행 '체크우리' ↔ 우리카드 '체크계좌' 자동 마킹
- **Slack 라우터** — 메시지 조회, 후보 매칭 (금액 ±1/±3%/VAT), 확정/무시
- **Cashflow 엔드포인트** — 월별 opening/income/expense/net/closing
- pytest 14 cases (파서 감지 + 파싱 + 중복 + 레지스트리)
- Playwright E2E 3 cases (대시보드, 엔티티 탭, 네비게이션)
- shadcn/ui 13개 컴포넌트 + sonner toast
- 공유 유틸리티 (formatKRW, fetchAPI)

### Changed
- DB connection: get_conn/put_conn → Depends(get_db) generator 패턴
- CORS: 하드코딩 → ALLOWED_ORIGINS 환경변수
- Dashboard KPI: 전월 대비 증감율 추가
- MASTER.md: KPI 크기 분리 (standalone 48px / inline 28px), A11y 사양, 반응형 전략 추가
- dashboard.md: Interaction States, 반응형, 법인 탭 동작, Quick Actions 구체화
- transactions.md: Interaction States, 반응형, 중복 표시 확정 (회색+취소선)

### Fixed
- Recharts ResponsiveContainer width/height 콘솔 경고 (minWidth={0})
- Sidebar h1 중복 (로고 div로 변경)
- Dashboard 터치 타겟 16px → 44px

## [0.0.0] - 2026-03-22 — Phase 0: 프로젝트 세팅

### Added
- PRD v2 완성 (docs/PRD.html)
- Neon dev 브랜치 (16 테이블, 48 표준계정, 28 GAAP 매핑)
- Frontend: Next.js 14 + Tailwind + shadcn/ui + Recharts
- Backend: FastAPI + psycopg2 + 6개 라우터
- 디자인 시스템: MASTER.md (UUPM dark OLED)
- Slack 매칭 엔진 설계 (docs/slack-matching-engine.md)
- Alembic 초기화, Railway/Vercel CLI 설치

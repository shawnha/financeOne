# 계정 트리 재설계 — 표준=상위 / 내부=보조 / 운영=직교 (결산자료 기반)

## 목표
표준계정과 내부계정이 평행 2트리라 ~6% 거래가 drift(transaction.standard ≠ 내부계정.standard, 약 640건). 이를 **단일 표준 트리(통제계정) + 내부계정(보조계정 잎) + 운영분류(직교 태그)** 로 통합해 drift를 구조적으로 제거.

사장님 결정: 상위 트리=순수 표준(GAAP) 골격 유지, 운영분류도 필요(직교로).

## 권위 기준 = 가결산자료 전체 (전 법인·전 기간, 듀얼 GAAP)
- **결산자료 코드가 정답.** DB standard_accounts와 코드 체계 일치(81100·83100·26200·40100·41200…).
- 결산자료가 **이미 통제+보조 패턴 사용**: 지급수수료 `83100`(통제) + 구매대행 `83101`(보조). → 사장님 제안과 동일.
- **사용한 결산자료 (`~/Documents/HanahOneAll/`)** — 4파일만 아니라 기존 전체 활용(사장님 지적):
  - 코리아(2): `Finance/1.가결산자료/26년/1분기/`(원장51+재무제표) + `Finance/3.결산자료/25년귀속 계정별원장`(46) + 25.12.31 가결산.
  - 리테일(3): 26.1Q 원장(26)+재무제표.
  - 홀세일(13): `한아원홀세일/재무자료/{24,25,26}년 계정별원장`(26년=48계정, 도매: 가지급금13400·단기차입금26000·장기차입금29300·차량운반구20800·이자비용93100·통신비81400·수도광열비81500·차량유지비82200·건물관리비83700·잡급80500·잡비84800).
  - HOI(1): `한아원아메리카(HOI)/결산자료/25년확정/{BS,PL}_Finalized`(US GAAP·QuickBooks·영문) + 월별 PL.
  - KB: `Knowledge/`(세무·회계 계정 매핑) [[reference_obsidian_knowledge_vault]].

## 듀얼 GAAP — 표준 차트는 GAAP별 2골격
1. **K-GAAP(중소기업회계기준, 더존 8xxxx/9xxxx)** — 코리아·리테일·홀세일. 결산 union ≈ 60~70계정. 위 GAAP 계층(아래) 적용.
2. **US GAAP(QuickBooks 구조, 영문·기능별)** — HOI. Income(Channel Sales>Amazon/Shopify/TikTok)·COGS(Selling Fees·COGS·Inventory)·Gross Profit·Expenses(Administrative/General/Selling: 3PL·Advertising·Marketing)·Net Operating·Other·Net Income. 계층형 컨트롤+서브 이미 사용.
3. **gaap_mapping**으로 K-GAAP ↔ US GAAP 연결(연결재무제표=US GAAP 기준, CLAUDE.md #6·7). standard_accounts.gaap_type로 골격 구분.

## GAAP 계층(재무제표 롤업) — 트리 상위 골격
**재무상태표(중기준)**
- 자산 > 유동자산 > {당좌자산: 보통예금10300·외상매출금10800·미수금12000·선급금13100·부가세대급금13500·선납세금13600 / 재고자산: 상품14600}, 비유동자산 > {투자: 장기대여금17900·종속기업투자주식18400 / 유형: 비품21200·시설장치21900 / 무형: 영업권23100[리테일] / 기타: 임차보증금96200}
- 부채 > 유동부채 > {외상매입금25100·미지급금25300·예수금25400·부가세예수금25500·단기차입금26000·미지급세금26100·미지급비용26200·미지급급여27500·선수금25900}, 비유동부채 > {주임종장기차입금30300·조건부지분인수계약부채31500}
- 자본 > {자본금33100 / 자본잉여금: 주식발행초과금34100 / 자본조정 / 기타포괄손익누계액 / 결손금: 이월결손금37600·미처리결손금37800}

**손익계산서(중기준)**
- Ⅰ.매출액 > {상품매출40100, 매출환입및에누리40200(차감), 서비스매출41200}
- Ⅱ.매출원가 > {상품매출원가45100}
- Ⅲ.매출총이익(=Ⅰ−Ⅱ)
- Ⅳ.판매비와관리비 > {직원급여80200·퇴직급여80800·복리후생비81100·여비교통비81200·접대비81300·전력비81600·세금과공과금81700·지급임차료81900·보험료82100·운반비82400·도서인쇄비82600·사무용품비82900·소모품비83000·지급수수료83100(+구매대행83101)·광고선전비83300·판매수수료83900}
- Ⅴ.영업손익(=Ⅲ−Ⅳ)
- Ⅵ.영업외수익 > {이자수익90100·외환차익90700·사업양도이익92200·국고보조금수익92900·잡이익93000}
- Ⅶ.영업외비용 > {잡손실96000 등}
- Ⅷ.법인세차감전이익 → Ⅹ.당기순이익

## DB 정리 필요 (결산 vs 현재 standard_accounts 300)
1. **중복 명칭 42건** — 같은 계정명에 코드 여러 개. **결산 코드로 일원화**, 나머지 deprecate(is_active=false). 예: 복리후생비(50400❌·**81100**✅)·여비교통비(51300❌·**81200**✅)·미지급비용(20300❌·**26200**✅)·이자비용(4개)·선수금(20700·25300·25900). ⚠️매핑된 거래/내부계정 재배선 후 폐기.
2. **명칭 오류 수정**: `25300` DB=선수금→**미지급금**(결산). `18400` DB="회사설정계정과목"placeholder→**종속기업투자주식**.
3. **누락 5개 추가**: 23100 영업권·26100 미지급세금·80800 퇴직급여·83101 지급수수료(구매대행)·92200 사업양도이익.
4. 코드별 category/subcategory를 위 GAAP 계층에 맞게 정합(재무제표 롤업 = statement_generator 그룹과 일치).

## 타깃 데이터 모델 (정련 — 2026-06-07 분석 반영)
- **단일 구조 트리 = standard_accounts(GAAP 골격, parent_code).** 전 법인 공유(중기준). HOI=US GAAP 별도 골격.
- **internal_accounts = 보조계정**, `standard_account_id`로 표준에 매달림(링크 이미 존재 → 재배치).
- **기능 sub-tree 보존**: 내부 self-ref `parent_id` 다층 그룹(구독·복리후생·교통·수수료·외주비용 등)은 **표준 밑에 그대로 유지**. 예: 지급수수료(83100) ▸ 구독(기능그룹) ▸ {기타구독·Admin구독·AI SaaS·Google Workspace…}. 기능그룹 = 자식 표준 일관 + 채널/컨테이너 아님.
- **채널/사업 그룹은 트리 부모 금지 → cost-center 태그**: 마트약국·한아원리테일·ODD·3PL은 자식이 여러 표준에 걸침(약국식비=복리후생·상품사입=매출원가) → 표준 부모 못 됨. **부문/프로젝트(운영 태그)로**. 약국식비=복리후생비(표준)+마트약국(태그). (코리아 cost-center 분포: 마트약국10·ODD7·리테일4·3PL3.)
- 최상위 컨테이너(지출·수입)=비용/수익 카테고리 → 표준 GAAP 골격으로 흡수(제거).
- **거래/세금계산서 = 잎 하나 태깅 → transaction.standard 동기화 자동도출**(잎.standard_account_id). 독립 입력 잠금 = drift 차단.
- **운영분류 = 직교 태그**(트리 부모 아님): **고정/변동(cost_behavior)·구독여부·부문/프로젝트(cost-center: 마트약국·리테일·ODD…)**. 담당자=제외(결제 1인). owner/is_recurring(기존) 활용.
- **context 의존 분리**: 카드대금 → `카드대금-정식결제`(미지급비용26200) / `카드대금-선결제`(선급금13100) 두 잎. (25200/26200 해소, [[project_opex_card_payment_pending]])

## 미매핑 추천 (코리아 22, 분석 초안)
- 다수는 **구조노드**(지출·수입·마트약국·카드대금=0건 그룹)·**테스트계정**(삭제). 진짜 leaf 분류는 소수.
- 추천: 제작외주→지급수수료(83100)·상여금→직원급여(80200)·**인프라구축비→서비스매출(41200, 비용아닌 수익! 이수마트)**·정수기/에스원→임차료/수수료·노트북→비품(21200)or소모품·스마트스토어리뷰→광고선전비(83300).
- ⚠️ 기타(28·9건)·자기자금이체(내부이체=비손익) → 거래/결산 확인 [[feedback_sensitive_classification_workflow]]. 차입금이자비용 그룹 현재 표준 "장기차입금"=오류→이자비용(93100).

## 마이그레이션(단계)
1. 표준 차트 정합(중복 일원화·누락 추가·명칭수정) — 매핑 재배선 동반.
2. 내부계정 표준 밑 재배치(코리아 129·리테일 124·홀세일 186·HOI 121, NULL 매핑 채움 — 코리아 22개).
3. transaction.standard = 내부.standard 일괄 정렬(drift 640 해소) + 향후 도출/동기화.
4. mapping_rules·invoice 매핑을 잎 기준으로.
5. statement_generator/bookkeeping_engine 롤업을 표준 GAAP 계층으로.
6. 계정관리 UI = 표준 골격 + 보조 잎 + 운영 태그 필터.

## 검증 기준
- sum(debit)==sum(credit), 재무상태표 항등식, 현금흐름 루프(기존 invariant).
- 재무제표 결과가 가결산 PDF와 매칭(코리아 26.1Q: 판관비 484,081,859 등 라인 일치).
- drift 0 (transaction.standard 모두 내부 잎과 일치).

## 열린 결정
- transaction.standard: 완전 도출(컬럼 제거) vs 동기화 유지(권장: 동기화 — 기존 쿼리 영향 최소).
- 운영분류 항목 확정(고정/변동·담당자 외 추가?).
- 표준 deprecate vs 삭제(권장: is_active=false 유지, 이력 보존).
- 적용 순서: 코리아 먼저 PoC → 리테일/홀세일/HOI.

## ⚠️ 리뷰 발견 (codex 적대적 리뷰 2026-06-07, 코드근거) — 정식설계 전 반드시 반영
- **[P1] 과거 재무제표 restatement**: drift 640 일괄정렬은 과거 재무제표를 바꿈(재무제표는 현재매핑서 재생성 `consolidated.py:215`, 일부 P&L이 transactions.standard 직접읽음 `income_statement_accrual.py:124`). → **기간잠금+remap 감사테이블+전후diff+명시승인**, 마감기간은 재분류분개로(조용한 덮어쓰기 금지).
- **[P1] journal_entry_lines가 진짜 회계원천**: transactions만 고치면 게시 분개기반 재무제표 안 바뀜(`bookkeeping_engine.py:183` 복사·`:473` 롤업). → 기간별 보존/재생성/재분류 정책. 마감·조정분개 맹목 sync 금지.
- **[P1] standard sync는 DB 트리거로 강제**(앱관행 X): PATCH·auto-map target=standard·split이 독립 standard 씀(`transactions.py:347,471,1001`) → drift 재발. 내부잎 변경시 도출, 직접수정 차단.
- **[P1] "내부1=표준1" 거짓 — transaction_splits 이미 존재**(`bookkeeping_engine.py:165`), 인보이스 다중라인 분개(`invoice_service.py:115`). 내부잎=default(truth 아님), 라인별 split+contra+자산화 워크플로우.
- **[P1] 중복표준 폐기 FK 폭발반경**: transactions·mapping_rules·keywords·분개라인·gaap_mapping·splits FK. → **canonical remap 테이블로 전 참조 트랜잭션내 갱신 후** is_active=false. 별칭유지.
- **[P1] 듀얼GAAP 경계 하드닝**: `consolidated.py:256`이 HOI에 convert_kgaap_to_usgaap() 호출(K전용). gaap_type 하드경계 — HOI는 이미 US_GAAP, 한국법인만 변환.
- **[P1] 기초/마감/VAT/내부거래/현금흐름 통제 선행**: 발생BS plug자본·CF가 10100만(은행 10300)·내부거래 휴리스틱. 기초잔액 마이그·마감정책·VAT정산·내부거래상계·CF계정셋 재설계.
- **[P2] 롤업은 parent_code 아니라 category/subcategory를 씀**(`income_statement_accrual.py:131`·`bookkeeping_engine.py:475`). → 트리는 입력/UI 구조용. 롤업은 **category/subcategory 권위 유지 OR 진짜 트리롤업 구현+테스트**. "parent_code가 롤업 구동하는 척" 금지.
- **[P2] 생성기 `_gen_tree_html.py` 버그**: live DB접속·entity2 하드코딩·first code match·**사입→40100 상품매출은 오류(COGS여야)**·25200→26200이 plan 25300정합과 충돌. → 시각화 전용·비권위 명시, is_active/gaap 필터, remap 제거.
- 판정 **GO-with-fixes**. top3: 기간잠금/재작성·DB강제sync(분개라인정책)·듀얼GAAP경계.

## ⚠️ 제3자 에이전트 리뷰 추가 (2026-06-07, DB 실측 — codex와 교차검증, 둘 다 GO-with-fixes)
- **[P1] gaap_mapping 커버리지 붕괴(codex 못 봄)**: 통신비 폐기코드 50700·82800엔 gaap_mapping 1행씩, **생존 81400엔 0행** → 일원화 시 US GAAP 연결에서 통신비 빠짐. **42그룹 일원화 = 폐기코드 gaap_mapping을 생존코드로 이관 필수**(매핑공백 사전점검표).
- **[P1] 25300 데이터 triage**: 25300=선수금에 실제 거래5·세금계산서3·내부1 booking됨 → "미지급금 개명"은 진짜 선수금 오분류. 생성기 25200→26200은 미지급금(상거래)vs미지급비용(발생) conflate + plan 25300과 충돌. → **42그룹 canonical을 계정별 1:1 명시표로, 25300 8건은 개명 전 분리**(진짜 선수금→25900 / 실제 미지급금→유지).
- **[P0 실측] 홀세일 journal_entries 0건**(6716거래 GL없이 transactions만으로 재무제표) → 347 drift 재배선이 곧 과거 홀세일 BS/IS 변경. 코리아도 절반(2614/5373)만 GL. **period/close/lock 테이블 0·is_closing 분개 0** — 마감잠금 장치 자체가 없음. 실측 drift=코리아192·리테일5·홀세일347=544.
- **[P0 실측] transactions.std ↔ journal_entry_lines.std 2차 drift**: 표준측 분개라인이 t.std 스냅샷(전기시 복사 `bookkeeping_engine.py:289`). transactions만 재배선+분개 미재전기 → 발생IS/BS는 움직이고 현금흐름·연결은 그대로. **HOI는 11/218만 일치(이미 심한 desync)**. → GL 단일정본화 OR 재배선 시 분개 재전기를 같은 트랜잭션에.
- **[P1 실측] HOI 정리 과소평가**: 내부 70/121 NULL·GL std 거의 desync → 작업량 큼.
- **[P2] context분리 일반화**: 카드대금 특례 말고 환불(매출환입vs선수금reversal vs잡손실)·선급/가지급 정산·자산화(노트북 비품21200 vs소모품83000)까지 일반 정책 + split시 어느 잎이 transactions.std 결정하는지 규칙. transaction_splits 현재 0행.
- **✅ 둘 다 개념 인정**: 통제+보조=결산일치, 채널=태그 데이터입증, 기능sub-tree 안전, **cross-gaap dup=0이라 일원화는 GAAP내부 안전**, 누락5·is_active=false 저위험.

## 메모
- 결산자료 파일(.xls/.pdf, ~/Documents/HanahOneAll/Finance/) **커밋 금지**. 분석만 로컬, 깃엔 설계·코드만.
- 다음: 위 리뷰 반영 → Software Architect 정식 설계 + plan-eng-review → 코리아 PoC.

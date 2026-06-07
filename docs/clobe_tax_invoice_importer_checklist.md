# clobe 세금계산서 importer — 계획·체크리스트·컨텍스트 노트

clobe.ai(클로브) 워크스페이스의 세금계산서 엑셀을 FinanceOne `invoices`(source_kind='tax_invoice')로 적재하는 재사용 importer. 국세청(홈택스) 직접 연동이 없어서, clobe(공동인증서로 홈택스 수집)의 공식 "엑셀 다운로드"를 브릿지로 사용. 스크래핑 불필요.

## 목표 / 성공기준
- 코리아(2) 매출 세금계산서 누락분(2~4월) 적재 → /pnl 매출 정상화 (1차 deliverable).
- 멱등(idempotent): 같은 파일 재적재해도 중복 0.
- 멀티법인 재사용: clobe '내 사업자번호' → entity 자동 매핑 (코리아 1968103665·리테일 3778103468·홀세일 6078622100).
- 매입·리테일·홀세일은 같은 importer로 후속 (별도 승인).

## clobe 엑셀 양식 (라이브 확인)
시트: 전체 / 매출 / 매입 / 메타정보. 데이터 시트 컬럼(고정):
`발급일자 | 작성일자 | 매출 매입 유형 | 과세 유형 | 거래처 상호 | 거래처 사업자등록번호 | 대표 품목 | 공급가액 | 세액 | 합계금액 | 수정 여부 | 입금 예정일자 | 내 사업자번호`
- **승인번호(document_no) 컬럼 없음** → 기존 /invoices/import 의 document_no dedup 무력 → 자연키 필요.
- '매출 매입 유형' 컬럼이 direction 직접 제공('매출'→sales, '매입'→purchase) → our_biz_no 추론 불필요.
- 공급가액/세액/합계 = 정확 분리(VAT 포함 합계). 음수 행 = 수정(취소) 세금계산서.
- 과세 유형 = 일반/면세.

## dedup 자연키 (확정)
`(entity_id, direction, issue_date=작성일자, total=합계금액)`
- 근거: 기존 DB tax_invoice 행은 **counterparty_biz_no=NULL, vat=0, amount=합계**(분리 안 됨)로 저장됨 → 공통 신뢰 필드는 합계(total)뿐. amount/vat/biz_no는 기존↔clobe 불일치.
- 검증: 코리아 기존 5건(1월) ↔ clobe 5건 (작성일자, total) 정확 매칭. clobe 1/27 −13,425,676(수정분)만 신규로 분류. ✅

## 대조 결과 (코리아 2026, 읽기전용)
- 매출 16건 ₩119.95M: 기존 일치 5건(skip) + **신규 10건(2~4월) ₩72.4M** + 수정세금계산서 1건(1/27 −13.4M).
- ⚠️ 1월 수정세금계산서: clobe엔 +13.4M/−13.4M/+14.7M(원본·취소·재발행) 모두 있고 DB엔 +13.4M·+14.7M만(−13.4M 없음) → DB 1월 매출 13.4M 과대 가능. −13.4M 적재 시 정합. (세무 영역 → dry-run에서 명시 후 사장님 확인.)
- 매입 146건 ₩501.9M (DB 39건뿐). 매입 invoices는 /pnl(비용=transactions 현금) 무영향, 발생주의 재무제표 쪽 → 매출과 분리 후속.

## 구현 (TDD)
### Backend
- [ ] `backend/services/parsers/clobe_tax_invoice.py` — `parse_clobe_tax_invoice(file_bytes)`. '전체' 시트 우선(없으면 매출+매입 결합). 행→dict{entity_biz_no, direction, issue_date, counterparty, counterparty_biz_no, description, amount, vat, total, tax_type, due_date, raw}. cp949/숫자/날짜/음수 처리.
- [ ] `backend/services/clobe_import_service.py` — `import_clobe_invoices(conn, parsed, dry_run=True)`. entity=내사업자번호 매핑, 자연키 dedup, source_kind='tax_invoice'·note='clobe'·raw_data 적재. 반환 {parsed, inserted, duplicates, skipped_no_entity, errors, by_entity_direction}.
- [ ] 라우터 `POST /invoices/import-clobe` (invoices.py) — 업로드 + dry_run.
### 테스트
- [ ] `backend/tests/test_clobe_tax_invoice.py` — 파싱(컬럼/VAT/면세/음수), direction(유형 컬럼), entity 매핑(biz_no), 자연키 dedup(기존 vat=0/biz NULL 케이스), 멀티법인.

### 검증 / 적재
- [ ] pytest 회귀 없음.
- [ ] 실제 clobe 매출 파일 dry-run → 16건/5 dup/11 new(10+수정1) 확인, 사장님 명시 승인.
- [ ] dry_run=False 적재 (prod, 코리아 매출). /pnl 코리아 2~4월 매출 정상화 확인.
- [ ] 매입·리테일·홀세일은 후속(별도 승인).

## 경계 / 주의
- 프로덕션 DB 적재는 사장님 명시 승인 필수(자동가드).
- selective-stage (codef·cockpit 등 타 세션 미커밋분 분리). [[feedback_selective_stage_pitfall]]
- 세무 분류(수정세금계산서·이수마트 거래성격·계정매핑)는 자체판단 금지 → 결산자료/사장님.
- 거래 데이터 엑셀(~/Downloads/*세금계산서*.xlsx) 커밋 금지.
- SsArt 비번 로테이션 권장(별건).

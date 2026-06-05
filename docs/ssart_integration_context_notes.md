# SsArt SIMS OpenAPI 연동 — 컨텍스트 노트

연동 중 내린 결정과 근거. 계속 append.

## API 사실 (2026-06-05 라이브 read-only 테스트로 확정)
- Base URL: `https://openapi.ssart.co.kr/api` (가이드 표기 `openApi`지만 도메인 대소문자 무관).
- **인증 2단계**: `POST /v1/oAuth/` `{uid,pwd}` → ACCESS_TOKEN(2주) / `POST /v1/oAuth/utk/` `{ACCESS_TOKEN}` → USE_TOKEN(48h, API 호출용). 모든 호출 body에 `USE_TOKEN`.
- **응답 인코딩 = cp949 (ks_c_5601-1987)**. UTF-8로 디코딩하면 한글 깨짐. 반드시 `bytes.decode("cp949")`.
- **요청 포맷 = flat 파라미터** (예: `{"USE_TOKEN":..,"OUT_DATE":"20260530~20260530","PAGE_NO":"1","PAGE_SIZE":"500"}`). 가이드 PPT의 `"DATA":[{...}]` 래퍼는 **틀림 → 500 에러**. summary/detail 모두 flat.
- 날짜 범위는 `"YYYYMMDD~YYYYMMDD"`. 매출=`OUT_DATE`(출고일) 또는 `TRANS_DATE`(명세서일), 매입=`IN_DATE` 또는 `TRANS_DATE`. 둘 중 하나 필수.
- 응답 공통: `{RESULT:Y/N, ERRCODE, ERRMSG, COUNT, DATA:[...]}`.
- 오류코드: E0000 정상 / E0001 데이터없음 / E0002 USE_TOKEN 무효 / E0003 결과없음 / E0004 필수조건 미입력 / **E0005 결과과다(검색 좁혀라)** / **E9999 레이트리밋(IP당 1분 300회)**.
- 페이지: `PAGE_NO`/`PAGE_SIZE` flat. → **날짜별로 끊어 조회**(하루 ~80줄 < PAGE_SIZE)하면 E0005 회피 + 안정.

## 매출 detail (`/v2/sales/get/`) 필드 → wholesale_sales
- TRANS_DATE(명세서일), TRANS_SEQ(명세서번호), OUT_YYMMDD(출고일), OUT_SEQ(출고번호=line seq), OUT_CUST_CD/NM/PRT, PRODUCT_CD/NM/PRT/STANDARD, OUT_QTY, IO_GU(매출), FIN_UNIT_COST(장부단가)/FIN_OUT_AMT(장부출고금액), UNIT_COST(실단가)/OUT_AMT(실출고금액), FIN_IN_UNIT_COST/FIN_IN_AMT(장부입고=COGS), IN_UNIT_COST/IN_AMT(실입고), INSU_PRICE, TAX_YN, OTHER.
- **핵심: OUT_AMT/FIN_OUT_AMT = 합계금액(VAT 포함)**. 검증: 5/30 detail ΣOUT_AMT(163,450,421) == summary ΣTOT_AMT(163,450,421). summary ΣSUPPLY_PRICE(148,591,296) = ÷1.1.
- 공급가 역산: TAX_YN='Y'면 supply=round(합계/1.1), vat=합계−supply. TAX_YN='N'(면세)면 vat=0, supply=합계.
- **dedup 키 = (entity, sales_date, document_no=TRANS_SEQ, row_number=OUT_SEQ, product_name)** — 기존 매출관리 xlsx와 동일(xlsx가 SIMS 생성물). → API로 겹치는 기간 재sync해도 ON CONFLICT가 중복 차단. amount는 키에 없어 안전.

## 매입 detail (`/v2/purchase/get/`) → wholesale_purchases
- 매출과 대칭: IN_YYMMDD(입고일), IN_SEQ, IN_CUST_*, IN_QTY, FIN_UNIT_COST/FIN_IN_AMT, UNIT_COST/IN_AMT, TAX_YN.
- 면세 흔함 (위고비 등 생물학적제제 TAX_YN=N). 매입 합계 VAT 포함 여부는 매출과 동일 가정, summary 대조로 검증 예정.

## 결정
- **토큰 비영속(매 sync마다 재인증)**. Vercel serverless라 in-memory 캐시 무의미 + 일배치라 2콜 비용 무시. 추후 DB 캐시 불필요.
- **기존 import 함수 재사용** (parse 없이 transform→import_wholesale_sales/purchases). 스키마/INSERT/dedup 변경 0.
- **장부(FIN) vs 실 매핑은 5/30 overlap 행과 DB 대조로 확정** (real_ 접두 = 실). 검증 전까지 total_amount←FIN_OUT_AMT 가정.
- 자격증명 `.env` `SSART_API_URL/SSART_UID/SSART_PWD` (gitignore). ⚠️ 비번 transcript 노출 → 로테이션 권장.

## 배경
- 5월 매출 과소(13.7억)는 이미 해결됨 — `5월매출관리(홀세일).xlsx`(5/13~5/30, 1057줄) 수동 업로드로 39.4억 완성. 이 연동은 **자동화**(수동 xlsx 제거)가 목적. [[project_resume]]

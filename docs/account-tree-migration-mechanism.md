<!-- 계정 트리 재설계의 마이그레이션 메커니즘 정식 설계 (기간잠금·canonical remap·GL 재전기·sync 강제·듀얼 GAAP 경계) -->

# 계정 트리 재설계 — 마이그레이션 메커니즘 정식 설계

작성: Software Architect, 2026-06-07. 입력 문서: `docs/account-tree-redesign-plan.md`(모델+리뷰), `docs/account-tree-preflight-2026-06-07.md`(실측), `docs/account-tree-redesign-context-notes.md`(결정기록).

이 문서는 **메커니즘 설계만** 담는다. DB write·코드 edit·commit 없음. 잠긴 개념 모델(표준=상위 GAAP 골격 / 내부=보조 잎 / 운영=직교 태그)은 변경 대상이 아니다. 모든 메커니즘 주장은 실제 코드 file:line으로 grounding했고, 라인은 직접 Read로 확인한 2026-06-07 기준이다. 못 정하는 결정은 §13 "열린 결정"에 명시했다.

---

## 0. 설계가 선 사실 (코드 grounding 요약)

설계 전체가 의존하는 코드 사실을 먼저 못박는다. 이 사실들이 P0/P1 리스크의 근거다.

1. **재무제표에는 불변 스냅샷이 없다 — 매 조회가 라이브 재계산이다.** `financial_statement_line_items`는 생성 때마다 통째로 삭제 후 재구성된다 (단독 `consolidated.py:67`, 연결 `consolidated.py:215`). 따라서 상류(`transactions.standard_account_id` 또는 `journal_entry_lines`)를 바꾸면 **다음 재생성 시 과거 재무제표가 조용히 restatement** 된다. 이것이 핵심 P0이다.

2. **읽기 경로가 둘로 갈린다.**
   - 발생주의 손익계산서 판관비/영업외/세금은 `transactions`를 직접 읽는다 (`income_statement_accrual.py:124-137`, `JOIN standard_accounts s ON s.id = t.standard_account_id`). → `transactions.standard_account_id` 재배선 시 **즉시** 과거 IS가 움직인다 (GL 불필요).
   - 발생주의 재무상태표·현금주의 5종·연결은 GL(`journal_entry_lines`)을 `get_all_account_balances`로 읽는다 (`bookkeeping_engine.py:452-489`, `JOIN journal_entry_lines`). → JEL을 재전기해야만 움직인다.
   - 결론: `transactions`만 고치고 JEL을 재전기하지 않으면 **IS는 움직이고 BS/CF/연결은 그대로** → 같은 재무제표 안에서 IS와 BS가 어긋나는 내부 불일치 발생.

3. **JEL은 전기 시점의 `transactions.standard_account_id` 스냅샷이다.** `create_journal_from_transaction`이 단일 매핑은 `std_account_id`를 그대로 라인에 복사하고 (`bookkeeping_engine.py:289-293`), splits는 각 split의 `sa_id`를 복사한다 (`:278-287`). 즉 JEL은 별도 정본이며 `transactions`와 자동 동기화되지 않는다. 인보이스 분개도 동일하게 `standard_account_id`를 라인에 박는다 (`invoice_service.py:119-127`, `_create_invoice_journal` `:143~`).

4. **롤업 권위는 `category`/`subcategory`이지 `parent_code`가 아니다.** 발생 IS는 `s.category = %s AND s.subcategory = ANY(%s)`로 버킷팅하고 (`income_statement_accrual.py:131`), `get_all_account_balances`는 `GROUP BY sa.category, sa.subcategory`로 집계한다 (`bookkeeping_engine.py:484`). 연결은 `b["category"]`를 `_norm_cat`으로 정규화해 합산한다 (`consolidated.py:438-467`). `standard_accounts.parent_code`(`schema.sql:44`)는 존재하지만 어떤 롤업도 구동하지 않는다.

5. **표준 차트는 전 법인 공유 + `gaap_type`로 K/US 분리.** `standard_accounts`의 UNIQUE는 `code` 단독이 아니라 `(code, gaap_type)` 복합이다 (마이그레이션 `o5p6q7r8s9t0_standard_accounts_gaap_type.py:53-67`). 같은 코드가 K_GAAP/US_GAAP 두 행으로 존재할 수 있다. preflight의 "cross-gaap dup=0 → 일원화는 GAAP 내부 안전"은 여기서 나온다. **canonical 병합은 같은 `gaap_type` 안에서만** 일어나야 한다.

6. **표준 참조 FK = 8테이블** (preflight §FK, 코드로 교차확인): `transactions.standard_account_id`(`schema.sql:94`), `internal_accounts.standard_account_id`(`:55`), `invoices.standard_account_id`(마이그 `k1l2m3n4o5p6:50`), `journal_entry_lines.standard_account_id`(`:413`), `mapping_rules.standard_account_id`(`:250`), `standard_account_keywords.standard_account_id`(`:281`), `transaction_splits.standard_account_id`(`:433`), `gaap_mapping.standard_account_id`(`:290`).

7. **과거 freeze 장치 부재.** preflight 실측: `is_closing` 분개 0건, 조정분개 0건, 기간잠금/마감 테이블 없음. 홀세일(13) GL 0건(재무제표=transactions 단독), HOI(1) GL std 일치 11/109(극심 desync), 코리아(2) GL std 98%·NULL 22·drift 192.

8. **독립 standard 쓰기 경로가 3곳 — drift 재발원.** PATCH(`transactions.py:359-376` 일반 필드 루프가 `standard_account_id`를 직접 SET, splits 사용 시 `:347-357`에서 차단, 내부→표준 도출은 `:421-432`), auto-map target=standard(`:557-565` set_clause + `:579` UPDATE — **내부 도출 우회**), split(`:1001-1005` 첫 split sa를 `transactions.standard_account_id`에 박음). 이 셋은 서로 다른 규칙으로 같은 컬럼을 쓴다.

---

## 1. 기간잠금 / 마감 메커니즘 (P0)

### 1.1 문제
§0-1, §0-7. 과거 기간을 동결할 수단이 전혀 없고, 재무제표는 라이브 재계산이라 어떤 상류 변경도 다음 조회에서 과거를 덮어쓴다. 마이그레이션의 모든 재배선은 잠재적 "조용한 restatement"다.

### 1.2 신규 테이블
```sql
-- 회계 기간 동결 — 잠긴 (entity, 기간, basis)은 직접 UPDATE 금지
CREATE TABLE IF NOT EXISTS fiscal_period_locks (
  id         SERIAL PRIMARY KEY,
  entity_id  INTEGER NOT NULL REFERENCES entities(id),   -- 절대원칙: entity_id 필수
  period     DATE NOT NULL,            -- 월 첫날(2026-03-01) 단위 (연 잠금은 1월~12월 일괄 insert)
  basis      TEXT NOT NULL CHECK (basis IN ('cash','accrual','both')),
  locked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  locked_by  INTEGER REFERENCES members(id),
  note       TEXT,
  UNIQUE(entity_id, period, basis)
);
```

### 1.3 강제 메커니즘 (2겹)
- **A. 잠금 트리거**: `transactions`(BEFORE INSERT/UPDATE/DELETE, `date` 기준), `journal_entry_lines`(소속 `journal_entries.entry_date` 기준), `transaction_splits`(소속 transaction `date` 기준)에 트리거를 걸어, 영향 행의 기간이 잠긴 `(entity_id, period)`면 예외를 던진다. 단 마이그레이션·재전기를 위해 세션 GUC `financeone.allow_locked_write = on`일 때만 우회 허용(아래 1.4의 통제된 재분류 경로에서만 설정).
- **B. 잠긴 재무제표 보존**: 잠긴 기간의 `financial_statements`는 `status='locked'`로 두고, 재생성 함수가 locked statement에 대해서는 `DELETE FROM financial_statement_line_items`(현재 `consolidated.py:67`·`:215`)를 **거부**하도록 가드를 추가한다. 잠긴 기간의 line item은 그 시점 값을 박제한다(불변 아카이브). → 재계산이 과거를 못 건드린다.

### 1.4 잠긴 기간 변경 = 일자 있는 재분류분개로만
잠긴 기간의 계정 정정은 직접 UPDATE가 아니라 **현재 열린 일자**의 재분류분개(`journal_entries.is_adjusting=true`, `create_journal_entry(..., is_adjusting=True)` `bookkeeping_engine.py:99-162`)로 표현한다. 차변/대변 합 일치는 엔진이 강제(`:126-130`)하므로 sum(debit)==sum(credit) 절대원칙이 유지된다. 잠긴 과거 IS/BS는 불변, 정정은 당기 영향으로만 흐른다.

### 1.5 "조용한 restatement" 표면 매핑 (어디서 과거를 읽나)
| 읽기 지점 | 소스 | 잠금으로 보호할 대상 |
|---|---|---|
| 발생 IS 판관비/영업외/세금 | `transactions` 직접 (`income_statement_accrual.py:124-137`) | `transactions.standard_account_id`, `is_duplicate`, `is_cancel` |
| 발생 BS / 현금 5종 / 연결 | GL `get_all_account_balances` (`bookkeeping_engine.py:473-489`) | `journal_entry_lines.standard_account_id`, `je.status` |
| 발생 BS 합성잔액(외상매출/매입·VAT) | `wholesale_sales/purchases`, `balance_snapshots`, `ar_opening_balances` (`balance_sheet_accrual.py:31-221`) | 이 입력 테이블의 과거 행 |
| 연결 HOI | GL + `convert_kgaap_to_usgaap` (`consolidated.py:256-281`) | HOI JEL + `gaap_mapping` |

### 1.6 리스크 / 롤백
- 리스크: 트리거가 정상 운영 입력(신규 거래 import)까지 막을 수 있음 → 잠금은 마감된 과거 월에만 적용, 당월은 항상 열림.
- 롤백: 잠금 테이블·트리거 DROP으로 완전 가역(데이터 손실 0). 박제된 line item 아카이브는 별도 테이블이라 잔존해도 무해.

### 1.7 열린 결정
- 어느 월부터 잠그나(마감 기준일). 결산 권위 필요 — §13.

---

## 2. Canonical 1:1 remap 메커니즘 (P1, 전역 작업)

### 2.1 중요한 범위 사실 — canonical remap은 법인-스코프가 아니다
`standard_accounts`는 전 법인 공유(`entity_id` 없음, `schema.sql:37-47`). 따라서 중복코드 폐기는 **모든 법인의** transactions/JEL/invoices를 동시에 건드린다. "코리아 PoC 먼저"는 내부계정 재배치·drift 정렬(§4, 법인-스코프 가능)에는 적용되지만, **표준 차트 일원화는 본질적으로 전역**이다. → 차트 일원화를 코리아 내부작업과 **분리된 전역 마이그레이션**으로 두고, 전 법인 마감기간 diff=0 게이트로 통과시킨다(§9 PoC와 순서 구분).

### 2.2 신규 테이블
```sql
-- 중복 표준코드 일원화 매핑 (old → canonical), 같은 gaap_type 내에서만
CREATE TABLE IF NOT EXISTS canonical_remap (
  id             SERIAL PRIMARY KEY,
  old_account_id INTEGER NOT NULL REFERENCES standard_accounts(id),
  new_account_id INTEGER NOT NULL REFERENCES standard_accounts(id),
  gaap_type      TEXT NOT NULL CHECK (gaap_type IN ('K_GAAP','US_GAAP')),
  is_relabel     BOOLEAN NOT NULL,   -- TRUE=순수 재라벨(롤업키 동일), FALSE=재분류(잠금 존중)
  reason         TEXT,
  applied_at     TIMESTAMPTZ,
  CHECK (old_account_id <> new_account_id)
);
```

### 2.3 순수 재라벨 vs 재분류 — 마감기간 안전성의 핵심
canonical 병합이 **마감기간에서도 안전한 유일한 조건**은 old와 new의 롤업키가 동일할 때다. 롤업은 `(category, subcategory)`로 구동되므로(§0-4), 다음을 사전 게이트로 강제한다:
```
for each (old,new):
  assert old.category    == new.category
  assert old.subcategory == new.subcategory
  assert old.normal_side == new.normal_side
  assert old.gaap_type   == new.gaap_type
  → 이 경우 is_relabel=TRUE. 잠긴 기간 JEL도 UPDATE 허용(롤업·합계·항등식 불변, diff=0 by construction).
  하나라도 다르면 is_relabel=FALSE → 순수 병합 금지, 재분류분개(§1.4)로 escalate.
```
preflight의 42그룹 대부분(레거시 5xxxx 저사용 → 결산 8xxxx 고사용, 동일 계정명)은 재라벨에 해당하나, **명칭만 같다고 category/subcategory가 같다는 보장은 없다** → 자동 가정 금지, 그룹별로 위 assert를 실측 게이트로 돌린다.

### 2.4 8 FK 원자적 재배선 (한 트랜잭션)
```
BEGIN;
  -- 사전 게이트 (아래 2.5·2.6 전부 PASS여야 진행)
  FOR each (old,new) IN canonical_remap WHERE applied_at IS NULL:
    -- 8 FK 전부 갱신 + remap_audit 로깅(§7)
    UPDATE transactions            SET standard_account_id=new WHERE standard_account_id=old;   -- 잠금: is_relabel만
    UPDATE internal_accounts       SET standard_account_id=new WHERE standard_account_id=old;
    UPDATE invoices                SET standard_account_id=new WHERE standard_account_id=old;
    UPDATE journal_entry_lines     SET standard_account_id=new WHERE standard_account_id=old;   -- 잠금: is_relabel만
    UPDATE transaction_splits      SET standard_account_id=new WHERE standard_account_id=old;
    UPDATE mapping_rules           SET standard_account_id=new WHERE standard_account_id=old;
    -- standard_account_keywords: keyword UNIQUE → 단순 re-point만 (충돌 없음, 2.6 참조)
    UPDATE standard_account_keywords SET standard_account_id=new WHERE standard_account_id=old;
    -- gaap_mapping: 2.5 규칙으로 이관
    -- old 폐기 (삭제 아님)
    UPDATE standard_accounts SET is_active=false WHERE id=old;
  -- 전후 diff 리포트 게이트(§7): 마감기간 diff=0 검증 → 0 아니면 ROLLBACK
COMMIT;
```
재배선과 폐기를 한 BEGIN/COMMIT에 묶어 중간 상태(코드 일부만 옮겨진 깨진 차트)를 노출하지 않는다.

### 2.5 gaap_mapping 생존코드 이관 규칙 (preflight §2 적중)
역전 사례: 생존 canonical이 `gaap=0`인데 폐기 레거시가 `gaap=1`을 쥠(차량유지비 82200 gaap0 / 레거시 gaap1, 통신비 81400 gaap0). 폐기만 하면 US GAAP 연결에서 해당 계정 누락(`convert_kgaap_to_usgaap`이 매핑 없으면 K코드 그대로 두고 `is_mapped=False`, `gaap_conversion_service.py:83-92`). `gaap_mapping.us_gaap_code`는 UNIQUE(`schema.sql:288`), `standard_account_id`는 비유일이라 1 canonical : N us_code 허용.
```
규칙 — canonical마다 gaap_mapping ≥1행 보장:
  if canonical(new) 에 gaap_mapping 행 없음 AND old 에 있음:
      UPDATE gaap_mapping SET standard_account_id=new WHERE standard_account_id=old;  -- 이관
  elif 둘 다 있음:
      if 같은 us_gaap_code:  old 행 DELETE (UNIQUE 충돌 회피, canonical 행 유지)
      else:                  old 행도 new로 re-point (1:N 허용)
  사전 매핑공백 점검표: 일원화 후 "사용>0 AND gaap_mapping 0행"인 한국 코드 = 0 이어야 진행.
```
preflight가 한국 결산코드 ~12개(82200·29300·26000·93100·84800·81600·83700·11400·81400 등)에서 사용>0·gaap=0을 실측 → 이들은 이관 또는 신규 gaap 행 필요(결산 권위, §13).

### 2.6 25300 / 선수금 다중코드 + 67키워드 특수처리 (preflight §3, "개명 아님")
25300은 재라벨이 아니라 **오분류 버킷**이다(진짜 선수금 0건; 실제 booking=차량할부 현대캐피탈 ₩395,369×3, 매입인보이스 LG유플러스 등). 선수금 명칭은 3코드(20700·25300·25900)에 분산. 따라서:
- 25300의 8건(거래5+인보이스3)은 **canonical_remap에 넣지 않는다**(category가 다른 재분류). 건별로 올바른 계정에 개별 재배선(차량할부→리스/이자, 통신→81400, 매입→해당 비용). 잠긴 기간이면 §1.4 재분류분개로.
- 25300에 매달린 `standard_account_keywords` 67개는 일괄 re-point 금지 → 키워드별로 올바른 표준에 재타겟(자동학습 오염 방지).
- 선수금 canonical 코드 확정(25900 유력)은 **결산 권위 필요 → §13 열린 결정**.

### 2.7 리스크 / 롤백
- 리스크: is_relabel 오판(category 같다고 가정)으로 마감 재무제표 변형 → 2.3 게이트와 §7 마감 diff=0 게이트로 이중 차단.
- 롤백: `canonical_remap` 역방향(new→old) + `remap_audit`(§7) 역재생으로 8 FK 원복, `is_active=true` 복구. 삭제하지 않았으므로 완전 가역.

---

## 3. GL 재전기 원자성 (P0)

### 3.1 문제
§0-2·§0-3. `transactions.standard_account_id`를 재배선해도 JEL은 전기 시점 스냅샷이라 안 따라온다(`bookkeeping_engine.py:289`). 결과: 발생 IS는 움직이고 BS/CF/연결은 그대로(2차 drift). HOI는 이미 GL std 11/109 desync.

### 3.2 정본(source of truth) 결정 — 법인별 정책
**원칙: GL(`journal_entry_lines`)을 회계 정본으로 단일화**하고 `transactions.standard_account_id`는 입력/표시 + JEL 도출의 트리거로 본다. 단 현 코드가 발생 IS를 transactions에서 직접 읽으므로(§0-2), 완전 단일화 전까지는 **재배선 = 같은 트랜잭션 내 JEL 재전기**를 불변식으로 강제한다.

| 법인 | GL 현황 | 정책 |
|---|---|---|
| 코리아(2) | GL 2614/5373·std 98%·drift 192 | GL 정본화. 재배선 시 자동분개 delete+recreate를 **같은 txn에**. 52건 JEL≠tx std는 재전기로 정렬. 열린 기간만, 마감은 §1.4. |
| 리테일(3) | GL 15건 | 코리아와 동일(소량, 저위험). |
| 홀세일(13) | **GL 0건** | 두 선택: (a) 확정거래 전건 GL 백필 후 GL 정본화, (b) 홀세일 재무제표=transactions+wholesale_* 발생주의로 명시하고 연결에서 special-case. **권장 (a)**(전 그룹 GL 일관) — 단 기초잔액·마감정책 선행 필요 → §13. drift 347 재배선은 (a) 전엔 곧 과거 BS/IS 직접변경이므로 (a) 완료 전 금지. |
| HOI(1) | GL std 11/109 | **최후.** 단독 재무제표는 QBO Report API 경로라 GL 무관(`consolidated.py:74-83`), 그러나 연결은 GL 사용(`:256-281`) → 불일치. HOI는 GL을 QBO에 정합시키거나(또는 연결 HOI 소스를 QBO로 전환) 후 재배선. §5의 듀얼GAAP 경계와 함께 처리. |

### 3.3 메커니즘 — 재배선·재전기 단일 트랜잭션
split 엔드포인트는 이미 모범 패턴이다: splits 저장 → 기존 자동분개 DELETE(조정/마감 보존, `transactions.py:990-999`) → `create_journal_from_transaction` 재생성, 실패 시 전체 ROLLBACK(`:1007-1013`). **이 패턴을 재배선 전 경로에 강제한다.** 구멍은 auto-map target=standard(`:557-579`)가 JEL을 재전기하지 않는 것 → 재배선된 confirmed 거래에 대해 같은 txn에서 자동분개 재전기를 추가해야 한다(아래 §4 sync와 묶음).

의사코드(재배선 1건):
```
BEGIN;
  if period_locked(entity, tx.date):  raise → §1.4 재분류분개 경로로
  UPDATE transactions SET standard_account_id=new WHERE id=tx;
  if tx.is_confirmed:
     DELETE FROM journal_entries WHERE transaction_id=tx AND is_adjusting=false AND is_closing=false;
     create_journal_from_transaction(tx);   -- 차/대 합 검증 내장(:126-130)
  -- 시산표 검증: validate_trial_balance(entity) is_balanced=TRUE 확인
COMMIT;
```

### 3.4 리스크 / 롤백
- 리스크: 조정/마감 분개를 잘못 삭제 → DELETE 조건에 `is_adjusting=false AND is_closing=false` 유지(기존 패턴 그대로).
- 리스크: 재전기 중 일부만 성공 → 단일 txn + 실패 시 ROLLBACK.
- 롤백: `remap_audit`로 tx.std 원복 + JEL 재전기. GL 백필(홀세일)은 batch_id로 식별해 일괄 삭제 가능.

---

## 4. standard sync 강제 (P1) — 트리거 vs 앱계층

### 4.1 문제
§0-8. 내부 잎이 표준의 권위 입력이어야 하는데, 3개 경로가 독립적으로 `transactions.standard_account_id`를 쓴다 → drift 재발원.

### 4.2 비교
| 방식 | 강점 | 약점 |
|---|---|---|
| DB 트리거 | 모든 경로(PATCH·auto-map·split·importer·수동 SQL) 우회 불가. 불변식이 DB에 박힘. | 숨은 동작, 벌크 import 시 매행 발화(성능), 마이그레이션엔 일시 비활성 필요. |
| 앱계층(서비스 함수 단일화) | 명시적·테스트 용이·UX 메시지. | 우회 가능(직접 SQL·새 라우터가 안 거치면 drift 재발). |

### 4.3 권장 — 트리거를 불변식으로, 앱계층은 UX로 (둘 다)
**불변식은 트리거로 강제**(우회 불가가 본질). 단순 도출 규칙:
```sql
-- transactions BEFORE INSERT/UPDATE: 내부 잎이 있고 splits 없으면 표준을 내부에서 도출
CREATE OR REPLACE FUNCTION trg_sync_standard_from_internal() RETURNS trigger AS $$
BEGIN
  IF current_setting('financeone.bypass_std_sync', true) = 'on' THEN
     RETURN NEW;                      -- 통제된 마이그/재전기에서만 우회
  END IF;
  IF NEW.internal_account_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM transaction_splits WHERE transaction_id = NEW.id) THEN
     SELECT standard_account_id INTO NEW.standard_account_id
       FROM internal_accounts WHERE id = NEW.internal_account_id;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
```
규칙 요지: splits 있으면 라인별 split이 권위(트리거는 표준 손대지 않음), 내부 잎 있으면 표준=내부.std 도출, 내부 NULL이면 직접 표준 허용(미분류 거래). 이러면 auto-map target=standard의 독립 쓰기(`transactions.py:557-565`)가 내부와 어긋나도 트리거가 도출값으로 덮어 drift를 원천 차단한다.

**앱계층은 유지**: PATCH의 splits 보호 409(`:347-357`)와 내부→표준 도출(`:421-432`)은 좋은 UX 메시지 → 트리거의 사용자 친화 버전으로 병존. 트리거는 안전망, 앱은 설명.

### 4.4 INSERT 시 NEW.id 부재 문제 (정확성 주의)
INSERT BEFORE 트리거에서 splits 조회는 NEW.id가 아직 없을 수 있음 → INSERT엔 splits 없음을 가정(신규 거래는 split 동시 생성 안 됨), UPDATE에만 splits 존재 검사. 또는 AFTER 트리거 + 별도 정합. **구현 시 검증 필요(§13).**

### 4.5 리스크 / 롤백
- 리스크: 벌크 import 성능 → import 경로는 `bypass_std_sync=on` 후 일괄 정합 1회.
- 롤백: 트리거 DROP. 데이터는 이미 일관(트리거가 만든 상태가 정답).

---

## 5. 듀얼 GAAP 하드 경계 (P1)

### 5.1 버그
`consolidated.py:256-281`: `base_currency=="USD" AND currency=="USD"`(=HOI) 분기에서 `convert_kgaap_to_usgaap(conn, balances)` 호출(`:260`). 이 함수는 K-GAAP→US 변환 전용이다. HOI 계정은 이미 US_GAAP(`gaap_type='US_GAAP'`, §0-5)인데 K로 간주해 다시 변환 → 듀얼 GAAP 경계 침범. 현재는 HOI 계정에 `gaap_mapping` 행이 없으면 무변환 passthrough라 우연히 무해할 수 있으나(`gaap_conversion_service.py:83-92`), 코드가 매핑이 있으면 오변환하는 **잠복 버그**다.

### 5.2 수정안 — currency가 아니라 gaap_type로 경계
1. `get_all_account_balances`가 `sa.gaap_type`를 함께 반환(`bookkeeping_engine.py:473-489` SELECT에 컬럼 추가).
2. 연결 HOI 분기: 잔액을 gaap_type로 분리 — `US_GAAP`은 **passthrough**(이미 US, 변환 금지), `K_GAAP`만 `convert_kgaap_to_usgaap`. HOI가 전부 US_GAAP이면 사실상 passthrough.
3. `convert_kgaap_to_usgaap`는 `gaap_type='US_GAAP'` 계정을 받으면 skip(또는 거부)하도록 가드.
```
# consolidated.py HOI 분기 의사코드
k_bal  = [b for b in balances if b["gaap_type"] == "K_GAAP"]
us_bal = [b for b in balances if b["gaap_type"] == "US_GAAP"]
converted = convert_kgaap_to_usgaap(conn, k_bal) + passthrough(us_bal)
assert all(b["gaap_type"]=="US_GAAP" for b in us_bal)  # HOI에 K행 있으면 데이터오류 경보
```

### 5.3 전제 검증 (열린 결정 연계)
이 수정이 옳으려면 **HOI의 transactions/JEL이 US_GAAP-typed standard_accounts를 참조**해야 한다. HOI GL desync(11/109)와 맞물려 — HOI 정리(최후) 시 HOI 분개가 어떤 gaap_type 표준을 가리키는지 실측 후 경계 적용. 그 전까지 passthrough는 K코드 누출 위험 → §13.

### 5.4 리스크 / 롤백
- 리스크: HOI에 K_GAAP 행이 섞여 있으면 passthrough가 K코드를 US 재무제표에 노출 → 5.2의 assert/경보로 탐지.
- 롤백: 코드 변경(이 phase는 설계만). 데이터 무변경이라 가역.

---

## 6. 운영태그 스키마 (롤업 영향 0)

### 6.1 DDL (internal_accounts에 직교 태그 신설)
```sql
ALTER TABLE internal_accounts
  ADD COLUMN IF NOT EXISTS cost_behavior   TEXT
        CHECK (cost_behavior IN ('fixed','variable')),   -- 고정/변동, NULL=미지정
  ADD COLUMN IF NOT EXISTS is_subscription BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS cost_center     TEXT;          -- 부문/프로젝트(마트약국·ODD·3PL·리테일…)
```
기존 `owner`(담당자)는 제외(결제 1인, context-notes 결정), `is_recurring`(`schema.sql:59`)은 존치·활용.

### 6.2 롤업 영향 0 보장 (코드 grounding)
어떤 재무제표 롤업도 `internal_accounts`의 태그 컬럼을 읽지 않는다:
- 발생 IS: `transactions JOIN standard_accounts`만 (`income_statement_accrual.py:124-137`).
- BS/현금/연결: `standard_accounts JOIN journal_entry_lines`만 (`bookkeeping_engine.py:473-489`), 연결은 `category` (`consolidated.py`).
→ `internal_accounts`에 nullable 컬럼 추가는 모든 롤업에 불가시. 태그는 OpEx 구독탭·코쿼핏 cost_center 필터·고정/변동 분석 전용. **재무제표 숫자 영향 0**(설계상 보장).

### 6.3 리스크 / 롤백
- 리스크: cost_center 카디널리티 — 한 잎이 여러 부문에 걸치면 단일 컬럼 부족(약국식비 사례). 시작은 잎당 1부문, N:N 발생 시 junction 테이블로 escalate → §13.
- 롤백: 컬럼 DROP(가역, 데이터 손실은 태그값뿐).

---

## 7. 마이그 감사 · 전후 diff · 명시승인 게이트

### 7.1 remap_audit 테이블
```sql
CREATE TABLE IF NOT EXISTS remap_audit (
  id          SERIAL PRIMARY KEY,
  batch_id    UUID NOT NULL,
  table_name  TEXT NOT NULL,
  row_id      INTEGER NOT NULL,
  column_name TEXT NOT NULL,
  old_value   INTEGER,
  new_value   INTEGER,
  entity_id   INTEGER,           -- 영향 행의 법인(가능 시) — 절대원칙 준수
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reverted_at TIMESTAMPTZ
);
```
§2.4·§3.3의 모든 FK UPDATE가 행별 old→new를 여기 기록 → 정확한 역재생 가능.

### 7.2 전후 diff 리포트 (read-only, 게이트)
적용 전/후로 영향 기간의 재무제표를 재생성해 `financial_statement_line_items`를 line_key 단위로 diff하는 read-only 스크립트:
- **마감(잠긴) 기간 diff = 0** 이어야 통과(순수 재라벨·재전기는 by construction 0). 0 아니면 ABORT.
- 열린 기간 diff는 의도된 변화(drift 정정)와 일치하는지 사람이 확인.
- 불변식 동시 검증: sum(debit)==sum(credit)(`validate_trial_balance` `bookkeeping_engine.py:344-385`), BS 항등식(`consolidated.py:538` 패턴), 현금흐름 루프.

### 7.3 명시승인 게이트
prod 적용은 **dry-run(별도 트랜잭션 BEGIN…ROLLBACK) → diff 리포트 → 사장님 명시승인** 후에만. preflight·이 설계 모두 read-only 원칙(프로덕션 DATABASE_URL은 SELECT 외 금지) 준수. 승인 없는 prod write 금지.

### 7.4 롤백
batch_id 단위로 `remap_audit` 역재생(new→old) + `reverted_at` 기록. canonical은 `is_active=true` 복구. 완전 가역.

---

## 8. 롤업 권위 결정

### 8.1 현황 (재확인)
롤업 = `category`/`subcategory`(§0-4). `parent_code`는 롤업 무구동. 발생 IS는 PDF와 99.2% 정합(`income_statement_accrual.py` docstring) — 검증된 자산.

### 8.2 권장 — category/subcategory를 롤업 권위로 **유지**, parent_code는 입력/UI + 정합성 제약
- **이유**: (a) 검증된 결과를 깨지 않음(저위험), (b) PoC 범위 최소화, (c) 진짜 트리(재귀 parent_code) 롤업 구현은 statement 5종·연결 전부 재작성 + 테스트 재구축이라 큰 변경인데 즉시 이득 없음.
- 대신 **무결성 제약**을 둔다: 각 표준 계정의 `(category, subcategory)`가 `parent_code` 사슬과 모순되지 않는지 검증하는 read-only 체크(예: 자식의 category == 부모 사슬의 category). parent_code는 "트리를 구동하는 척"이 아니라 명시적으로 **시각화/입력 구조 + 정합 제약**임을 문서화.
- **트레이드오프**: category/subcategory는 2레벨 비정규화 롤업이라 3레벨+ 계층은 표현 불가. GAAP 골격이 더 깊은 계층을 요구하면 그때 진짜 트리 롤업을 테스트와 함께 도입(후속 phase). 지금은 안 한다.

### 8.3 생성기 `_gen_tree_html.py` 비권위 명시
리뷰 P2: 생성기는 live DB 접속·entity2 하드코딩·first-code-match·"사입→40100 상품매출"(COGS여야)·25200→26200(plan 25300과 충돌) 버그 보유 → **시각화 전용·비권위**로 명시, is_active/gaap 필터 적용, remap 로직 제거. 롤업·매핑 권위 아님.

---

## 9. 코리아(2) PoC 실행계획

PoC는 **법인-스코프 작업**(내부 재배치·drift 정렬·태그)에 한정. 전역 차트 일원화(§2)는 별도 전역 마이그레이션으로 선행하되 전 법인 마감 diff=0 게이트로 통과(코리아 검증 포함).

### 9.1 단계 (순서 필수)
0. **사전 스냅샷**: 코리아 cash+accrual 전월(YTD) 재무제표 생성 → line item 아카이브. preflight 재실행해 drift=192·NULL=22 재확인.
1. **M1 스키마**(전역, 가역): fiscal_period_locks·canonical_remap·remap_audit + internal_accounts 운영태그 3컬럼.
2. **마감 잠금 설정**: 코리아 마감 월을 `fiscal_period_locks`에 등록 + locked statement 보존 가드.
3. **전역 차트 일원화(M2)**: §2 게이트(롤업키 동일=재라벨, gaap 이관, 25300 제외) → 전 법인 마감 diff=0 검증, 코리아 재무제표 불변 확인.
4. **코리아 내부 백필**: 22 NULL `internal.standard_account_id` 채움(결산 권위 입력 필요·§13), 내부 잎을 표준 골격 밑으로 재배치(self-ref parent_id 기능그룹 보존, plan §타깃모델), 운영태그 부여.
5. **코리아 drift 정렬(192건)**: 열린 기간은 `transactions.std := internal.std` + 같은 txn JEL 재전기(§3.3). 잠긴 기간 drift는 §1.4 재분류분개.
6. **M3 sync 트리거** 활성(§4).
7. **검증(게이트)**: 
   - drift=0(코리아 전건 `transactions.std == internal.std`).
   - **두 엔진 모두**: 발생(transactions 읽기)·GL(BS/현금/연결) 재생성 → 마감기간 vs 0단계 스냅샷 **diff=0**.
   - 타깃 월 가결산 PDF 라인 대조(plan: 판관비 484,081,859 등 일치).
   - sum(debit)==sum(credit), BS 항등식, 현금흐름 루프 PASS.
8. **승인 후 prod 적용**(§7.3).

### 9.2 롤백
각 단계가 가역 마이그레이션(§10) + remap_audit 역재생. 7단계 게이트 실패 시 즉시 원복, prod 무변경.

### 9.3 다음 법인
리테일(3, 소량) → 홀세일(13, GL 백필 정책 §3.2 선결) → HOI(1, 듀얼GAAP 경계 §5 + GL desync 해소, 최후).

---

## 10. Alembic 마이그레이션 분해

현재 단일 head = **`l8m9n0o1p2q3`**(ssart_masters, 2026-06-07 `alembic` 그래프 실측, 체인 39개 선형). 신규 마이그레이션은 head에서 분기. **WIP 마이그레이션이 계속 land 중이므로 구현 시 `alembic heads`로 head 재확인 필수**(추측 금지).

| # | 마이그레이션 | 내용 | 가역성 |
|---|---|---|---|
| M1 | `*_account_tree_schema` | fiscal_period_locks·canonical_remap·remap_audit 신설 + internal_accounts 운영태그 3컬럼 + 잠금 트리거 함수(비활성 상태로 생성) | downgrade=테이블/컬럼/함수 DROP. 데이터 무변경, 완전 가역. |
| M2 | `*_canonical_chart_remap` | canonical_remap 채움 → 8 FK 재배선 → gaap 이관 → is_active=false. **데이터 마이그레이션**, 전역, 마감 diff=0 게이트 | downgrade=remap_audit 역재생 + is_active 복구. 가역(삭제 안 함). |
| M3 | `*_std_sync_trigger` | transactions sync 트리거 ENABLE + (선택) 잠금 트리거 ENABLE | downgrade=트리거 DROP. 데이터는 이미 일관, 가역. |
| M4 | `*_korea_internal_backfill` | 코리아 내부 std NULL 채움·재배치·태그·drift 정렬·GL 재전기(법인-스코프) | downgrade=remap_audit/배치 역재생. JEL 재전기는 batch_id로 식별 후 원복. |
| (M5+) | 법인별 반복 | 리테일·홀세일(GL 백필 별도 마이그)·HOI(듀얼GAAP) | 동일 패턴. |

순서 원칙: **스키마 신설(M1) → 전역 remap(M2) → 트리거(M3) → 법인별 백필(M4+)**. 트리거를 remap보다 먼저 켜면 대량 재배선이 매행 발화 → M2/M4의 대량 작업은 `bypass_std_sync=on` 세션에서 수행 후 M3에서 켠다. 각 단계는 독립 가역이라 부분 롤백 가능(절대원칙: entity_id 누락 0, 모든 신규 재무 테이블 entity_id 보유 — canonical_remap은 전역 카탈로그라 예외이나 remap_audit이 entity_id로 영향 추적).

---

## 11. 재무 정확성 절대원칙 — 본 설계의 준수 매핑
- **sum(debit)==sum(credit)**: 모든 재배선이 `create_journal_entry`의 합 검증(`bookkeeping_engine.py:126-130`)을 통과하는 재전기로만 GL을 바꾼다. 직접 JEL UPDATE는 순수 재라벨(§2.3, 차/대 보존)만.
- **BS 항등식**: §7.2 게이트가 매 적용 후 `is_balanced` 검증(`consolidated.py:538`).
- **현금흐름 루프**: §7.2에서 동시 검증. CF가 10100만 읽는 기존 한계(리뷰 P1)는 본 트리 재설계 범위 밖(별도 백로그)이나, 마감 diff=0 게이트가 회귀 방지.
- **entity_id 누락 금지**: fiscal_period_locks·remap_audit 모두 entity_id 보유. 신규 운영태그는 entity_id 가진 internal_accounts에 부착.

---

## 12. 의존·순서 요약 (한눈)
1. 기간잠금(§1)이 **모든 것의 전제** — 없으면 어떤 재배선도 과거를 조용히 덮어쓴다.
2. 전역 차트 일원화(§2)는 법인-스코프 아님 → 전 법인 마감 diff=0 게이트로 1회 전역 수행.
3. 재배선=GL 재전기 원자성(§3) + sync 트리거(§4)가 drift 재발을 구조적으로 차단.
4. 듀얼GAAP 경계(§5)는 HOI(최후)에서 확정.
5. 운영태그(§6)는 롤업 무영향이라 언제든 안전 추가.
6. 감사·diff·승인(§7)이 매 적용의 안전벨트.
7. 롤업 권위는 category/subcategory 유지(§8) — PoC 범위 최소화.

---

## 13. 열린 결정 / 추가 입력 필요 (정식설계가 못 정한 것)
1. **선수금 canonical 코드** — 25900 유력하나 결산 권위 확정 필요(20700/25300/25900 중). 25300 8건의 건별 올바른 계정(차량할부→리스 vs 이자, 매입→비용 코드)도 결산 대조 필요. (`~/Documents/HanahOneAll` 결산, 본 작업 범위 밖이라 미열람.)
2. **gaap_mapping 신규 행** — 사용>0·gaap=0인 한국 결산코드 ~12개(82200·29300·26000·93100 등)의 US GAAP 대응 코드 = 결산/QBO 권위 필요.
3. **canonical 42그룹 is_relabel 판정** — 그룹별 old/new의 (category, subcategory, normal_side) 동일성 실측 게이트 결과에 따라 재라벨 vs 재분류 분기(자동 가정 금지).
4. **마감 기준일** — 어느 월부터 fiscal_period_locks를 채울지(회계법인 마감 일정).
5. **홀세일 GL 정책** — (a) 전건 GL 백필 vs (b) transactions/wholesale_* 발생주의 명시. 권장 (a)이나 기초잔액·마감정책 선행 필요.
6. **HOI gaap_type 실측** — HOI transactions/JEL이 US_GAAP-typed 표준을 참조하는지 확인 후 §5 passthrough 경계 확정. HOI 연결 소스를 GL vs QBO 중 무엇으로 둘지.
7. **sync 트리거 INSERT 타이밍** — BEFORE INSERT에서 splits 조회 불가 문제(§4.4)를 BEFORE(splits 없음 가정) vs AFTER 정합 중 무엇으로 구현할지 검증 필요.
8. **cost_center 카디널리티** — 잎당 1부문(컬럼) 시작, N:N 발생 시 junction 테이블 escalate 시점.
9. **transaction.standard 도출 vs 동기화** — context-notes 권장은 "동기화 유지"(쿼리 영향 최소). 단 §3.2의 GL 정본화 방향과 정합하려면 장기적으로 `transactions.standard`를 캐시로 강등할지 재확인.

---

## 14. 리뷰 반영 — 필수 수정 (plan-eng-review + codex outside-voice, 2026-06-07)

이 설계는 plan-eng-review(아키텍처 4섹션) + codex 독립 검증을 거쳤다. **개념은 GO, 그러나 메커니즘에 코드 근거 구멍 다수 → 구현 전 아래 전부 반영.** 두 리뷰는 모순 없이 합의+확장.

### 14.0 스코프 결정 (확정)
- **D1 — 전역 42그룹 차트 일원화(§2)를 코리아 PoC에서 분리.** PoC = entity-scoped(코리아 내부 재배치·drift 정렬·운영태그) + 안전장치(잠금·감사·GL재전기·sync). 전역 차트 일원화는 **별도 후속 게이트 마이그**(전 법인 마감 diff=0). → §9.1 step 3(M2 전역 일원화)을 PoC critical path에서 제거, 별도 phase로.
- **A1 — 잠긴 재무제표는 별도 불변 아카이브 테이블로 스냅샷·거기서 서빙**(live line_items 가드 아님). 재무기록 감사용 불변.

### 14.1 🔴 CRITICAL (PoC 재설계 수준)
- **C1. GL 재전기 ≠ 순수 remap** (`bookkeeping_engine.py:247-276`). `create_journal_from_transaction`이 **현재** source-type·카드정산 규칙을 replay → 과거 코리아 거래 재전기 시 std 라인뿐 아니라 현금/은행/AP 라인까지 변경 → debit==credit이어도 99.2% PDF 정합 깨질 위험. → §3.3 수정: 재전기 대신 **해당 std 라인만 in-place 수정**(차/대 보존) 또는 재전기 전후 비-std 라인 동일성 assert. 전건 재전기 금지.
- **C2. 잠금 가드가 엉뚱한 DELETE 겨냥.** `_get_or_create_statement()`(`helpers.py:40-49`)가 `consolidated.py:67` 이전에 line_items 삭제 → consolidated.py:67만 막으면 무력. → 가드를 helpers 삭제 지점 + 모든 삭제 경로로.
- **C3. `status='locked'`가 API 계약에 없음.** 라우터는 draft|finalized만(`statements.py:247-259`), 생성·삭제·수정이 finalized만 보호(`:189-193·:220-239·:298-300`). 새 locked는 **모든 앱 경로 수정 OR DB 트리거 보호** 없이는 편집·삭제 가능 → **아카이브는 앱가드 아닌 DB 레벨 BEFORE DELETE/UPDATE 트리거로 강제**(스크립트 `import_2025_finalized_*.py`도 우회 경로).
- **C4. 기간잠금이 입력 테이블 과소.** 트리거 transactions/JEL/splits만(§1.3-A). 발생 재무제표는 `wholesale_sales·wholesale_purchases·balance_snapshots·ar_opening_balances·payee_aliases`도 읽음(`income_statement_accrual.py:61-76`, `balance_sheet_accrual.py:49-189`) → 잠긴 발생 BS/IS 조용히 변경 가능. §1.5 표엔 있는데 §1.3 트리거엔 빠짐(자체 모순). → 잠금 트리거를 이 입력 전부로 확장 or diff 게이트로 강제.

### 14.2 🟠 HIGH
- **H1. 재전기가 조정/마감 분개 있으면 실패.** 엔진이 거래에 기존 분개 있으면 거부(`bookkeeping_engine.py:238-245`). §3.3(auto 삭제+조정 보존+recreate)는 조정 JE 존재 시 throw → 재전기 전 거래의 조정/마감 JE 유무 분기.
- **H2. 인보이스 분개는 재전기 밖.** 인보이스 JEL은 `transaction_id=None`(`invoice_service.py:202-209`) → 거래기반 재전기 미갱신 → invoice std remap 시 GL desync. → 인보이스-origin JE 별도 재배선 경로.
- **H3. "읽기전용 diff 재생성"이 거짓.** §7.2 diff가 line_items 재생성을 read-only로 가정하나 재생성은 파괴적 write(`helpers.py:42-48`) → **in-memory 계산 또는 temp/scratch schema**로 변경.
- **H4. BS 항등식 게이트 무의미.** 발생 BS가 자본을 plug로 강제균형(`balance_sheet_accrual.py:277-300`) → assets=liab+equity 항상 통과. **진짜 게이트는 diff=0**(BS 항등식은 보조).
- **H5. std-sync 트리거가 split 삭제 누락.** split DELETE(`transactions.py:1034-1067`)가 stale tx std로 재생성 → BEFORE UPDATE 트리거 미발화. → split DELETE 경로도 sync.
- **H6. drift=0 기준이 splits에서 무효.** split 거래는 tx.std=첫 split(레거시 표시)(`transactions.py:1001-1005`) → `tx.std==internal.std` 불변식은 split 거래 제외 or split 라인 비교.

### 14.3 🟡 MEDIUM
- **M1.** 잠금 `basis`(cash/accrual) 비정합 — tx/JEL write가 두 basis 다 영향. "cash 열림·accrual 잠김" 불가 → basis 차원 재고(both만 의미).
- **M2.** YTD/분기 잠금 — locks는 월, statements는 범위(`schema.sql:191-194`) → 겹치는 잠긴 월 전부 차단.
- **M3.** `remap_audit.entity_id` nullable이 절대원칙 위반(§7.1) → 전역작업도 영향 entity 명시행 or global-op+entity-impact 분리.
- **M4.** `transaction_splits.entity_id` 신뢰불가(제약 없음, `schema.sql:429-433`) → 잠금/감사는 transactions JOIN.
- **M5.** is_relabel 게이트 불충분 — 재무제표 생성기가 표준코드 **리터럴 참조**(`balance_sheet_accrual.py`: `'40100'·'10800'·'10300'·'25500'·'30100'`, `consolidated.py:353` `'39200'` CTA, `:482` 결손금). 같은 category여도 리터럴코드 remap 시 깨짐(특히 자본금 30100=dup레거시+하드코딩). → is_relabel 게이트에 **코드-리터럴 의존 스캔** 추가(전역 일원화 마이그 시점).
- **M6.** CF 루프 게이트 약함 — CF가 10100만 읽는데 엔진은 은행을 10300 매핑(`cash_flow.py` vs `bookkeeping_engine.py:60-67`) → 루프 통과해도 은행현금 사라질 수 있음(기존 [[project_cash_10100_journal_bug]], 본 작업 범위 밖이나 게이트 신뢰도 한계 인지).
- **M7.** mapping_rules remap 시 both-ids 불변 유지(prior learning 10/10) — standard만 옮기고 internal 정합 점검.

### 14.4 테스트 (구현 시 필수, pytest 인바리언트 확장)
잠금 트리거 거부+bypass GUC / is_relabel 게이트 category-mismatch 차단 / remap 원자성 실패 롤백 / GL 재전기 후 trial balance debit==credit / 잠긴기간 전후 diff=0 / HOI passthrough(US_GAAP 무변환) / split 거래 drift 기준 제외.

### 14.5 성능
잠금·sync 트리거가 bulk import(codef/ssart) 시 행마다 발화 → (entity_id, period) 인덱스 단일조회·당월 fast-negative·bulk는 bypass GUC 후 1회 정합.

### 14.6 판정
**GO-with-fixes (significant).** 개념·스코프(분리) 확정. C1·C4가 PoC 메커니즘 재설계 수준 → 위 CRITICAL/HIGH 전부 반영 후 구현 착수. 다음: 결산 권위 입력(§13 1·2·4·5) 확보 + C1~C4 반영한 §1/§3/§7 개정 → 코리아 PoC 구현(발생+GL 두 엔진 PDF 대조).

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open | 2 decisions + 16 outside-voice gaps (4 critical, 6 high, 7 medium) |
| Outside Voice | codex | Independent 2nd opinion | 1 | issues_found | 16 code-grounded gaps, no cross-model tension (agreement+extension) |

- **CROSS-MODEL:** 텐션 없음 — codex가 리뷰와 모순 없이 16건 확장. 가장 무거운 C1(GL 재전기 replay)·C4(잠금 입력 과소)는 architect 문서가 놓친 것.
- **결정(확정):** D1 전역 차트 일원화 PoC서 분리 / A1 잠긴 재무제표 불변 아카이브 스냅샷.
- **UNRESOLVED:** §13 열린결정 9건(결산권위 입력 대기) + §14 CRITICAL/HIGH 10건(구현 전 설계 개정 필요).
- **VERDICT:** ENG REVIEW = GO-with-fixes. 개념·스코프 CLEARED. 구현 착수 전 §14.1·14.2 반영 필수. 코드/DB 무변경(설계 단계).

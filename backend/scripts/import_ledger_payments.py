"""회계법인 계정별원장의 결제/회수 행 → 분개 동기화 (P3-10-1).

외상매입금(25100) 시트 차변 행 = 결제 — 외상매입금 차감.
외상매출금(10800) 시트 대변 행 = 회수 — 외상매출금 차감.

각 결제/회수 행에 대해:
1) 우리 transactions 와 매칭 (날짜±days_window, 금액 일치, 거래처 fuzzy):
   - 매칭됨 → tx.standard_account_id 를 25100 / 10800 으로 변경 (마이그레이션 재실행 권장).
2) 매칭 안 됨 → 다른 은행 결제로 간주, 분개 직접 추가:
   - (차) 25100 / (대) 10300 (외상매입 결제)
   - (차) 10300 / (대) 10800 (외상매출 회수)
   - description 에 'ledger:25100:YYYY-MM-DD:거래처:금액' marker (재실행 시 중복 방지).

사용:
    # 1단계: 매칭 미리보기
    python -m backend.scripts.import_ledger_payments \\
        --entity 2 --year 2026 \\
        --file '/path/to/계정별원장.xls' --dry-run

    # 2단계: tx std 변경 + ledger-only 분개 추가
    python -m backend.scripts.import_ledger_payments \\
        --entity 2 --year 2026 \\
        --file '/path/to/계정별원장.xls' --commit

    # 그 후 마이그레이션 재실행:
    python -m backend.scripts.migrate_journal_entries_to_accrual \\
        --entity 2 --year 2026 --month 1 --commit
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
import xlrd
from dotenv import load_dotenv

load_dotenv()


# 시트 이름 → (direction, target_std_code)
LEDGER_PAYMENT_SHEETS = {
    "10_외상매입금(25100)": ("purchase", "25100", "debit"),   # 차변 = 결제
    "1_외상매출금(10800)":  ("sales",     "10800", "credit"),  # 대변 = 회수
}

CASH_ACCOUNT_CODE = "10300"  # 보통예금 (회계법인 원장 결제 채널 대부분 은행)


@dataclass
class LedgerPayment:
    direction: str           # "purchase" or "sales"
    issue_date: date
    counterparty: str        # 회계법인 원장 거래처명
    amount: Decimal
    note: str
    std_code: str            # 25100 / 10800

    @property
    def marker(self) -> str:
        """journal_entries.description 에 들어가는 중복 방지 marker."""
        return f"ledger:{self.std_code}:{self.issue_date}:{self.counterparty[:30]}:{int(self.amount)}"


def _parse_date(date_str: str, year: int) -> date | None:
    s = str(date_str).strip()
    if not s or "-" not in s:
        return None
    try:
        m, d = s.split("-")
        return date(year, int(m), int(d))
    except (ValueError, IndexError):
        return None


def _normalize_counterparty(name: str) -> str:
    """거래처명 fuzzy match 용 정규화 — 핵심 한글 토큰만 추출."""
    s = str(name or "").strip()
    # 은행명 prefix 제거
    s = re.sub(r"^(국민|기업|하나|신한|우리|F/B\s?출금|F/B\s?입금|인터넷|모바일|펌뱅킹|대체입금|지로자동|관세납부|S1)\s*", "", s)
    # 회사형태 정규화
    s = re.sub(r"\(주\)|㈜|주식회사|유한회사", "", s)
    s = re.sub(r"\([^)]*\)", "", s)  # 괄호 안 영문 등 제거
    s = re.sub(r"[\s\u3000\u00a0]+", "", s)  # 공백 제거
    return s


def _counterparty_key(name: str, length: int = 4) -> str:
    """fuzzy match 키 — 정규화 후 앞 N 글자."""
    return _normalize_counterparty(name)[:length]


def _amount_match(a: Decimal, b: Decimal, tolerance: int = 10) -> bool:
    """금액 정확 일치 또는 tolerance 원 이내 차이 허용."""
    return abs(a - b) <= tolerance


def extract_ledger_payments(file_path: str, year: int) -> list[LedgerPayment]:
    wb = xlrd.open_workbook(file_path)
    payments: list[LedgerPayment] = []
    for sheet_name, (direction, std_code, side) in LEDGER_PAYMENT_SHEETS.items():
        if sheet_name not in wb.sheet_names():
            continue
        sh = wb.sheet_by_name(sheet_name)
        for r in range(5, sh.nrows):
            note = str(sh.cell_value(r, 1)).strip()
            if "[ 월" in note or "[ 누" in note:
                continue
            date_str = str(sh.cell_value(r, 0)).strip()
            cp = str(sh.cell_value(r, 3)).strip()
            try:
                dr = Decimal(str(sh.cell_value(r, 4) or 0))
                cr = Decimal(str(sh.cell_value(r, 5) or 0))
            except Exception:
                continue
            issue_d = _parse_date(date_str, year)
            if not issue_d:
                continue
            amount = dr if side == "debit" else cr
            if amount <= 0:
                continue
            payments.append(LedgerPayment(
                direction=direction, issue_date=issue_d,
                counterparty=cp, amount=amount,
                note=note[:100], std_code=std_code,
            ))
    return payments


def find_matching_tx(
    cur, entity_id: int, p: LedgerPayment, days_window: int = 3,
) -> int | None:
    """우리 transactions 에서 같은 결제/회수 거래 찾기.

    조건: 날짜 ±window, 금액 정확 일치, 거래처/적요 정규화 후 substring match.
    direction=purchase → tx.type='out', direction=sales → tx.type='in'.

    여러 후보 중 가장 가까운 날짜 + counterparty 일치도 높은 1건 선택.
    """
    tx_type = "out" if p.direction == "purchase" else "in"
    cp_key = _counterparty_key(p.counterparty)
    if not cp_key:
        return None

    # 1차: 정확 금액 (±10원). 거래처 fuzzy 적용.
    # 2차: 거래처 strong match + 같은 날짜 → 금액 ±20,000원 (수수료/통관세 차이 허용).
    ledger_norm = _normalize_counterparty(p.counterparty)
    best = None
    best_score = -1

    def _score(tx_id, tx_date, tx_cp, tx_desc, strong_amt: bool) -> int:
        tx_cp_norm = _normalize_counterparty(tx_cp or "")
        tx_desc_norm = _normalize_counterparty(tx_desc or "")
        s = -1
        # ① ledger 핵심 토큰이 tx counterparty 에 포함 (strong)
        if cp_key and cp_key in tx_cp_norm:
            s = 100 - abs((tx_date - p.issue_date).days)
        # ② 역방향: tx 의 핵심 토큰(앞 4글자) 이 ledger cp 에 포함 (strong)
        elif tx_cp_norm and tx_cp_norm[:4] and tx_cp_norm[:4] in ledger_norm:
            s = 90 - abs((tx_date - p.issue_date).days)
        # ③ ledger cp 핵심 토큰이 tx description 에 포함 (medium)
        elif cp_key and cp_key in tx_desc_norm:
            s = 70 - abs((tx_date - p.issue_date).days)
        # ④ description 에서 ledger cp 앞 3글자 검색 (weak)
        elif cp_key and cp_key[:3] and cp_key[:3] in tx_desc_norm:
            s = 40 - abs((tx_date - p.issue_date).days)
        # 금액 tolerance 가 큰 (2차) 매칭은 strong 만 허용
        if not strong_amt and s < 90:
            return -1
        return s

    # 1차: 정확 금액
    cur.execute(
        """
        SELECT id, date, counterparty, description, amount
        FROM transactions
        WHERE entity_id = %s AND type = %s
          AND date BETWEEN %s AND %s
          AND amount BETWEEN %s AND %s
          AND (is_cancel IS NOT TRUE) AND is_duplicate = false
        ORDER BY date
        """,
        [entity_id, tx_type,
         p.issue_date - timedelta(days=days_window),
         p.issue_date + timedelta(days=days_window),
         p.amount - 10, p.amount + 10],
    )
    for tx_id, tx_date, tx_cp, tx_desc, tx_amt in cur.fetchall():
        s = _score(tx_id, tx_date, tx_cp, tx_desc, strong_amt=True)
        if s > best_score:
            best_score, best = s, tx_id
    if best is not None:
        return best

    # 2차: 거래처 strong match + 같은 날짜 → 금액 ±20,000원 허용
    cur.execute(
        """
        SELECT id, date, counterparty, description, amount
        FROM transactions
        WHERE entity_id = %s AND type = %s
          AND date BETWEEN %s AND %s
          AND amount BETWEEN %s AND %s
          AND (is_cancel IS NOT TRUE) AND is_duplicate = false
        ORDER BY date
        """,
        [entity_id, tx_type,
         p.issue_date - timedelta(days=1),
         p.issue_date + timedelta(days=1),
         p.amount - 20000, p.amount + 20000],
    )
    for tx_id, tx_date, tx_cp, tx_desc, tx_amt in cur.fetchall():
        if abs(Decimal(str(tx_amt)) - p.amount) <= 10:
            continue  # 1차에서 처리됐어야 함 — skip
        s = _score(tx_id, tx_date, tx_cp, tx_desc, strong_amt=False)
        if s > best_score:
            best_score, best = s, tx_id
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--days-window", type=int, default=3)
    parser.add_argument("--purchase-only", action="store_true",
                        help="외상매입금 결제만 처리 (외상매출금 회수 skip)")
    parser.add_argument("--apply-unmatched", action="store_true",
                        help="unmatched ledger 결제도 분개 직접 추가 (이중차감 위험 — 검토 후 사용)")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    print(f"\n=== 회계법인 원장 결제/회수 → 분개 동기화 ===")
    print(f"  entity={args.entity}, year={args.year}")
    print(f"  file={args.file}")
    print(f"  mode={'DRY-RUN' if args.dry_run else 'COMMIT'}\n")

    payments = extract_ledger_payments(args.file, args.year)
    if args.purchase_only:
        payments = [p for p in payments if p.direction == "purchase"]
    print(f"  총 결제/회수 행: {len(payments)}건")
    by_dir = {"purchase": 0, "sales": 0}
    for p in payments:
        by_dir[p.direction] += 1
    print(f"    purchase(결제): {by_dir['purchase']}")
    print(f"    sales(회수):    {by_dir['sales']}\n")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    cur.execute("SELECT code, id FROM standard_accounts")
    code_to_id = dict(cur.fetchall())

    matched: list[tuple[LedgerPayment, int]] = []
    unmatched: list[LedgerPayment] = []
    for p in payments:
        tx_id = find_matching_tx(cur, args.entity, p, days_window=args.days_window)
        if tx_id:
            matched.append((p, tx_id))
        else:
            unmatched.append(p)

    print(f"=== 매칭 결과 ===")
    print(f"  matched (tx 매핑 변경 대상): {len(matched)}건")
    matched_total = sum(p.amount for p, _ in matched)
    print(f"    합계: {float(matched_total):,.0f}\n")
    print(f"  unmatched (ledger-only 분개 추가 대상): {len(unmatched)}건")
    unmatched_total = sum(p.amount for p in unmatched)
    print(f"    합계: {float(unmatched_total):,.0f}\n")

    if args.dry_run:
        print(f"--- matched 샘플 (최대 10건) ---")
        for p, tx_id in matched[:10]:
            cur.execute(
                "SELECT counterparty, description, standard_account_id FROM transactions WHERE id = %s",
                [tx_id],
            )
            tx_cp, tx_desc, tx_std = cur.fetchone()
            cur.execute("SELECT code FROM standard_accounts WHERE id = %s", [tx_std])
            old_code = cur.fetchone()
            old_code = old_code[0] if old_code else "NULL"
            print(f"  [{p.direction}] {p.issue_date} {p.counterparty[:20]:20s} {float(p.amount):>10,.0f}")
            print(f"    → tx#{tx_id} {(tx_cp or '')[:20]:20s} (현재 std={old_code}) → {p.std_code}")

        print(f"\n--- unmatched 샘플 (최대 15건) ---")
        for p in unmatched[:15]:
            print(f"  [{p.direction}] {p.issue_date} {p.counterparty[:25]:25s} {float(p.amount):>12,.0f}  {p.note[:30]}")

        print(f"\n--commit 으로 실행하면:")
        print(f"  1. matched {len(matched)}건의 tx.standard_account_id 변경")
        print(f"  2. unmatched {len(unmatched)}건 ledger 분개 직접 추가")
        print(f"  → 그 후 'migrate_journal_entries_to_accrual --commit' 실행 권장")
        cur.close()
        conn.close()
        return 0

    # ---- COMMIT ----
    print(f"--- COMMIT 시작 ---\n")
    # Step 1: tx.standard_account_id 변경
    remapped = 0
    for p, tx_id in matched:
        target_std_id = code_to_id.get(p.std_code)
        if not target_std_id:
            print(f"  ✗ std_code={p.std_code} 미등록 — skip")
            continue
        cur.execute(
            "UPDATE transactions SET standard_account_id = %s, updated_at = NOW() WHERE id = %s",
            [target_std_id, tx_id],
        )
        remapped += 1
    print(f"  Step 1: tx std 변경 {remapped}건")

    # Step 2: unmatched ledger 분개 직접 추가 (--apply-unmatched 시에만)
    cash_id = code_to_id.get(CASH_ACCOUNT_CODE)
    if not cash_id:
        print(f"  ✗ {CASH_ACCOUNT_CODE} 보통예금 미등록 — abort")
        conn.rollback()
        return 1

    if not args.apply_unmatched:
        print(f"  Step 2: unmatched {len(unmatched)}건 — skip (--apply-unmatched 미지정)")
        unmatched = []

    added = 0
    skipped_dup = 0
    for p in unmatched:
        target_std_id = code_to_id.get(p.std_code)
        if not target_std_id:
            continue
        # 중복 방지: 같은 marker 가 description 에 들어간 분개가 이미 있으면 skip
        cur.execute(
            "SELECT id FROM journal_entries WHERE entity_id = %s AND description LIKE %s LIMIT 1",
            [args.entity, f"%{p.marker}%"],
        )
        if cur.fetchone():
            skipped_dup += 1
            continue

        # 분개 헤더
        if p.direction == "purchase":
            # (차) 외상매입금 / (대) 보통예금
            debit_id, credit_id = target_std_id, cash_id
        else:
            # (차) 보통예금 / (대) 외상매출금
            debit_id, credit_id = cash_id, target_std_id

        desc = f"[ledger] {p.counterparty[:30]} {p.note[:30]} {p.marker}"
        cur.execute(
            """
            INSERT INTO journal_entries
              (entity_id, entry_date, description, transaction_id, created_at, updated_at)
            VALUES (%s, %s, %s, NULL, NOW(), NOW())
            RETURNING id
            """,
            [args.entity, p.issue_date, desc[:500]],
        )
        je_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO journal_entry_lines
              (journal_entry_id, standard_account_id, debit_amount, credit_amount, description)
            VALUES
              (%s, %s, %s, 0, %s),
              (%s, %s, 0, %s, %s)
            """,
            [
                je_id, debit_id, p.amount, p.counterparty[:200],
                je_id, credit_id, p.amount, p.counterparty[:200],
            ],
        )
        added += 1

    print(f"  Step 2: ledger 분개 추가 {added}건 (중복 skip {skipped_dup})")

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n=== 완료 ===")
    print(f"  matched tx 수정: {remapped}")
    print(f"  ledger-only 분개 추가: {added}")
    print(f"\n다음 단계:")
    print(f"  python -m backend.scripts.migrate_journal_entries_to_accrual \\")
    print(f"    --entity {args.entity} --year {args.year} --month 1 --commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())

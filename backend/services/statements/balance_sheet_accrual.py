"""발생주의 재무상태표 — wholesale_sales/purchases + balance_snapshots 기반.

설계 doc: docs/statements-accrual-plan.md (Phase B, 옵션 A)

balance_sheet.py 의 generate_balance_sheet() 를 wrapper 로 호출하면서:
  1. net_income_override = IS_accrual.net_income 전달 (위험 1 대응 — BS/IS net_income 일관성)
  2. extra_balances 로 합성 잔액 추가:
     자산:
       - 10300 보통예금 (당좌자산) = balance_snapshots 의 'bank' 잔고 (as_of_date 까지의 최신)
       - 10800 외상매출금 (당좌자산) = wholesale_sales 누계 - 매칭된 입금 transactions
       - 13500 부가세대급금 (당좌자산) = wholesale_purchases.vat 누계
     부채:
       - 25100 외상매입금 (유동부채) = wholesale_purchases 누계 - 매칭된 출금 transactions
       - 25500 부가세예수금 (유동부채) = wholesale_sales.vat 누계
  3. 자산-부채-자본 차이 (plug) 는 자본 측 "전기이월잉여금 (가정)" 항목으로 자동 추가
     → 한아원홀세일 처럼 journal_entries 가 비어 있는 entity 의 항등식 강제 균형
     → UI 에서 plug 표시 + warning ("자본금/기초잔고 미입력")

외상매출금 매칭: receivables_service 와 동일 — payee_aliases (canonical) + std.code='40100'.
외상매입금 매칭: wholesale_purchases.payee_name 과 transactions.counterparty 일치 (단순).
"""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from .balance_sheet import generate_balance_sheet


def _fetch_extra_balances(
    conn: PgConnection,
    entity_id: int,
    as_of_date: date,
    vat_excluded: bool,
    existing_codes: set[str] | None = None,
) -> list[dict]:
    """보통예금 / 외상매출금 / 부가세대급금 / 외상매입금 / 부가세예수금 합성 잔액.

    existing_codes: journal_entries 에 이미 잔액이 있는 standard_account 코드 set.
        이 코드와 겹치면 extras 추가 skip (line_key 중복 방지 + 이중 계상 방지).
    """
    existing = existing_codes or set()
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # ── 보통예금: balance_snapshots 의 'bank' type 최신 잔고 (as_of_date 이전) ──
    # journal_entries 에 보통예금이 이미 있으면 skip (entity 2/3 처럼 분개 풍부)
    cur.execute(
        """
        WITH latest AS (
            SELECT account_name, MAX(date) AS d
            FROM balance_snapshots
            WHERE entity_id = %s AND account_type = 'bank' AND date <= %s
            GROUP BY account_name
        )
        SELECT COALESCE(SUM(bs.balance), 0)
        FROM balance_snapshots bs
        JOIN latest l ON bs.account_name = l.account_name AND bs.date = l.d
        WHERE bs.entity_id = %s AND bs.account_type = 'bank'
        """,
        [entity_id, as_of_date, entity_id],
    )
    bank_balance = Decimal(str(cur.fetchone()[0])) if "10300" not in existing else Decimal("0")

    # ── 외상매출금: receivables_service 로직 차용 ──
    cur.execute(
        """
        WITH alias_map AS (
            SELECT alias, canonical_name FROM payee_aliases WHERE entity_id = %s
            UNION ALL
            SELECT DISTINCT payee_name, payee_name FROM wholesale_sales WHERE entity_id = %s
        ),
        billed AS (
            SELECT COALESCE(SUM(total_amount), 0) AS amt
            FROM wholesale_sales
            WHERE entity_id = %s AND sales_date <= %s
        ),
        received AS (
            SELECT COALESCE(SUM(t.amount), 0) AS amt
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            JOIN alias_map am ON am.alias = t.counterparty
            WHERE t.entity_id = %s AND t.type = 'in' AND s.code = '40100'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
              AND t.date <= %s
        )
        SELECT (SELECT amt FROM billed), (SELECT amt FROM received)
        """,
        [entity_id, entity_id, entity_id, as_of_date, entity_id, as_of_date],
    )
    row = cur.fetchone()
    receivables_total = max(Decimal(str(row[0])) - Decimal(str(row[1])), Decimal("0"))

    # ── VAT 예수금/대급금 누계 ──
    cur.execute(
        """
        SELECT COALESCE(SUM(vat), 0)
        FROM wholesale_sales
        WHERE entity_id = %s AND sales_date <= %s
        """,
        [entity_id, as_of_date],
    )
    vat_collected = Decimal(str(cur.fetchone()[0]))

    cur.execute(
        """
        SELECT COALESCE(SUM(vat), 0)
        FROM wholesale_purchases
        WHERE entity_id = %s AND purchase_date <= %s
        """,
        [entity_id, as_of_date],
    )
    vat_paid = Decimal(str(cur.fetchone()[0]))

    # ── 외상매입금: counterparty 단순 매칭 ──
    cur.execute(
        """
        WITH purchased AS (
            SELECT COALESCE(SUM(total_amount), 0) AS amt
            FROM wholesale_purchases
            WHERE entity_id = %s AND purchase_date <= %s
        ),
        paid AS (
            SELECT COALESCE(SUM(t.amount), 0) AS amt
            FROM transactions t
            WHERE t.entity_id = %s AND t.type = 'out'
              AND t.counterparty IN (
                  SELECT DISTINCT payee_name FROM wholesale_purchases WHERE entity_id = %s
              )
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
              AND t.date <= %s
        )
        SELECT (SELECT amt FROM purchased), (SELECT amt FROM paid)
        """,
        [entity_id, as_of_date, entity_id, entity_id, as_of_date],
    )
    row = cur.fetchone()
    payables_total = max(Decimal(str(row[0])) - Decimal(str(row[1])), Decimal("0"))

    cur.close()

    # 합성 balance entries — get_all_account_balances 결과 형식과 동일
    extras: list[dict] = []

    def _add(code: str, name: str, cat: str, subcat: str, side: str, amount: Decimal):
        if code in existing or amount <= 0:
            return
        if side == "debit":
            extras.append({
                "account_id": None, "code": code, "name": name,
                "category": cat, "subcategory": subcat, "normal_side": "debit",
                "debit_total": float(amount), "credit_total": 0.0, "balance": float(amount),
            })
        else:
            extras.append({
                "account_id": None, "code": code, "name": name,
                "category": cat, "subcategory": subcat, "normal_side": "credit",
                "debit_total": 0.0, "credit_total": float(amount), "balance": float(amount),
            })

    _add("10300", "보통예금", "자산", "당좌자산", "debit", bank_balance)
    _add("10800", "외상매출금", "자산", "당좌자산", "debit", receivables_total)
    _add("13500", "부가세대급금", "자산", "당좌자산", "debit", vat_paid)
    _add("25100", "외상매입금", "부채", "유동부채", "credit", payables_total)
    _add("25500", "부가세예수금", "부채", "유동부채", "credit", vat_collected)

    return extras


def _compute_plug_capital(
    base_balances: list[dict],
    extras: list[dict],
    net_income: Decimal,
) -> Decimal:
    """자산 - (부채 + 자본 + net_income) = 자본금 plug (가정).

    plug 양수: 자본금 가정 추가. 음수: 이월결손금 가정 추가.
    """
    all_balances = list(base_balances) + list(extras)

    assets = Decimal("0")
    liabilities = Decimal("0")
    equity = Decimal("0")
    for b in all_balances:
        cat = b["category"]
        bal = Decimal(str(b["balance"]))
        if cat == "자산":
            assets += bal
        elif cat == "부채":
            liabilities += bal
        elif cat == "자본":
            equity += bal

    # plug = 자산 - 부채 - (자본 + net_income)
    plug = assets - liabilities - equity - net_income
    return plug


def generate_balance_sheet_accrual(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    fiscal_year: int,
    as_of_date: date,
    start_date: date,
    net_income_override: Decimal,
    vat_excluded: bool = True,
) -> dict:
    """발생주의 재무상태표 생성.

    기존 generate_balance_sheet 를 net_income_override + extra_balances 와 함께 호출.
    journal_entries 가 비어 있는 entity (한아원홀세일 등) 는 자본금 plug 자동 추가로 항등식 균형.

    Returns:
        balance_sheet 결과 + {"plug_capital": float} — plug 양 표시용
    """
    net_income_dec = Decimal(str(net_income_override))
    base_balances = get_all_account_balances(conn, entity_id, to_date=as_of_date)
    existing_codes = {b["code"] for b in base_balances}
    extras = _fetch_extra_balances(conn, entity_id, as_of_date, vat_excluded, existing_codes)

    # plug 계산 → extras 에 추가 (항등식 강제 균형)
    # plug > 0: 자산 > 부채+자본 → 자본금 가정 추가
    # plug < 0: 자산 < 부채+자본 → 결손금 추가 (자본 줄임)
    plug = _compute_plug_capital(base_balances, extras, net_income_dec)
    if plug > 0:
        extras.append({
            "account_id": None, "code": "30100", "name": "자본금 (가정 — 기초자본 미입력)",
            "category": "자본", "subcategory": "자본금",
            "normal_side": "credit",
            "debit_total": 0.0,
            "credit_total": float(plug),
            "balance": float(plug),
        })
    elif plug < 0:
        # 자본 측에 (-) plug 추가 — "자본조정" subcategory 로 별도 분류.
        # 이렇게 해야 balance_sheet.py 의 net_income 가산 (이익잉여금 우선) 과 분리됨.
        # 미처리결손금 (37800, 이익잉여금) 은 net_income 가산용으로 자동 synthesize 됨.
        extras.append({
            "account_id": None, "code": "38500", "name": "기초자본 미입력 plug (가정)",
            "category": "자본", "subcategory": "자본조정",
            "normal_side": "debit",
            "debit_total": float(-plug),
            "credit_total": 0.0,
            "balance": float(plug),
        })

    result = generate_balance_sheet(
        conn=conn, cur=cur, stmt_id=stmt_id,
        entity_id=entity_id, fiscal_year=fiscal_year,
        as_of_date=as_of_date, start_date=start_date,
        net_income_override=net_income_dec,
        extra_balances=extras,
    )
    result["plug_capital"] = float(plug)
    return result

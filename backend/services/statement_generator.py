"""재무제표 생성 엔진 — 5종 재무제표를 journal_entry_lines 기반으로 생성

모든 함수는 conn.commit()을 하지 않음. 호출자가 트랜잭션 제어.
"""

from datetime import date, timedelta
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances


class StatementImbalanceError(Exception):
    """재무상태표 항등식 불균형."""
    pass


class CashFlowLoopError(Exception):
    """현금흐름 루프 검증 실패."""
    pass


# --- 내부 헬퍼 ---

def _get_or_create_statement(
    cur,
    entity_id: int,
    fiscal_year: int,
    start_month: int,
    end_month: int,
) -> int:
    """financial_statements 헤더 조회 또는 생성. 반환: statement_id."""
    cur.execute(
        """
        SELECT id FROM financial_statements
        WHERE entity_id = %s AND fiscal_year = %s
          AND start_month = %s AND end_month = %s
          AND is_consolidated = FALSE
        """,
        [entity_id, fiscal_year, start_month, end_month],
    )
    row = cur.fetchone()
    if row:
        stmt_id = row[0]
        # 기존 라인 삭제 (재생성)
        cur.execute(
            "DELETE FROM financial_statement_line_items WHERE statement_id = %s",
            [stmt_id],
        )
        cur.execute(
            "UPDATE financial_statements SET status = 'draft', updated_at = NOW() WHERE id = %s",
            [stmt_id],
        )
        return stmt_id

    cur.execute(
        """
        INSERT INTO financial_statements
            (entity_id, fiscal_year, start_month, end_month, status)
        VALUES (%s, %s, %s, %s, 'draft')
        RETURNING id
        """,
        [entity_id, fiscal_year, start_month, end_month],
    )
    return cur.fetchone()[0]


def _insert_line_item(cur, stmt_id: int, item: dict):
    """financial_statement_line_items에 한 행 삽입."""
    cur.execute(
        """
        INSERT INTO financial_statement_line_items
            (statement_id, statement_type, account_code, line_key, label,
             sort_order, is_section_header, auto_amount, auto_debit, auto_credit)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            stmt_id,
            item["statement_type"],
            item.get("account_code"),
            item["line_key"],
            item["label"],
            item["sort_order"],
            item.get("is_section_header", False),
            item.get("auto_amount", 0),
            item.get("auto_debit", 0),
            item.get("auto_credit", 0),
        ],
    )


def _section_header(stmt_type: str, key: str, label: str, order: int) -> dict:
    return {
        "statement_type": stmt_type,
        "line_key": key,
        "label": label,
        "sort_order": order,
        "is_section_header": True,
        "auto_amount": 0,
        "auto_debit": 0,
        "auto_credit": 0,
    }


# --- 재무상태표 ---

def generate_balance_sheet(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    fiscal_year: int,
    as_of_date: date,
    start_date: date,
) -> dict:
    """재무상태표 생성. 자산 = 부채 + 자본 검증.

    Returns: {"total_assets", "total_liabilities", "total_equity", "is_balanced"}
    """
    # 기간 시작~종료까지 모든 분개 기반 잔액
    balances = get_all_account_balances(conn, entity_id, to_date=as_of_date)

    # 당기순이익 계산 (수익 - 비용, 해당 기간)
    period_balances = get_all_account_balances(conn, entity_id, from_date=start_date, to_date=as_of_date)
    net_income = Decimal("0")
    for b in period_balances:
        if b["category"] == "수익":
            net_income += Decimal(str(b["balance"]))
        elif b["category"] == "비용":
            net_income -= Decimal(str(b["balance"]))

    st = "balance_sheet"
    items = []
    order = 100

    # 자산
    items.append(_section_header(st, "assets_header", "자산", order))
    order += 10

    # 유동자산
    items.append(_section_header(st, "current_assets_header", "  유동자산", order))
    order += 10
    total_current_assets = Decimal("0")
    for b in balances:
        if b["category"] == "자산" and b["subcategory"] == "유동자산":
            items.append({
                "statement_type": st,
                "account_code": b["code"],
                "line_key": f"ca_{b['code']}",
                "label": f"    {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]),
                "auto_credit": float(b["credit_total"]),
            })
            total_current_assets += Decimal(str(b["balance"]))
            order += 10

    items.append({
        "statement_type": st, "line_key": "current_assets_total",
        "label": "  유동자산 합계", "sort_order": order,
        "auto_amount": float(total_current_assets), "auto_debit": 0, "auto_credit": 0,
    })
    order += 10

    # 비유동자산
    items.append(_section_header(st, "noncurrent_assets_header", "  비유동자산", order))
    order += 10
    total_noncurrent_assets = Decimal("0")
    for b in balances:
        if b["category"] == "자산" and b["subcategory"] == "비유동자산":
            items.append({
                "statement_type": st,
                "account_code": b["code"],
                "line_key": f"nca_{b['code']}",
                "label": f"    {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]),
                "auto_credit": float(b["credit_total"]),
            })
            total_noncurrent_assets += Decimal(str(b["balance"]))
            order += 10

    items.append({
        "statement_type": st, "line_key": "noncurrent_assets_total",
        "label": "  비유동자산 합계", "sort_order": order,
        "auto_amount": float(total_noncurrent_assets), "auto_debit": 0, "auto_credit": 0,
    })
    order += 10

    total_assets = total_current_assets + total_noncurrent_assets
    items.append({
        "statement_type": st, "line_key": "total_assets",
        "label": "자산 총계", "sort_order": order,
        "auto_amount": float(total_assets), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # 부채
    items.append(_section_header(st, "liabilities_header", "부채", order))
    order += 10
    total_current_liab = Decimal("0")
    total_noncurrent_liab = Decimal("0")

    items.append(_section_header(st, "current_liab_header", "  유동부채", order))
    order += 10
    for b in balances:
        if b["category"] == "부채" and b["subcategory"] == "유동부채":
            items.append({
                "statement_type": st,
                "account_code": b["code"],
                "line_key": f"cl_{b['code']}",
                "label": f"    {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]),
                "auto_credit": float(b["credit_total"]),
            })
            total_current_liab += Decimal(str(b["balance"]))
            order += 10

    items.append({
        "statement_type": st, "line_key": "current_liab_total",
        "label": "  유동부채 합계", "sort_order": order,
        "auto_amount": float(total_current_liab), "auto_debit": 0, "auto_credit": 0,
    })
    order += 10

    items.append(_section_header(st, "noncurrent_liab_header", "  비유동부채", order))
    order += 10
    for b in balances:
        if b["category"] == "부채" and b["subcategory"] == "비유동부채":
            items.append({
                "statement_type": st,
                "account_code": b["code"],
                "line_key": f"ncl_{b['code']}",
                "label": f"    {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]),
                "auto_credit": float(b["credit_total"]),
            })
            total_noncurrent_liab += Decimal(str(b["balance"]))
            order += 10

    total_liabilities = total_current_liab + total_noncurrent_liab
    items.append({
        "statement_type": st, "line_key": "total_liabilities",
        "label": "부채 총계", "sort_order": order,
        "auto_amount": float(total_liabilities), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # 자본
    items.append(_section_header(st, "equity_header", "자본", order))
    order += 10
    total_equity = Decimal("0")
    for b in balances:
        if b["category"] == "자본":
            bal = Decimal(str(b["balance"]))
            # 이익잉여금(30300)에 당기순이익 자동 반영
            if b["code"] == "30300":
                bal += net_income
            items.append({
                "statement_type": st,
                "account_code": b["code"],
                "line_key": f"eq_{b['code']}",
                "label": f"    {b['name']}" + (" (당기순이익 포함)" if b["code"] == "30300" else ""),
                "sort_order": order,
                "auto_amount": float(bal),
                "auto_debit": float(b["debit_total"]),
                "auto_credit": float(b["credit_total"]),
            })
            total_equity += bal
            order += 10

    # 자본 계정이 없는 경우에도 당기순이익 표시
    if not any(b["category"] == "자본" for b in balances):
        total_equity = net_income
        if net_income != 0:
            items.append({
                "statement_type": st,
                "account_code": "30300",
                "line_key": "eq_30300",
                "label": "    이익잉여금 (당기순이익)",
                "sort_order": order,
                "auto_amount": float(net_income),
                "auto_debit": 0, "auto_credit": 0,
            })
            order += 10

    items.append({
        "statement_type": st, "line_key": "total_equity",
        "label": "자본 총계", "sort_order": order,
        "auto_amount": float(total_equity), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 10

    liab_plus_equity = total_liabilities + total_equity
    items.append({
        "statement_type": st, "line_key": "total_liabilities_equity",
        "label": "부채 및 자본 총계", "sort_order": order,
        "auto_amount": float(liab_plus_equity), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    is_balanced = total_assets == liab_plus_equity
    return {
        "total_assets": float(total_assets),
        "total_liabilities": float(total_liabilities),
        "total_equity": float(total_equity),
        "net_income": float(net_income),
        "is_balanced": is_balanced,
        "difference": float(total_assets - liab_plus_equity),
    }


# --- 손익계산서 ---

def generate_income_statement(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    start_date: date,
    end_date: date,
) -> dict:
    """손익계산서 생성."""
    balances = get_all_account_balances(conn, entity_id, from_date=start_date, to_date=end_date)

    st = "income_statement"
    items = []
    order = 100

    # 매출
    items.append(_section_header(st, "revenue_header", "매출", order))
    order += 10
    total_revenue = Decimal("0")
    for b in balances:
        if b["category"] == "수익" and b.get("subcategory") == "영업수익":
            items.append({
                "statement_type": st, "account_code": b["code"],
                "line_key": f"rev_{b['code']}", "label": f"  {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]), "auto_credit": float(b["credit_total"]),
            })
            total_revenue += Decimal(str(b["balance"]))
            order += 10

    items.append({
        "statement_type": st, "line_key": "total_revenue",
        "label": "매출 합계", "sort_order": order,
        "auto_amount": float(total_revenue), "auto_debit": 0, "auto_credit": 0,
    })
    order += 10

    # 매출원가
    total_cogs = Decimal("0")
    for b in balances:
        if b["category"] == "비용" and b.get("subcategory") == "매출원가":
            items.append({
                "statement_type": st, "account_code": b["code"],
                "line_key": f"cogs_{b['code']}", "label": f"  {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]), "auto_credit": float(b["credit_total"]),
            })
            total_cogs += Decimal(str(b["balance"]))
            order += 10

    gross_profit = total_revenue - total_cogs
    items.append({
        "statement_type": st, "line_key": "gross_profit",
        "label": "매출총이익", "sort_order": order,
        "auto_amount": float(gross_profit), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # 판매비와관리비
    items.append(_section_header(st, "sga_header", "판매비와관리비", order))
    order += 10
    total_sga = Decimal("0")
    for b in balances:
        if b["category"] == "비용" and b.get("subcategory") == "판매비와관리비":
            items.append({
                "statement_type": st, "account_code": b["code"],
                "line_key": f"sga_{b['code']}", "label": f"  {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]), "auto_credit": float(b["credit_total"]),
            })
            total_sga += Decimal(str(b["balance"]))
            order += 10

    items.append({
        "statement_type": st, "line_key": "total_sga",
        "label": "판매비와관리비 합계", "sort_order": order,
        "auto_amount": float(total_sga), "auto_debit": 0, "auto_credit": 0,
    })
    order += 10

    operating_income = gross_profit - total_sga
    items.append({
        "statement_type": st, "line_key": "operating_income",
        "label": "영업이익", "sort_order": order,
        "auto_amount": float(operating_income), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # 영업외수익
    total_other_income = Decimal("0")
    for b in balances:
        if b["category"] == "수익" and b.get("subcategory") == "영업외수익":
            items.append({
                "statement_type": st, "account_code": b["code"],
                "line_key": f"oi_{b['code']}", "label": f"  {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]), "auto_credit": float(b["credit_total"]),
            })
            total_other_income += Decimal(str(b["balance"]))
            order += 10

    # 영업외비용
    total_other_expense = Decimal("0")
    for b in balances:
        if b["category"] == "비용" and b.get("subcategory") == "영업외비용":
            items.append({
                "statement_type": st, "account_code": b["code"],
                "line_key": f"oe_{b['code']}", "label": f"  {b['name']}",
                "sort_order": order,
                "auto_amount": float(b["balance"]),
                "auto_debit": float(b["debit_total"]), "auto_credit": float(b["credit_total"]),
            })
            total_other_expense += Decimal(str(b["balance"]))
            order += 10

    income_before_tax = operating_income + total_other_income - total_other_expense
    items.append({
        "statement_type": st, "line_key": "income_before_tax",
        "label": "법인세차감전이익", "sort_order": order,
        "auto_amount": float(income_before_tax), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 10

    # 법인세비용
    total_tax = Decimal("0")
    for b in balances:
        if b["category"] == "비용" and b.get("subcategory") == "법인세":
            total_tax += Decimal(str(b["balance"]))

    if total_tax != 0:
        items.append({
            "statement_type": st, "line_key": "tax_expense",
            "label": "  법인세비용", "sort_order": order,
            "auto_amount": float(total_tax), "auto_debit": 0, "auto_credit": 0,
        })
        order += 10

    net_income = income_before_tax - total_tax
    items.append({
        "statement_type": st, "line_key": "net_income",
        "label": "당기순이익", "sort_order": order,
        "auto_amount": float(net_income), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    return {
        "total_revenue": float(total_revenue),
        "total_cogs": float(total_cogs),
        "gross_profit": float(gross_profit),
        "operating_income": float(operating_income),
        "net_income": float(net_income),
    }


# --- 현금흐름표 (직접법) ---

def generate_cash_flow_statement(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    start_date: date,
    end_date: date,
) -> dict:
    """현금흐름표 (직접법). 기말잔고 = 기초잔고 + 수입 - 지출."""
    inner_cur = conn.cursor()

    # 기초 현금잔고 (start_date 이전까지의 현금 잔액)
    inner_cur.execute(
        """
        SELECT COALESCE(SUM(jel.debit_amount) - SUM(jel.credit_amount), 0)
        FROM journal_entry_lines jel
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE je.entity_id = %s AND je.status = 'posted'
          AND je.entry_date < %s
          AND jel.standard_account_id = (
              SELECT id FROM standard_accounts WHERE code = '10100'
          )
        """,
        [entity_id, start_date],
    )
    opening_cash = Decimal(str(inner_cur.fetchone()[0]))

    # 기간 중 현금 수입 (debit to cash)
    inner_cur.execute(
        """
        SELECT COALESCE(SUM(jel.debit_amount), 0)
        FROM journal_entry_lines jel
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE je.entity_id = %s AND je.status = 'posted'
          AND je.entry_date >= %s AND je.entry_date <= %s
          AND jel.standard_account_id = (
              SELECT id FROM standard_accounts WHERE code = '10100'
          )
        """,
        [entity_id, start_date, end_date],
    )
    cash_inflows = Decimal(str(inner_cur.fetchone()[0]))

    # 기간 중 현금 지출 (credit from cash)
    inner_cur.execute(
        """
        SELECT COALESCE(SUM(jel.credit_amount), 0)
        FROM journal_entry_lines jel
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE je.entity_id = %s AND je.status = 'posted'
          AND je.entry_date >= %s AND je.entry_date <= %s
          AND jel.standard_account_id = (
              SELECT id FROM standard_accounts WHERE code = '10100'
          )
        """,
        [entity_id, start_date, end_date],
    )
    cash_outflows = Decimal(str(inner_cur.fetchone()[0]))
    inner_cur.close()

    net_cash = cash_inflows - cash_outflows
    ending_cash = opening_cash + net_cash

    # 독립 검증: 기말까지의 실제 현금 잔액
    inner_cur2 = conn.cursor()
    inner_cur2.execute(
        """
        SELECT COALESCE(SUM(jel.debit_amount) - SUM(jel.credit_amount), 0)
        FROM journal_entry_lines jel
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE je.entity_id = %s AND je.status = 'posted'
          AND je.entry_date <= %s
          AND jel.standard_account_id = (
              SELECT id FROM standard_accounts WHERE code = '10100'
          )
        """,
        [entity_id, end_date],
    )
    actual_ending = Decimal(str(inner_cur2.fetchone()[0]))
    inner_cur2.close()

    st = "cash_flow"
    items = [
        {
            "statement_type": st, "line_key": "opening_cash",
            "label": "기초 현금잔고", "sort_order": 100,
            "auto_amount": float(opening_cash), "auto_debit": 0, "auto_credit": 0,
        },
        _section_header(st, "cf_operating", "영업활동 현금흐름", 200),
        {
            "statement_type": st, "line_key": "cash_inflows",
            "label": "  현금 수입", "sort_order": 210,
            "auto_amount": float(cash_inflows), "auto_debit": float(cash_inflows), "auto_credit": 0,
        },
        {
            "statement_type": st, "line_key": "cash_outflows",
            "label": "  현금 지출", "sort_order": 220,
            "auto_amount": float(-cash_outflows), "auto_debit": 0, "auto_credit": float(cash_outflows),
        },
        {
            "statement_type": st, "line_key": "net_cash_flow",
            "label": "순현금흐름", "sort_order": 300,
            "auto_amount": float(net_cash), "auto_debit": 0, "auto_credit": 0,
            "is_section_header": True,
        },
        {
            "statement_type": st, "line_key": "ending_cash",
            "label": "기말 현금잔고", "sort_order": 400,
            "auto_amount": float(ending_cash), "auto_debit": 0, "auto_credit": 0,
            "is_section_header": True,
        },
    ]

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    # 독립 검증: 계산된 기말잔고 vs 실제 기말잔고
    loop_valid = ending_cash == actual_ending

    return {
        "opening_cash": float(opening_cash),
        "cash_inflows": float(cash_inflows),
        "cash_outflows": float(cash_outflows),
        "net_cash": float(net_cash),
        "ending_cash": float(ending_cash),
        "loop_valid": loop_valid,
    }


# --- 합계잔액시산표 ---

def generate_trial_balance(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    as_of_date: date,
) -> dict:
    """합계잔액시산표. sum(차변) == sum(대변) 검증."""
    balances = get_all_account_balances(conn, entity_id, to_date=as_of_date)

    st = "trial_balance"
    items = []
    order = 100
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for b in balances:
        items.append({
            "statement_type": st,
            "account_code": b["code"],
            "line_key": f"tb_{b['code']}",
            "label": b["name"],
            "sort_order": order,
            "auto_amount": float(b["balance"]),
            "auto_debit": float(b["debit_total"]),
            "auto_credit": float(b["credit_total"]),
        })
        total_debit += Decimal(str(b["debit_total"]))
        total_credit += Decimal(str(b["credit_total"]))
        order += 10

    items.append({
        "statement_type": st, "line_key": "tb_total",
        "label": "합계", "sort_order": order,
        "auto_amount": 0,
        "auto_debit": float(total_debit),
        "auto_credit": float(total_credit),
        "is_section_header": True,
    })

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    is_balanced = total_debit == total_credit
    return {
        "total_debit": float(total_debit),
        "total_credit": float(total_credit),
        "is_balanced": is_balanced,
        "difference": float(total_debit - total_credit),
        "account_count": len(balances),
    }


# --- 결손금처리계산서 ---

def generate_deficit_treatment(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    fiscal_year: int,
    start_date: date,
    end_date: date,
) -> dict:
    """결손금처리계산서. 이익잉여금이 음수일 때 결손금 처리."""
    balances = get_all_account_balances(conn, entity_id, to_date=end_date)
    period_balances = get_all_account_balances(conn, entity_id, from_date=start_date, to_date=end_date)

    # 전기이월 이익잉여금
    retained_balance = Decimal("0")
    for b in balances:
        if b["code"] == "30300":
            retained_balance = Decimal(str(b["balance"]))
            break

    # 당기순이익
    net_income = Decimal("0")
    for b in period_balances:
        if b["category"] == "수익":
            net_income += Decimal(str(b["balance"]))
        elif b["category"] == "비용":
            net_income -= Decimal(str(b["balance"]))

    ending_retained = retained_balance + net_income

    st = "deficit_treatment"
    items = [
        {
            "statement_type": st, "line_key": "prior_retained",
            "label": "전기이월 이익잉여금(결손금)", "sort_order": 100,
            "auto_amount": float(retained_balance), "auto_debit": 0, "auto_credit": 0,
        },
        {
            "statement_type": st, "line_key": "current_net_income",
            "label": "당기순이익(순손실)", "sort_order": 200,
            "auto_amount": float(net_income), "auto_debit": 0, "auto_credit": 0,
        },
        {
            "statement_type": st, "line_key": "ending_retained",
            "label": "차기이월 이익잉여금(결손금)", "sort_order": 300,
            "auto_amount": float(ending_retained), "auto_debit": 0, "auto_credit": 0,
            "is_section_header": True,
        },
    ]

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    return {
        "prior_retained": float(retained_balance),
        "net_income": float(net_income),
        "ending_retained": float(ending_retained),
        "is_deficit": ending_retained < 0,
    }


# --- 전체 재무제표 생성 ---

def generate_all_statements(
    conn: PgConnection,
    entity_id: int,
    fiscal_year: int,
    start_month: int = 1,
    end_month: int = 12,
) -> dict:
    """5종 재무제표 일괄 생성. financial_statement_line_items에 저장.

    Returns:
        {"statement_id": int, "validation": {...per statement...}}
    """
    start_date = date(fiscal_year, start_month, 1)
    # end_month의 마지막 날
    if end_month == 12:
        end_date = date(fiscal_year, 12, 31)
    else:
        end_date = date(fiscal_year, end_month + 1, 1) - timedelta(days=1)

    cur = conn.cursor()
    stmt_id = _get_or_create_statement(cur, entity_id, fiscal_year, start_month, end_month)

    bs = generate_balance_sheet(conn, cur, stmt_id, entity_id, fiscal_year, end_date, start_date)
    inc = generate_income_statement(conn, cur, stmt_id, entity_id, start_date, end_date)
    cf = generate_cash_flow_statement(conn, cur, stmt_id, entity_id, start_date, end_date)
    tb = generate_trial_balance(conn, cur, stmt_id, entity_id, end_date)
    dt = generate_deficit_treatment(conn, cur, stmt_id, entity_id, fiscal_year, start_date, end_date)

    cur.close()

    return {
        "statement_id": stmt_id,
        "fiscal_year": fiscal_year,
        "start_month": start_month,
        "end_month": end_month,
        "validation": {
            "balance_sheet": bs,
            "income_statement": inc,
            "cash_flow": cf,
            "trial_balance": tb,
            "deficit_treatment": dt,
        },
    }

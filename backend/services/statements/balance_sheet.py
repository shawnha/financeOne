"""재무상태표 생성."""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from .helpers import _insert_line_item, _section_header


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

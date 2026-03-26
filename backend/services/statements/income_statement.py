"""손익계산서 생성."""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from .helpers import _insert_line_item, _section_header


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

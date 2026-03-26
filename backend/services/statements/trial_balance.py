"""합계잔액시산표 생성."""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from .helpers import _insert_line_item


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

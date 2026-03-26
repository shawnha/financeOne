"""결손금처리계산서 생성."""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from .helpers import _insert_line_item


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

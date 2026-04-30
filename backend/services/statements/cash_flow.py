"""현금흐름표 (직접법) 생성."""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from .helpers import _insert_line_item, _section_header


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
              SELECT id FROM standard_accounts WHERE code = '10100' AND gaap_type = 'K_GAAP'
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
              SELECT id FROM standard_accounts WHERE code = '10100' AND gaap_type = 'K_GAAP'
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
              SELECT id FROM standard_accounts WHERE code = '10100' AND gaap_type = 'K_GAAP'
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
              SELECT id FROM standard_accounts WHERE code = '10100' AND gaap_type = 'K_GAAP'
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

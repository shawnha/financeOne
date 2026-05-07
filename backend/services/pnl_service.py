"""P&L (손익계산서) 서비스 — 도매 매출/매입 + OpEx 결합.

매출 (발생주의) = wholesale_sales.total_amount
매출원가 (발생주의) = wholesale_sales.quantity × cogs_unit_price
판관비 (현금주의 약식) = transactions WHERE std_account.subcategory IN ('판매관리비','판매비와관리비')
영업외 = transactions WHERE std_account.subcategory IN ('영업외비용','영업외수익')

도매업 1차 P&L. 발생주의 정합성은 invoices/journal_entries 통합 시 향상.
"""

from decimal import Decimal

from psycopg2.extensions import connection as PgConnection

from backend.utils.db import build_date_range


SGA_SUBS = ("판매관리비", "판매비와관리비")


def get_pnl_summary(conn: PgConnection, entity_id: int, year: int, month: int) -> dict:
    start, end = build_date_range(year, month)
    cur = conn.cursor()

    # 매출 + 매출원가 (도매)
    cur.execute(
        """
        SELECT
          COALESCE(SUM(total_amount), 0) AS revenue,
          COALESCE(SUM(quantity * COALESCE(cogs_unit_price, 0)), 0) AS cogs,
          COUNT(*) AS tx_count
        FROM wholesale_sales
        WHERE entity_id = %s AND sales_date >= %s AND sales_date < %s
        """,
        [entity_id, start, end],
    )
    rev_row = cur.fetchone()
    revenue = Decimal(str(rev_row[0]))
    cogs = Decimal(str(rev_row[1]))
    sales_count = rev_row[2]

    # 매입 (검증용)
    cur.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0), COUNT(*)
        FROM wholesale_purchases
        WHERE entity_id = %s AND purchase_date >= %s AND purchase_date < %s
        """,
        [entity_id, start, end],
    )
    pur_row = cur.fetchone()
    purchases = Decimal(str(pur_row[0]))
    purchases_count = pur_row[1]

    # 판관비 (운영비)
    cur.execute(
        """
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s AND t.date >= %s AND t.date < %s
          AND t.type = 'out'
          AND s.category = '비용' AND s.subcategory = ANY(%s)
          AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
        """,
        [entity_id, start, end, list(SGA_SUBS)],
    )
    opex = Decimal(str(cur.fetchone()[0]))

    # 영업외 비용/수익
    cur.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN s.category = '비용' AND s.subcategory = '영업외비용' THEN t.amount ELSE 0 END), 0) AS non_op_expense,
          COALESCE(SUM(CASE WHEN s.category = '수익' AND s.subcategory = '영업외수익' THEN t.amount ELSE 0 END), 0) AS non_op_income
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
        """,
        [entity_id, start, end],
    )
    nx_row = cur.fetchone()
    non_op_expense = Decimal(str(nx_row[0]))
    non_op_income = Decimal(str(nx_row[1]))

    # 표준계정별 운영비 breakdown
    cur.execute(
        """
        SELECT s.code, s.name, COUNT(*), SUM(t.amount)
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s AND t.date >= %s AND t.date < %s
          AND t.type = 'out'
          AND s.category = '비용' AND s.subcategory = ANY(%s)
          AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
        GROUP BY s.code, s.name
        ORDER BY SUM(t.amount) DESC
        """,
        [entity_id, start, end, list(SGA_SUBS)],
    )
    opex_breakdown = [
        {"code": r[0], "name": r[1], "count": r[2], "amount": float(r[3])}
        for r in cur.fetchall()
    ]

    # 영업외비용 거래 list (drilldown 용)
    cur.execute(
        """
        SELECT t.id, t.date, t.amount, t.description, t.counterparty,
               t.transfer_memo, ia.name AS internal_name,
               s.code, s.name
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        LEFT JOIN internal_accounts ia ON ia.id = t.internal_account_id
        WHERE t.entity_id = %s AND t.date >= %s AND t.date < %s
          AND t.type = 'out'
          AND s.category = '비용' AND s.subcategory = '영업외비용'
          AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
        ORDER BY t.date, t.id
        """,
        [entity_id, start, end],
    )
    non_op_expense_txs = [
        {
            "id": r[0], "date": str(r[1]), "amount": float(r[2]),
            "description": r[3], "counterparty": r[4],
            "transfer_memo": r[5], "internal_name": r[6],
            "std_code": r[7], "std_name": r[8],
        }
        for r in cur.fetchall()
    ]

    cur.close()

    gross_profit = revenue - cogs
    operating_profit = gross_profit - opex
    net_income = operating_profit + non_op_income - non_op_expense

    return {
        "year": year, "month": month, "entity_id": entity_id,
        "revenue": float(revenue),
        "cogs": float(cogs),
        "gross_profit": float(gross_profit),
        "gross_margin_pct": float(gross_profit / revenue * 100) if revenue > 0 else None,
        "opex": float(opex),
        "operating_profit": float(operating_profit),
        "operating_margin_pct": float(operating_profit / revenue * 100) if revenue > 0 else None,
        "non_op_income": float(non_op_income),
        "non_op_expense": float(non_op_expense),
        "net_income": float(net_income),
        "net_margin_pct": float(net_income / revenue * 100) if revenue > 0 else None,
        "purchases_total": float(purchases),
        "sales_count": sales_count,
        "purchases_count": purchases_count,
        "opex_breakdown": opex_breakdown,
        "non_op_expense_transactions": non_op_expense_txs,
    }


_GROUP_COLS = {
    "product": "product_name",
    "payee": "payee_name",
}


def _breakdown_rows(rows, total_count: int, total_amount: Decimal, limit: int) -> dict:
    """top N + 기타 + 합계 형식. rows: [(key, count, amount), ...] DESC."""
    top = rows[:limit]
    rest = rows[limit:]
    others_count = sum(r[1] for r in rest)
    others_amount = sum(Decimal(str(r[2])) for r in rest)
    return {
        "rows": [
            {"key": r[0] or "(이름없음)", "count": r[1], "amount": float(r[2])}
            for r in top
        ],
        "others": {"count": others_count, "amount": float(others_amount)} if rest else None,
        "total": {"count": total_count, "amount": float(total_amount)},
    }


def get_revenue_breakdown(
    conn: PgConnection, entity_id: int, year: int, month: int,
    group_by: str = "product", limit: int = 20,
) -> dict:
    if group_by not in _GROUP_COLS:
        raise ValueError(f"group_by must be one of {list(_GROUP_COLS)}")
    col = _GROUP_COLS[group_by]
    start, end = build_date_range(year, month)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT {col}, COUNT(*), COALESCE(SUM(total_amount), 0)
        FROM wholesale_sales
        WHERE entity_id = %s AND sales_date >= %s AND sales_date < %s
        GROUP BY {col}
        ORDER BY SUM(total_amount) DESC NULLS LAST
        """,
        [entity_id, start, end],
    )
    rows = cur.fetchall()
    cur.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(total_amount), 0)
        FROM wholesale_sales
        WHERE entity_id = %s AND sales_date >= %s AND sales_date < %s
        """,
        [entity_id, start, end],
    )
    tot_count, tot_amount = cur.fetchone()
    cur.close()
    return {"group_by": group_by, **_breakdown_rows(rows, tot_count, Decimal(str(tot_amount)), limit)}


def get_cogs_breakdown(
    conn: PgConnection, entity_id: int, year: int, month: int,
    group_by: str = "product", limit: int = 20,
) -> dict:
    """매출원가 = 매출 row 의 quantity × cogs_unit_price. payee = 매출 거래처 (=고객)."""
    if group_by not in _GROUP_COLS:
        raise ValueError(f"group_by must be one of {list(_GROUP_COLS)}")
    col = _GROUP_COLS[group_by]
    start, end = build_date_range(year, month)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT {col}, COUNT(*), COALESCE(SUM(quantity * COALESCE(cogs_unit_price, 0)), 0)
        FROM wholesale_sales
        WHERE entity_id = %s AND sales_date >= %s AND sales_date < %s
        GROUP BY {col}
        ORDER BY SUM(quantity * COALESCE(cogs_unit_price, 0)) DESC NULLS LAST
        """,
        [entity_id, start, end],
    )
    rows = cur.fetchall()
    cur.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(quantity * COALESCE(cogs_unit_price, 0)), 0)
        FROM wholesale_sales
        WHERE entity_id = %s AND sales_date >= %s AND sales_date < %s
        """,
        [entity_id, start, end],
    )
    tot_count, tot_amount = cur.fetchone()
    cur.close()
    return {"group_by": group_by, **_breakdown_rows(rows, tot_count, Decimal(str(tot_amount)), limit)}


def get_purchases_breakdown(
    conn: PgConnection, entity_id: int, year: int, month: int,
    group_by: str = "payee", limit: int = 20,
) -> dict:
    """매입 (실제 매입처) — wholesale_purchases. payee = 매입처."""
    if group_by not in _GROUP_COLS:
        raise ValueError(f"group_by must be one of {list(_GROUP_COLS)}")
    col = _GROUP_COLS[group_by]
    start, end = build_date_range(year, month)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT {col}, COUNT(*), COALESCE(SUM(total_amount), 0)
        FROM wholesale_purchases
        WHERE entity_id = %s AND purchase_date >= %s AND purchase_date < %s
        GROUP BY {col}
        ORDER BY SUM(total_amount) DESC NULLS LAST
        """,
        [entity_id, start, end],
    )
    rows = cur.fetchall()
    cur.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(total_amount), 0)
        FROM wholesale_purchases
        WHERE entity_id = %s AND purchase_date >= %s AND purchase_date < %s
        """,
        [entity_id, start, end],
    )
    tot_count, tot_amount = cur.fetchone()
    cur.close()
    return {"group_by": group_by, **_breakdown_rows(rows, tot_count, Decimal(str(tot_amount)), limit)}


def get_pnl_monthly(conn: PgConnection, entity_id: int, months: int = 12) -> dict:
    """월별 P&L 시리즈 (차트용)."""
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT to_char(date_trunc('month', sales_date), 'YYYY-MM') AS month
        FROM wholesale_sales WHERE entity_id = %s
        UNION
        SELECT DISTINCT to_char(date_trunc('month', date), 'YYYY-MM') AS month
        FROM transactions WHERE entity_id = %s
          AND is_duplicate = false AND (is_cancel IS NOT TRUE)
        ORDER BY month
        """,
        [entity_id, entity_id],
    )
    available = [r[0] for r in cur.fetchall()]
    if not available:
        cur.close()
        return {"months": [], "available_months": []}

    target = available[-months:]
    result = []
    for m in target:
        y, mn = int(m[:4]), int(m[5:7])
        # 함수 내 cursor 재사용 — get_pnl_summary 가 새 cursor 만들어 안전
        s = get_pnl_summary(conn, entity_id, y, mn)
        result.append({
            "month": m,
            "revenue": s["revenue"],
            "cogs": s["cogs"],
            "gross_profit": s["gross_profit"],
            "gross_margin_pct": s["gross_margin_pct"],
            "opex": s["opex"],
            "operating_profit": s["operating_profit"],
            "net_income": s["net_income"],
            "purchases_total": s["purchases_total"],
            "sales_count": s["sales_count"],
            "purchases_count": s["purchases_count"],
        })
    cur.close()
    return {"months": result, "available_months": available}

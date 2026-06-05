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

# wholesale_sales / wholesale_purchases 를 매출/매입 ground truth 로 쓰는 법인.
# 그 외 법인 (한아원코리아 2, 한아원리테일 3, HOI 1) 은 transactions 의 매출/매출원가
# subcategory 합산을 매출/매출원가로 사용 — wholesale xlsx import 가 없기 때문.
_WHOLESALE_ENTITIES = (13,)

# 매출을 invoices(direction='sales', SalesOne 동기화) 에서 읽는 법인 — 발생주의.
# 코리아(2)·리테일(3). 매출배선 Tier 1 (2026-06-06): transactions 매출=0 버그 수정.
# COGS 는 transactions(현금) 유지 → cogs_basis='cash' (매출=발생/원가=현금 불일치는 라벨로 노출).
# HOI(1) 등 그 외는 기존 transactions 매출 유지(US-GAAP, 범위 밖).
_INVOICE_REVENUE_ENTITIES = (2, 3)


def _revenue_cogs_summary(cur, entity_id: int, start, end) -> dict:
    """entity 별 매출/매출원가 집계.

    entity_id ∈ _WHOLESALE_ENTITIES: wholesale_sales 발생주의.
    entity_id ∈ _INVOICE_REVENUE_ENTITIES: invoices(sales) 발생 매출 + transactions 현금 원가.
    그 외: transactions (subcategory='매출' / '매출원가') 현금주의.

    반환 dict 에 revenue_source('wholesale_sales'|'invoices'|'transactions') 와
    cogs_basis('accrual'|'cash') 포함 — 프론트 disclaimer 용.
    """
    if entity_id in _WHOLESALE_ENTITIES:
        cur.execute(
            """
            SELECT
              COALESCE(SUM(total_amount), 0) AS revenue,
              COALESCE(SUM(COALESCE(supply_amount, total_amount / 1.1)), 0) AS revenue_excl_vat,
              COALESCE(SUM(quantity * COALESCE(cogs_unit_price, 0)), 0) AS cogs,
              COALESCE(SUM(quantity * COALESCE(cogs_unit_price, 0) / 1.1), 0) AS cogs_excl_vat,
              COUNT(*) AS sales_count
            FROM wholesale_sales
            WHERE entity_id = %s AND sales_date >= %s AND sales_date < %s
            """,
            [entity_id, start, end],
        )
        r = cur.fetchone()
        return {
            "revenue": Decimal(str(r[0])), "revenue_excl_vat": Decimal(str(r[1])),
            "cogs": Decimal(str(r[2])), "cogs_excl_vat": Decimal(str(r[3])),
            "sales_count": r[4],
            "revenue_source": "wholesale_sales", "cogs_basis": "accrual",
        }

    # 매출 소스 분기 — 코리아·리테일=invoices(발생), 그 외=transactions(현금)
    if entity_id in _INVOICE_REVENUE_ENTITIES:
        cur.execute(
            """
            SELECT
              COALESCE(SUM(total), 0) AS revenue,
              COALESCE(SUM(amount), 0) AS revenue_excl_vat,
              COUNT(*) AS sales_count
            FROM invoices
            WHERE entity_id = %s AND direction = 'sales'
              AND issue_date >= %s AND issue_date < %s
              AND status <> 'cancelled'
            """,
            [entity_id, start, end],
        )
        rev = cur.fetchone()
        revenue_source = "invoices"
    else:
        cur.execute(
            """
            SELECT
              COALESCE(SUM(t.amount), 0) AS revenue,
              COALESCE(SUM(
                CASE WHEN s.is_vat_taxable THEN t.amount / 1.1 ELSE t.amount END
              ), 0) AS revenue_excl_vat,
              COUNT(*) AS sales_count
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            WHERE t.entity_id = %s
              AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
              AND s.category = '수익' AND s.subcategory = '매출'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
            """,
            [entity_id, start, end],
        )
        rev = cur.fetchone()
        revenue_source = "transactions"

    cur.execute(
        """
        SELECT
          COALESCE(SUM(t.amount), 0) AS cogs,
          COALESCE(SUM(
            CASE WHEN s.is_vat_taxable THEN t.amount / 1.1 ELSE t.amount END
          ), 0) AS cogs_excl_vat
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s
          AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
          AND s.category = '비용' AND s.subcategory = '매출원가'
          AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
        """,
        [entity_id, start, end],
    )
    cogs_row = cur.fetchone()
    return {
        "revenue": Decimal(str(rev[0])), "revenue_excl_vat": Decimal(str(rev[1])),
        "cogs": Decimal(str(cogs_row[0])), "cogs_excl_vat": Decimal(str(cogs_row[1])),
        "sales_count": rev[2],
        "revenue_source": revenue_source, "cogs_basis": "cash",
    }


def get_pnl_summary(conn: PgConnection, entity_id: int, year: int, month: int) -> dict:
    start, end = build_date_range(year, month)
    cur = conn.cursor()

    # 매출 + 매출원가 — entity 별 source 분기 (wholesale vs transactions)
    rc = _revenue_cogs_summary(cur, entity_id, start, end)
    revenue = rc["revenue"]
    revenue_excl_vat = rc["revenue_excl_vat"]
    cogs = rc["cogs"]
    cogs_excl_vat = rc["cogs_excl_vat"]
    sales_count = rc["sales_count"]
    revenue_source = rc["revenue_source"]
    cogs_basis = rc["cogs_basis"]

    # 매입 (검증용)
    cur.execute(
        """
        SELECT
          COALESCE(SUM(total_amount), 0),
          COALESCE(SUM(COALESCE(supply_amount, total_amount / 1.1)), 0),
          COUNT(*)
        FROM wholesale_purchases
        WHERE entity_id = %s AND purchase_date >= %s AND purchase_date < %s
        """,
        [entity_id, start, end],
    )
    pur_row = cur.fetchone()
    purchases = Decimal(str(pur_row[0]))
    purchases_excl_vat = Decimal(str(pur_row[1]))
    purchases_count = pur_row[2]

    # 판관비 (운영비) — VAT 포함 / 제외 모두 계산
    # is_vat_taxable=true 항목만 /1.1 처리 (인건비/공과금/이자 등 면세는 그대로)
    cur.execute(
        """
        SELECT
          COALESCE(SUM(t.amount), 0) AS opex,
          COALESCE(SUM(
            CASE WHEN s.is_vat_taxable THEN t.amount / 1.1 ELSE t.amount END
          ), 0) AS opex_excl_vat
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
          AND t.type = 'out'
          AND s.category = '비용' AND s.subcategory = ANY(%s)
          AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
        """,
        [entity_id, start, end, list(SGA_SUBS)],
    )
    opex_row = cur.fetchone()
    opex = Decimal(str(opex_row[0]))
    opex_excl_vat = Decimal(str(opex_row[1]))

    # 영업외 비용/수익
    cur.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN s.category = '비용' AND s.subcategory = '영업외비용' THEN t.amount ELSE 0 END), 0) AS non_op_expense,
          COALESCE(SUM(CASE WHEN s.category = '수익' AND s.subcategory = '영업외수익' THEN t.amount ELSE 0 END), 0) AS non_op_income
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
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
        WHERE t.entity_id = %s AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
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
        WHERE t.entity_id = %s AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
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

    # VAT 제외 (K-GAAP 손익계산서 정합)
    # opex_excl_vat: 면세 (인건비/공과금) 그대로 + 과세 항목 /1.1
    # non_op 은 거래내역 기준 — 일반적으로 VAT 분리 안 됨. 동일값 유지.
    gross_profit_x = revenue_excl_vat - cogs_excl_vat
    operating_profit_x = gross_profit_x - opex_excl_vat
    net_income_x = operating_profit_x + non_op_income - non_op_expense

    return {
        "year": year, "month": month, "entity_id": entity_id,
        # VAT 포함 (default — 합계금액 base)
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
        # VAT 제외 (K-GAAP 손익 정합 — 공급가액 base)
        "revenue_excl_vat": float(revenue_excl_vat),
        "cogs_excl_vat": float(cogs_excl_vat),
        "opex_excl_vat": float(opex_excl_vat),
        "gross_profit_excl_vat": float(gross_profit_x),
        "gross_margin_pct_excl_vat": float(gross_profit_x / revenue_excl_vat * 100) if revenue_excl_vat > 0 else None,
        "operating_profit_excl_vat": float(operating_profit_x),
        "operating_margin_pct_excl_vat": float(operating_profit_x / revenue_excl_vat * 100) if revenue_excl_vat > 0 else None,
        "net_income_excl_vat": float(net_income_x),
        "net_margin_pct_excl_vat": float(net_income_x / revenue_excl_vat * 100) if revenue_excl_vat > 0 else None,
        "purchases_total_excl_vat": float(purchases_excl_vat),
        # 공통
        "sales_count": sales_count,
        "purchases_count": purchases_count,
        "opex_breakdown": opex_breakdown,
        "non_op_expense_transactions": non_op_expense_txs,
        # 매출 소스 / 원가 기준 (프론트 disclaimer — 매출=발생·원가=현금 불일치 표기)
        "revenue_source": revenue_source,
        "cogs_basis": cogs_basis,
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
    start, end = build_date_range(year, month)
    cur = conn.cursor()

    if entity_id in _WHOLESALE_ENTITIES:
        col = _GROUP_COLS[group_by]
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
    else:
        # transactions 기반 — product 단위 정보 없음. payee=counterparty, product=표준계정명.
        col = "s.name" if group_by == "product" else "t.counterparty"
        cur.execute(
            f"""
            SELECT {col}, COUNT(*), COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            WHERE t.entity_id = %s
              AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
              AND s.category = '수익' AND s.subcategory = '매출'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
            GROUP BY {col}
            ORDER BY SUM(t.amount) DESC NULLS LAST
            """,
            [entity_id, start, end],
        )
        rows = cur.fetchall()
        cur.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            WHERE t.entity_id = %s
              AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
              AND s.category = '수익' AND s.subcategory = '매출'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
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
    """매출원가 = 매출 row 의 quantity × cogs_unit_price. payee = 매출 거래처 (=고객).

    wholesale entity: wholesale_sales 의 cogs_unit_price 기반.
    그 외: transactions (subcategory='매출원가') 기반 — counterparty = 매입처.
    """
    if group_by not in _GROUP_COLS:
        raise ValueError(f"group_by must be one of {list(_GROUP_COLS)}")
    start, end = build_date_range(year, month)
    cur = conn.cursor()

    if entity_id in _WHOLESALE_ENTITIES:
        col = _GROUP_COLS[group_by]
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
    else:
        col = "s.name" if group_by == "product" else "t.counterparty"
        cur.execute(
            f"""
            SELECT {col}, COUNT(*), COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            WHERE t.entity_id = %s
              AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
              AND s.category = '비용' AND s.subcategory = '매출원가'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
            GROUP BY {col}
            ORDER BY SUM(t.amount) DESC NULLS LAST
            """,
            [entity_id, start, end],
        )
        rows = cur.fetchall()
        cur.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            WHERE t.entity_id = %s
              AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
              AND s.category = '비용' AND s.subcategory = '매출원가'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
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
            "revenue_excl_vat": s["revenue_excl_vat"],
            "cogs_excl_vat": s["cogs_excl_vat"],
            "opex_excl_vat": s["opex_excl_vat"],
            "gross_profit_excl_vat": s["gross_profit_excl_vat"],
            "gross_margin_pct_excl_vat": s["gross_margin_pct_excl_vat"],
            "operating_profit_excl_vat": s["operating_profit_excl_vat"],
            "net_income_excl_vat": s["net_income_excl_vat"],
            "purchases_total_excl_vat": s["purchases_total_excl_vat"],
            "sales_count": s["sales_count"],
            "purchases_count": s["purchases_count"],
        })
    cur.close()
    return {"months": result, "available_months": available}


def get_pnl_daily(conn: PgConnection, entity_id: int, year: int, month: int) -> dict:
    """일별 매출/매입 시리즈 — wholesale_sales / wholesale_purchases 발생주의 base.

    cashflow daily chart 와 같은 day axis 로 overlay 가능. 차입금 marker 와 함께
    "차입 → 매입 → 매출" cycle 시각화.
    """
    start, end = build_date_range(year, month)
    cur = conn.cursor()

    if entity_id in _WHOLESALE_ENTITIES:
        cur.execute(
            """
            SELECT EXTRACT(DAY FROM sales_date)::int AS day,
                   COALESCE(SUM(total_amount), 0) AS revenue,
                   COUNT(*) AS sales_count
            FROM wholesale_sales
            WHERE entity_id = %s AND sales_date >= %s AND sales_date < %s
            GROUP BY day
            ORDER BY day
            """,
            [entity_id, start, end],
        )
    else:
        cur.execute(
            """
            SELECT EXTRACT(DAY FROM COALESCE(t.pnl_date, t.date))::int AS day,
                   COALESCE(SUM(t.amount), 0) AS revenue,
                   COUNT(*) AS sales_count
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            WHERE t.entity_id = %s
              AND COALESCE(t.pnl_date, t.date) >= %s AND COALESCE(t.pnl_date, t.date) < %s
              AND s.category = '수익' AND s.subcategory = '매출'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
            GROUP BY day
            ORDER BY day
            """,
            [entity_id, start, end],
        )
    sales_by_day = {r[0]: {"revenue": float(r[1]), "sales_count": r[2]} for r in cur.fetchall()}

    cur.execute(
        """
        SELECT EXTRACT(DAY FROM purchase_date)::int AS day,
               COALESCE(SUM(total_amount), 0) AS purchases,
               COUNT(*) AS purchases_count
        FROM wholesale_purchases
        WHERE entity_id = %s AND purchase_date >= %s AND purchase_date < %s
        GROUP BY day
        ORDER BY day
        """,
        [entity_id, start, end],
    )
    pur_by_day = {r[0]: {"purchases": float(r[1]), "purchases_count": r[2]} for r in cur.fetchall()}
    cur.close()

    # last day of month
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    rows = []
    for d in range(1, last_day + 1):
        s = sales_by_day.get(d, {"revenue": 0.0, "sales_count": 0})
        p = pur_by_day.get(d, {"purchases": 0.0, "purchases_count": 0})
        rows.append({"day": d, **s, **p})
    return {"year": year, "month": month, "rows": rows}

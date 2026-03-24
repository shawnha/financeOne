"""대시보드 API -- KPI cards, cash flow chart, recent transactions"""

from fastapi import APIRouter, Query, Depends
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()

    entity_filter = ""
    params: list = []
    if entity_id is not None:
        entity_filter = "WHERE entity_id = %s"
        params = [entity_id]

    # KPI: 총잔고 (latest balance snapshot)
    cur.execute(
        f"""
        SELECT COALESCE(SUM(balance), 0)
        FROM balance_snapshots
        WHERE (entity_id, date, account_name) IN (
            SELECT entity_id, MAX(date), account_name
            FROM balance_snapshots
            {"WHERE entity_id = %s" if entity_id else ""}
            GROUP BY entity_id, account_name
        )
        """,
        params,
    )
    total_balance = float(cur.fetchone()[0])

    # KPI: 이번달 수입/지출
    cur.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE date >= date_trunc('month', CURRENT_DATE)
          AND date < date_trunc('month', CURRENT_DATE) + interval '1 month'
          {"AND entity_id = %s" if entity_id else ""}
        """,
        params,
    )
    row = cur.fetchone()
    monthly_income = float(row[0])
    monthly_expense = float(row[1])

    # KPI: 전월 수입/지출 (MoM 비교)
    cur.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE date >= date_trunc('month', CURRENT_DATE) - interval '1 month'
          AND date < date_trunc('month', CURRENT_DATE)
          {"AND entity_id = %s" if entity_id else ""}
        """,
        params,
    )
    prev_row = cur.fetchone()
    prev_income = float(prev_row[0])
    prev_expense = float(prev_row[1])

    def pct_change(current: float, previous: float) -> Optional[float]:
        if previous == 0:
            return None
        return round((current - previous) / previous * 100, 1)

    income_change_pct = pct_change(monthly_income, prev_income)
    expense_change_pct = pct_change(monthly_expense, prev_expense)

    # KPI: 현금 런웨이 (months)
    avg_monthly_expense = monthly_expense if monthly_expense > 0 else 1
    runway_months = round(total_balance / avg_monthly_expense, 1) if avg_monthly_expense > 0 else None

    # Cash flow chart: 최근 6개월
    cur.execute(
        f"""
        SELECT
            to_char(date_trunc('month', date), 'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE date >= date_trunc('month', CURRENT_DATE) - interval '5 months'
          {"AND entity_id = %s" if entity_id else ""}
        GROUP BY date_trunc('month', date)
        ORDER BY month
        """,
        params,
    )
    cash_flow = []
    for r in cur.fetchall():
        inc, exp = float(r[1]), float(r[2])
        cash_flow.append({
            "month": r[0],
            "income": inc,
            "expense": exp,
            "net": round(inc - exp, 2),
        })

    # Recent transactions: 최근 10건
    cur.execute(
        f"""
        SELECT t.id, t.date, t.description, t.amount, t.type, t.source_type,
               t.is_confirmed, t.mapping_confidence,
               sa.name AS standard_account_name
        FROM transactions t
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        {"WHERE t.entity_id = %s" if entity_id else ""}
        ORDER BY t.date DESC, t.id DESC
        LIMIT 10
        """,
        params,
    )
    cols = [d[0] for d in cur.description]
    recent = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Summary counts
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE is_confirmed = false) AS unconfirmed,
            COUNT(*) FILTER (WHERE standard_account_id IS NULL) AS unmapped
        FROM transactions
        {entity_filter}
        """,
        params,
    )
    counts = cur.fetchone()
    cur.close()

    return {
        "kpi": {
            "total_balance": total_balance,
            "monthly_income": monthly_income,
            "monthly_expense": monthly_expense,
            "income_change_pct": income_change_pct,
            "expense_change_pct": expense_change_pct,
            "runway_months": runway_months,
        },
        "cash_flow": cash_flow,
        "recent_transactions": recent,
        "counts": {
            "total": counts[0],
            "unconfirmed": counts[1],
            "unmapped": counts[2],
        },
    }


@router.get("/cashflow")
def get_cashflow(
    entity_id: Optional[int] = None,
    months: int = Query(12, ge=1, le=60),
    conn: PgConnection = Depends(get_db),
):
    """Monthly cashflow breakdown with running balance."""
    cur = conn.cursor()

    params: list = []
    entity_clause = ""
    if entity_id is not None:
        entity_clause = "AND entity_id = %s"
        params.append(entity_id)

    # Opening balance: latest balance_snapshot before the first transaction month
    # (or before period start, whichever finds data)
    cur.execute(
        f"""
        SELECT COALESCE(SUM(balance), 0)
        FROM balance_snapshots
        WHERE (entity_id, date, account_name) IN (
            SELECT entity_id, MAX(date), account_name
            FROM balance_snapshots
            WHERE date < (
                SELECT COALESCE(MIN(date_trunc('month', date)), date_trunc('month', CURRENT_DATE))
                FROM transactions
                WHERE date >= date_trunc('month', CURRENT_DATE) - interval '{months - 1} months'
                  {"AND entity_id = %s" if entity_id else ""}
            )
              {"AND entity_id = %s" if entity_id else ""}
            GROUP BY entity_id, account_name
        )
        """,
        ([entity_id, entity_id] if entity_id else []),
    )
    opening_balance = float(cur.fetchone()[0])

    # Monthly income/expense — 은행 거래만 (카드는 은행의 카드대금 출금에 포함)
    cur.execute(
        f"""
        SELECT
            to_char(date_trunc('month', date), 'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE date >= date_trunc('month', CURRENT_DATE) - interval '{months - 1} months'
          AND date < date_trunc('month', CURRENT_DATE) + interval '1 month'
          AND source_type IN ('woori_bank', 'mercury_api', 'manual')
          {entity_clause}
        GROUP BY date_trunc('month', date)
        ORDER BY month
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    # Build month-by-month with running balance
    result = []
    running_balance = opening_balance
    for r in rows:
        month_str = r[0]
        income = float(r[1])
        expense = float(r[2])
        net = round(income - expense, 2)
        month_opening = running_balance
        running_balance = round(running_balance + net, 2)
        result.append({
            "month": month_str,
            "opening_balance": month_opening,
            "income": income,
            "expense": expense,
            "net": net,
            "closing_balance": running_balance,
        })

    return {
        "months": result,
        "period_start_balance": opening_balance,
        "period_end_balance": running_balance if result else opening_balance,
    }


@router.get("/cashflow/detail")
def get_cashflow_detail(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """월별 현금흐름 상세 — 은행 거래 일별 리스트 + 카드대금 세부."""
    cur = conn.cursor()

    # 은행 거래 (일별)
    cur.execute(
        """
        SELECT t.id, t.date, t.type, t.amount, t.description, t.counterparty,
               t.source_type
        FROM transactions t
        WHERE t.entity_id = %s
          AND t.source_type IN ('woori_bank', 'mercury_api', 'manual')
          AND EXTRACT(YEAR FROM t.date) = %s
          AND EXTRACT(MONTH FROM t.date) = %s
        ORDER BY t.date, t.id
        """,
        [entity_id, year, month],
    )
    cols = [d[0] for d in cur.description]
    bank_transactions = [dict(zip(cols, r)) for r in cur.fetchall()]

    # 카드 사용 내역 (해당 월 사용분 — 다음 달 결제)
    cur.execute(
        """
        SELECT t.id, t.date, t.type, t.amount, t.description, t.counterparty,
               t.source_type, t.member_id,
               m.name AS member_name,
               sa.name AS account_name, sa.code AS account_code
        FROM transactions t
        LEFT JOIN members m ON t.member_id = m.id
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE t.entity_id = %s
          AND t.source_type IN ('lotte_card', 'woori_card')
          AND EXTRACT(YEAR FROM t.date) = %s
          AND EXTRACT(MONTH FROM t.date) = %s
        ORDER BY t.source_type, t.member_id, t.date
        """,
        [entity_id, year, month],
    )
    cols2 = [d[0] for d in cur.description]
    card_transactions = [dict(zip(cols2, r)) for r in cur.fetchall()]

    # 카드 사용 요약 (소스별)
    cur.execute(
        """
        SELECT source_type,
               SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END) AS total_out,
               SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END) AS total_refund,
               COUNT(*) AS tx_count
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('lotte_card', 'woori_card')
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
        GROUP BY source_type
        """,
        [entity_id, year, month],
    )
    card_summary = []
    for r in cur.fetchall():
        card_summary.append({
            "source_type": r[0],
            "total_expense": float(r[1]),
            "total_refund": float(r[2]),
            "net": float(r[1]) - float(r[2]),
            "tx_count": r[3],
        })

    # 잔액 스냅샷
    cur.execute(
        """
        SELECT balance FROM balance_snapshots
        WHERE entity_id = %s AND date <= make_date(%s, %s, 28)
        ORDER BY date DESC LIMIT 1
        """,
        [entity_id, year, month],
    )
    row = cur.fetchone()
    closing_balance = float(row[0]) if row else None

    cur.close()

    return {
        "year": year,
        "month": month,
        "bank_transactions": bank_transactions,
        "card_transactions": card_transactions,
        "card_summary": card_summary,
        "closing_balance": closing_balance,
    }

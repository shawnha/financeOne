"""대시보드 API -- KPI cards, cash flow chart, recent transactions

Phase 1A 신규 (2026-04-30): /full batch endpoint (Approach C + Option 2 Bento Selector).
Design doc: ~/.gstack/projects/shawnha-financeOne/admin-main-design-20260430-215309.md
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal, Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.routers.dashboard_schemas import DashboardFullResponse
from backend.services.dashboard_service import fetch_dashboard_full
from backend.utils.db import fetch_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ── Phase 1A: Batch endpoint (plan-eng-review A1) ─────────────

@router.get("/full", response_model=DashboardFullResponse)
def get_dashboard_full(
    entity_id: Optional[int] = Query(None, description="None = Group consolidated"),
    currency: Literal["USD", "KRW"] = Query("USD"),
    gaap: Literal["US", "K"] = Query("K"),
    year_month: Optional[str] = Query(None, description="YYYY-MM (default: current month)"),
    conn: PgConnection = Depends(get_db),
):
    """6 widget data 한 번에 fetch.

    Bento 클릭 시 frontend 가 이 endpoint 1번 호출로 KPI/Queue/AI/Chart 모두 갱신.
    Connection pool 절약 + FCP 개선 (network round trip 6→1).

    year_month: 'YYYY-MM' 으로 KPI/chart 의 reference month 지정 (default = 현재 달).
    """
    try:
        return fetch_dashboard_full(conn, entity_id, currency, gaap, year_month)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Dashboard /full error: %s", e, exc_info=True)
        raise HTTPException(500, detail=f"dashboard /full failed: {e}")


# ── Legacy endpoint (V0 dashboard) ─────────────────────────────

@router.get("")
def get_dashboard(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    try:
        return _get_dashboard_data(conn, entity_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Dashboard KPI error: %s", e)
        raise HTTPException(500, detail=str(e))


def _get_dashboard_data(conn: PgConnection, entity_id: Optional[int]):
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
          AND (is_cancel IS NOT TRUE)
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
          AND (is_cancel IS NOT TRUE)
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
          AND (is_cancel IS NOT TRUE)
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
        WHERE (t.is_cancel IS NOT TRUE)
        {"AND t.entity_id = %s" if entity_id else ""}
        ORDER BY t.date DESC, t.id DESC
        LIMIT 10
        """,
        params,
    )
    recent = fetch_all(cur)

    # Summary counts
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE is_confirmed = false) AS unconfirmed,
            COUNT(*) FILTER (WHERE standard_account_id IS NULL) AS unmapped
        FROM transactions
        WHERE (is_cancel IS NOT TRUE)
        {("AND entity_id = %s" if entity_id else "")}
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



# NOTE: /cashflow, /cashflow/detail 엔드포인트는 /api/cashflow/ 라우터로 이전됨
# (backend/routers/cashflow.py)


@router.get("/expenseone-summary")
def get_expenseone_summary(
    entity_id: int = 2,
    conn: PgConnection = Depends(get_db),
):
    """ExpenseOne 미매칭 거래 요약 — 빠른실행 버튼 카운트 + 제출자 breakdown + drift.

    Returns:
        unmapped_count: 전체 미매칭 수 (대시보드 버튼용)
        by_submitter: 제출자별 top 10 [{name, count}]
        drift_count: 전월 거래를 이번달에 승인한 건 (Asia/Seoul)
    """
    cur = conn.cursor()

    # unmapped_count + by_submitter
    cur.execute(
        """
        SELECT
            COALESCE(expense_submitted_by, '(미상)') AS name,
            COUNT(*) AS cnt
        FROM transactions
        WHERE entity_id = %s
          AND source_type LIKE 'expenseone_%%'
          AND internal_account_id IS NULL
        GROUP BY COALESCE(expense_submitted_by, '(미상)')
        ORDER BY cnt DESC, name ASC
        LIMIT 10
        """,
        [entity_id],
    )
    by_submitter = [{"name": name, "count": cnt} for name, cnt in cur.fetchall()]
    unmapped_count = sum(r["count"] for r in by_submitter)

    # drift: 거래일 월 != 생성일 월 (Asia/Seoul)
    cur.execute(
        """
        SELECT COUNT(*)
        FROM transactions
        WHERE entity_id = %s
          AND source_type LIKE 'expenseone_%%'
          AND DATE_TRUNC('month', date)
            != DATE_TRUNC('month', (created_at AT TIME ZONE 'Asia/Seoul')::date)
        """,
        [entity_id],
    )
    drift_count = cur.fetchone()[0] or 0
    cur.close()

    return {
        "unmapped_count": unmapped_count,
        "by_submitter": by_submitter,
        "drift_count": drift_count,
    }

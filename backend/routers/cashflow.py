"""현금흐름 API — 실제 현금흐름, 월별 요약, 카드비용, 예상 현금흐름 조회.

읽기 전용 API. 데이터 입력은 기존 /api/upload + /api/forecasts 담당.
"""

import logging
from fastapi import APIRouter, Query, Depends, HTTPException
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

logger = logging.getLogger(__name__)
from backend.services.cashflow_service import (
    build_daily_rows,
    group_card_expenses,
    get_opening_balance,
    get_bank_transactions,
    get_card_transactions,
    get_monthly_summary_data,
    get_forecast_cashflow,
    generate_daily_schedule,
)

router = APIRouter(prefix="/api/cashflow", tags=["cashflow"])


@router.get("/actual")
def get_actual_cashflow(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """특정 월 은행 거래 일별 리스트 + running balance."""
    try:
        opening = get_opening_balance(conn, entity_id, year, month)
        bank_txs = get_bank_transactions(conn, entity_id, year, month)
        rows = build_daily_rows(bank_txs, opening)

        # Serialize Decimal → float for JSON
        serialized = []
        for row in rows:
            serialized.append({
                "type": row["type"],
                "date": str(row["date"]) if row["date"] else None,
                "description": row.get("description", ""),
                "counterparty": row.get("counterparty"),
                "amount": float(row["amount"]),
                "balance": float(row["balance"]),
                "tx_id": row.get("tx_id"),
                "source_type": row.get("source_type"),
                "internal_account_id": row.get("internal_account_id"),
                "internal_account_name": row.get("internal_account_name"),
            })

        return {
            "year": year,
            "month": month,
            "entity_id": entity_id,
            "opening_balance": float(opening),
            "closing_balance": float(rows[-1]["balance"]) if rows else float(opening),
            "rows": serialized,
        }
    except Exception as e:
        logger.error("Cashflow actual error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/summary")
def get_cashflow_summary(
    entity_id: int = Query(...),
    months: int = Query(12, ge=1, le=60),
    conn: PgConnection = Depends(get_db),
):
    """월별 요약 (차트용) — N개월 income/expense/net + running balance."""
    try:
        return get_monthly_summary_data(conn, entity_id, months)
    except Exception as e:
        logger.error("Cashflow summary error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/card-expense")
def get_card_expense(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """카드 사용 상세 — 소스별/회원별 그룹핑 + 내부계정 breakdown."""
    try:
        card_txs = get_card_transactions(conn, entity_id, year, month)
        groups = group_card_expenses(card_txs)

        # Prev month card total (for comparison)
        prev_year = year if month > 1 else year - 1
        prev_month = month - 1 if month > 1 else 12
        prev_card_txs = get_card_transactions(conn, entity_id, prev_year, prev_month)
        prev_groups = group_card_expenses(prev_card_txs)

        prev_total_net = sum(float(g["net"]) for g in prev_groups)
        curr_total_net = sum(float(g["net"]) for g in groups)
        change_pct = (
            round((curr_total_net - prev_total_net) / prev_total_net * 100, 1)
            if prev_total_net != 0 else None
        )

        # Serialize
        def serialize_group(g):
            return {
                "source_type": g["source_type"],
                "total_expense": float(g["total_expense"]),
                "total_refund": float(g["total_refund"]),
                "net": float(g["net"]),
                "tx_count": g["tx_count"],
                "members": [
                    {
                        "member_id": m["member_id"],
                        "member_name": m["member_name"],
                        "subtotal": float(m["subtotal"]),
                        "refund": float(m["refund"]),
                        "net": float(m["net"]),
                        "tx_count": m["tx_count"],
                        "transactions": [
                            {
                                "id": t["id"],
                                "date": str(t["date"]),
                                "type": t["type"],
                                "amount": float(t["amount"]),
                                "description": t.get("description", ""),
                                "counterparty": t.get("counterparty"),
                                "account_name": t.get("account_name"),
                                "account_code": t.get("account_code"),
                            }
                            for t in m["transactions"]
                        ],
                    }
                    for m in g["members"]
                ],
                "account_breakdown": [
                    {
                        "account_name": a["account_name"],
                        "amount": float(a["amount"]),
                        "tx_count": a["tx_count"],
                    }
                    for a in g["account_breakdown"]
                ],
            }

        return {
            "year": year,
            "month": month,
            "entity_id": entity_id,
            "groups": [serialize_group(g) for g in groups],
            "total_expense": sum(float(g["total_expense"]) for g in groups),
            "total_refund": sum(float(g["total_refund"]) for g in groups),
            "total_net": curr_total_net,
            "prev_month_net": prev_total_net,
            "change_pct": change_pct,
        }
    except Exception as e:
        logger.error("Cashflow card-expense error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/forecast")
def get_forecast(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """예상 현금흐름 — forecasts + 시차 보정 + 실제 진행 비교."""
    try:
        return get_forecast_cashflow(conn, entity_id, year, month)
    except Exception as e:
        logger.error("Cashflow forecast error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/daily-schedule")
def get_daily_schedule(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """일별 잔고 시뮬레이션 — expected_day + card_settings 기반 (TENSION-2)."""
    try:
        return generate_daily_schedule(conn, entity_id, year, month)
    except Exception as e:
        logger.error("Cashflow daily-schedule error: %s", e)
        raise HTTPException(500, detail=str(e))

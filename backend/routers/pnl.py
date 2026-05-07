"""P&L (손익계산서) API."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.pnl_service import (
    get_cogs_breakdown,
    get_pnl_monthly,
    get_pnl_summary,
    get_purchases_breakdown,
    get_revenue_breakdown,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("/summary")
def pnl_summary(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """해당 월 P&L (매출/매출원가/총이익/판관비/영업이익/영업외/순이익)."""
    try:
        return get_pnl_summary(conn, entity_id, year, month)
    except Exception as e:
        logger.error("P&L summary error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/monthly")
def pnl_monthly(
    entity_id: int = Query(...),
    months: int = Query(12, ge=1, le=60),
    conn: PgConnection = Depends(get_db),
):
    """월별 P&L 시리즈."""
    try:
        return get_pnl_monthly(conn, entity_id, months)
    except Exception as e:
        logger.error("P&L monthly error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/revenue-breakdown")
def revenue_breakdown(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    group_by: str = Query("product", pattern="^(product|payee)$"),
    limit: int = Query(20, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    """매출 drilldown — 제품별/거래처별 top N + 기타 + 합계."""
    try:
        return get_revenue_breakdown(conn, entity_id, year, month, group_by, limit)
    except Exception as e:
        logger.error("revenue-breakdown error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/cogs-breakdown")
def cogs_breakdown(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    group_by: str = Query("product", pattern="^(product|payee)$"),
    limit: int = Query(20, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    """매출원가 drilldown — 제품별/거래처별 (매출 row × 매입가)."""
    try:
        return get_cogs_breakdown(conn, entity_id, year, month, group_by, limit)
    except Exception as e:
        logger.error("cogs-breakdown error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/purchases-breakdown")
def purchases_breakdown(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    group_by: str = Query("payee", pattern="^(product|payee)$"),
    limit: int = Query(20, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    """매입 drilldown — 매입처별/제품별."""
    try:
        return get_purchases_breakdown(conn, entity_id, year, month, group_by, limit)
    except Exception as e:
        logger.error("purchases-breakdown error: %s", e)
        raise HTTPException(500, detail=str(e))

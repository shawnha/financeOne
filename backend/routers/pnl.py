"""P&L (손익계산서) API."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.pnl_service import get_pnl_monthly, get_pnl_summary

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

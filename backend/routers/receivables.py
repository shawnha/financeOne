"""외상매출금 API."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.receivables_service import (
    get_receivables_monthly,
    get_receivables_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/receivables", tags=["receivables"])


@router.get("/summary")
def receivables_summary(
    entity_id: int = Query(...),
    year: int | None = Query(None),
    month: int | None = Query(None),
    conn: PgConnection = Depends(get_db),
):
    """거래처별 외상매출금 + 회수율.

    year+month 지정 시 그 월말까지 누계. 없으면 전체 기간.
    """
    try:
        return get_receivables_summary(conn, entity_id, year, month)
    except Exception as e:
        logger.exception("receivables_summary failed")
        raise HTTPException(500, detail=str(e))


@router.get("/monthly")
def receivables_monthly(
    entity_id: int = Query(...),
    months: int = Query(12, ge=1, le=60),
    conn: PgConnection = Depends(get_db),
):
    """월별 발생/회수/회수율 추이."""
    try:
        return get_receivables_monthly(conn, entity_id, months)
    except Exception as e:
        logger.exception("receivables_monthly failed")
        raise HTTPException(500, detail=str(e))

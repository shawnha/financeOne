"""OpEx (실질 운영비) API — 월별 시리즈 + 해당 월 상세."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.opex_service import get_opex_detail, get_opex_summary_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/opex", tags=["opex"])


@router.get("/summary")
def get_opex_summary(
    entity_id: int = Query(...),
    months: int = Query(12, ge=1, le=60),
    conn: PgConnection = Depends(get_db),
):
    """월별 운영비 시리즈 (차트용)."""
    try:
        return get_opex_summary_data(conn, entity_id, months)
    except Exception as e:
        logger.error("OpEx summary error: %s", e)
        raise HTTPException(500, detail=str(e))


@router.get("/detail")
def get_opex_detail_endpoint(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """해당 월 운영비 상세 — KPI + 카테고리 breakdown + 거래 list."""
    try:
        return get_opex_detail(conn, entity_id, year, month)
    except Exception as e:
        logger.error("OpEx detail error: %s", e)
        raise HTTPException(500, detail=str(e))

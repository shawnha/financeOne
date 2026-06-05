# 경영 코쿼핏(사장님 뷰) API 라우터 — 그룹/법인별 현금 집계 + 통화환산 + 순현금 추세
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.routers.cockpit_schemas import CockpitCeoResponse
from backend.services.cockpit_service import fetch_cockpit_ceo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cockpit", tags=["cockpit"])


@router.get("/ceo", response_model=CockpitCeoResponse)
def get_cockpit_ceo(
    currency: Literal["USD", "KRW"] = Query("USD", description="상단 카드/그룹 환산 통화"),
    year_month: Optional[str] = Query(None, description="YYYY-MM (default: 현재 달)"),
    conn: PgConnection = Depends(get_db),
):
    """사장님 코쿼핏 (현금 기준).

    4법인 월 수입/지출/순현금/잔고를 자국통화로, 그룹 합계는 display 통화로 환산해 반환.
    환율 데이터가 없으면 팬텀 1:1 합산 대신 500 (cockpit_service 가 raise).
    """
    try:
        return fetch_cockpit_ceo(conn, currency, year_month)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Cockpit /ceo error: %s", e, exc_info=True)
        raise HTTPException(500, detail=f"cockpit /ceo failed: {e}")

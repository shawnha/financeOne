"""Forecasts CRUD API — 예상 현금흐름 입력 데이터.

카테고리별 예상 입금/출금을 생성·조회·수정·삭제.
"""

from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])


class ForecastCreate(BaseModel):
    entity_id: int
    year: int
    month: int
    category: str
    subcategory: Optional[str] = None
    type: str  # 'in' or 'out'
    forecast_amount: float
    is_recurring: bool = False
    note: Optional[str] = None


class ForecastUpdate(BaseModel):
    forecast_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    is_recurring: Optional[bool] = None
    note: Optional[str] = None


@router.get("")
def list_forecasts(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    """특정 법인/연도의 forecasts 조회. month 생략 시 해당 연도 전체."""
    cur = conn.cursor()
    if month is not None:
        cur.execute(
            """
            SELECT id, entity_id, year, month, category, subcategory, type,
                   forecast_amount, actual_amount, is_recurring, note,
                   created_at, updated_at
            FROM forecasts
            WHERE entity_id = %s AND year = %s AND month = %s
            ORDER BY type, category, subcategory
            """,
            [entity_id, year, month],
        )
    else:
        cur.execute(
            """
            SELECT id, entity_id, year, month, category, subcategory, type,
                   forecast_amount, actual_amount, is_recurring, note,
                   created_at, updated_at
            FROM forecasts
            WHERE entity_id = %s AND year = %s
            ORDER BY month, type, category, subcategory
            """,
            [entity_id, year],
        )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    return {"forecasts": rows, "count": len(rows)}


@router.post("", status_code=201)
def create_forecast(
    body: ForecastCreate,
    conn: PgConnection = Depends(get_db),
):
    """forecast 항목 생성. UPSERT — 동일 키 존재 시 금액 업데이트."""
    if body.type not in ("in", "out"):
        raise HTTPException(400, "type must be 'in' or 'out'")

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO forecasts
            (entity_id, year, month, category, subcategory, type, forecast_amount, is_recurring, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (entity_id, year, month, category, subcategory, type)
        DO UPDATE SET forecast_amount = EXCLUDED.forecast_amount,
                      is_recurring = EXCLUDED.is_recurring,
                      note = EXCLUDED.note,
                      updated_at = NOW()
        RETURNING id
        """,
        [body.entity_id, body.year, body.month, body.category,
         body.subcategory, body.type, body.forecast_amount,
         body.is_recurring, body.note],
    )
    forecast_id = cur.fetchone()[0]
    conn.commit()
    cur.close()

    return {"id": forecast_id, "status": "created"}


@router.put("/{forecast_id}")
def update_forecast(
    forecast_id: int,
    body: ForecastUpdate,
    conn: PgConnection = Depends(get_db),
):
    """forecast 항목 부분 수정."""
    cur = conn.cursor()

    # Build dynamic SET clause
    updates = []
    params = []
    if body.forecast_amount is not None:
        updates.append("forecast_amount = %s")
        params.append(body.forecast_amount)
    if body.actual_amount is not None:
        updates.append("actual_amount = %s")
        params.append(body.actual_amount)
    if body.is_recurring is not None:
        updates.append("is_recurring = %s")
        params.append(body.is_recurring)
    if body.note is not None:
        updates.append("note = %s")
        params.append(body.note)

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = NOW()")
    params.append(forecast_id)

    cur.execute(
        f"UPDATE forecasts SET {', '.join(updates)} WHERE id = %s RETURNING id",
        params,
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Forecast not found")

    conn.commit()
    cur.close()

    return {"id": forecast_id, "status": "updated"}


@router.delete("/{forecast_id}")
def delete_forecast(
    forecast_id: int,
    conn: PgConnection = Depends(get_db),
):
    """forecast 항목 삭제."""
    cur = conn.cursor()
    cur.execute("DELETE FROM forecasts WHERE id = %s RETURNING id", [forecast_id])
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Forecast not found")

    conn.commit()
    cur.close()

    return {"id": forecast_id, "status": "deleted"}

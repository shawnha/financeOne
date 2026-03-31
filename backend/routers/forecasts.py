"""Forecasts CRUD API — 예상 현금흐름 입력 데이터.

카테고리별 예상 입금/출금을 생성·조회·수정·삭제.
"""

from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all

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
    internal_account_id: Optional[int] = None
    note: Optional[str] = None
    expected_day: Optional[int] = Field(None, ge=1, le=31)  # CQ-2
    payment_method: str = "bank"


class ForecastUpdate(BaseModel):
    forecast_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    is_recurring: Optional[bool] = None
    note: Optional[str] = None
    expected_day: Optional[int] = Field(None, ge=1, le=31)
    payment_method: Optional[str] = None


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
            SELECT f.id, f.entity_id, f.year, f.month, f.category, f.subcategory, f.type,
                   f.forecast_amount, f.actual_amount, f.is_recurring,
                   f.internal_account_id, ia.name AS internal_account_name,
                   f.note, f.expected_day, f.payment_method, f.created_at, f.updated_at
            FROM forecasts f
            LEFT JOIN internal_accounts ia ON f.internal_account_id = ia.id
            WHERE f.entity_id = %s AND f.year = %s AND f.month = %s
            ORDER BY f.type, f.category, f.subcategory
            """,
            [entity_id, year, month],
        )
    else:
        cur.execute(
            """
            SELECT f.id, f.entity_id, f.year, f.month, f.category, f.subcategory, f.type,
                   f.forecast_amount, f.actual_amount, f.is_recurring,
                   f.internal_account_id, ia.name AS internal_account_name,
                   f.note, f.expected_day, f.payment_method, f.created_at, f.updated_at
            FROM forecasts f
            LEFT JOIN internal_accounts ia ON f.internal_account_id = ia.id
            WHERE f.entity_id = %s AND f.year = %s
            ORDER BY f.month, f.type, f.category, f.subcategory
            """,
            [entity_id, year],
        )
    rows = fetch_all(cur)
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
            (entity_id, year, month, category, subcategory, type,
             forecast_amount, is_recurring, internal_account_id, note,
             expected_day, payment_method)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (entity_id, year, month, internal_account_id, type)
          WHERE internal_account_id IS NOT NULL
        DO UPDATE SET forecast_amount = EXCLUDED.forecast_amount,
                      is_recurring = EXCLUDED.is_recurring,
                      category = EXCLUDED.category,
                      note = EXCLUDED.note,
                      expected_day = EXCLUDED.expected_day,
                      payment_method = EXCLUDED.payment_method,
                      updated_at = NOW()
        RETURNING id
        """,
        [body.entity_id, body.year, body.month, body.category,
         body.subcategory, body.type, body.forecast_amount,
         body.is_recurring, body.internal_account_id, body.note,
         body.expected_day, body.payment_method],
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
    if body.expected_day is not None:
        updates.append("expected_day = %s")
        params.append(body.expected_day)
    if body.payment_method is not None:
        updates.append("payment_method = %s")
        params.append(body.payment_method)

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


@router.post("/copy-recurring", status_code=201)
def copy_recurring_forecasts(
    entity_id: int = Query(...),
    source_year: int = Query(...),
    source_month: int = Query(...),
    target_year: int = Query(...),
    target_month: int = Query(...),
    amount_source: str = Query("forecast"),
    conn: PgConnection = Depends(get_db),
):
    """is_recurring=true인 항목을 source → target 월로 복사.
    amount_source='actual'이면 actual_amount 우선 사용 (없으면 forecast_amount fallback).
    """
    if amount_source not in ("forecast", "actual"):
        raise HTTPException(400, "amount_source must be 'forecast' or 'actual'")

    # Choose which amount to copy as the new forecast_amount
    amount_expr = "forecast_amount"
    if amount_source == "actual":
        amount_expr = "COALESCE(actual_amount, forecast_amount)"

    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            INSERT INTO forecasts
                (entity_id, year, month, category, subcategory, type,
                 forecast_amount, is_recurring, internal_account_id, note,
                 expected_day, payment_method)
            SELECT entity_id, %s, %s, category, subcategory, type,
                   {amount_expr}, is_recurring, internal_account_id, note,
                   expected_day, payment_method
            FROM forecasts
            WHERE entity_id = %s AND year = %s AND month = %s AND is_recurring = true
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            [target_year, target_month, entity_id, source_year, source_month],
        )
        copied = len(cur.fetchall())
        conn.commit()
        cur.close()
        return {"copied": copied, "target": f"{target_year}-{target_month:02d}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/suggest-from-actuals")
def suggest_forecasts_from_actuals(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """전월 내부계정별 실제 지출을 예상 금액으로 제안."""
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12

    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.internal_account_id,
               ia.name AS account_name,
               ia.code AS account_code,
               ia.is_recurring,
               t.type,
               SUM(t.amount) AS total
        FROM transactions t
        JOIN internal_accounts ia ON t.internal_account_id = ia.id
        WHERE t.entity_id = %s
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND t.is_duplicate = false
          AND t.internal_account_id IS NOT NULL
        GROUP BY t.internal_account_id, ia.name, ia.code, ia.is_recurring, t.type
        ORDER BY ia.is_recurring DESC, total DESC
        """,
        [entity_id, prev_year, prev_month, prev_year, prev_month],
    )
    rows = fetch_all(cur)
    cur.close()

    return {
        "source_year": prev_year,
        "source_month": prev_month,
        "suggestions": rows,
    }

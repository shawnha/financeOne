"""환율 관리 API"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import date
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all
from backend.services.exchange_rate_service import (
    get_closing_rate,
    get_average_rate,
    ExchangeRateNotFoundError,
)
from backend.services.exchange_rate_fetcher import (
    fetch_exchange_rates,
    KoreaeximApiError,
)

router = APIRouter(prefix="/api/exchange-rates", tags=["exchange-rates"])


class ExchangeRateInput(BaseModel):
    date: date
    from_currency: str = "KRW"
    to_currency: str = "USD"
    rate: float
    source: str = "manual"


@router.get("")
def list_exchange_rates(
    from_currency: Optional[str] = None,
    to_currency: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    where = ["1=1"]
    params: list = []

    if from_currency:
        where.append("from_currency = %s")
        params.append(from_currency)
    if to_currency:
        where.append("to_currency = %s")
        params.append(to_currency)
    if date_from:
        where.append("date >= %s")
        params.append(date_from)
    if date_to:
        where.append("date <= %s")
        params.append(date_to)

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(f"SELECT COUNT(*) FROM exchange_rates WHERE {where_clause}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT id, date, from_currency, to_currency, rate, source
        FROM exchange_rates WHERE {where_clause}
        ORDER BY date DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    rows = fetch_all(cur)
    cur.close()

    return {"items": rows, "total": total, "page": page, "per_page": per_page}


@router.post("")
def create_exchange_rate(body: ExchangeRateInput, conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO exchange_rates (date, from_currency, to_currency, rate, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (date, from_currency, to_currency)
            DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source
            RETURNING id
            """,
            [body.date, body.from_currency, body.to_currency, body.rate, body.source],
        )
        rate_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"id": rate_id, "created": True}
    except Exception:
        conn.rollback()
        raise


@router.get("/closing")
def get_closing(
    from_currency: str = "KRW",
    to_currency: str = "USD",
    as_of_date: date = Query(...),
    conn: PgConnection = Depends(get_db),
):
    try:
        rate = get_closing_rate(conn, from_currency, to_currency, as_of_date)
        return {"rate": float(rate), "from": from_currency, "to": to_currency, "date": str(as_of_date)}
    except ExchangeRateNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("/average")
def get_average(
    from_currency: str = "KRW",
    to_currency: str = "USD",
    start_date: date = Query(...),
    end_date: date = Query(...),
    conn: PgConnection = Depends(get_db),
):
    try:
        rate = get_average_rate(conn, from_currency, to_currency, start_date, end_date)
        return {"rate": float(rate), "from": from_currency, "to": to_currency, "period": f"{start_date}~{end_date}"}
    except ExchangeRateNotFoundError as e:
        raise HTTPException(404, str(e))


class FetchRequest(BaseModel):
    start_date: date
    end_date: date


@router.post("/fetch")
def fetch_rates_from_koreaexim(
    body: FetchRequest,
    conn: PgConnection = Depends(get_db),
):
    """수출입은행 API에서 환율 데이터를 가져와 DB에 저장."""
    if (body.end_date - body.start_date).days > 365:
        raise HTTPException(400, "Date range must be within 365 days")
    try:
        result = fetch_exchange_rates(conn, body.start_date, body.end_date)
        return result
    except KoreaeximApiError as e:
        raise HTTPException(502, str(e))

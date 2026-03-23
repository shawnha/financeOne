"""내부거래 관리 API"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from datetime import date
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.intercompany_service import (
    detect_intercompany,
    confirm_pair,
    get_eliminations,
)

router = APIRouter(prefix="/api/intercompany", tags=["intercompany"])


class DetectRequest(BaseModel):
    entity_ids: list[int] = [1, 2, 3]
    start_date: date
    end_date: date
    date_tolerance_days: int = 1


@router.post("/detect")
def detect(body: DetectRequest, conn: PgConnection = Depends(get_db)):
    try:
        results = detect_intercompany(
            conn, body.entity_ids, body.start_date, body.end_date, body.date_tolerance_days,
        )
        conn.commit()
        return {"detected": len(results), "pairs": results}
    except Exception:
        conn.rollback()
        raise


@router.get("/pairs")
def list_pairs(
    start_date: date = Query(...),
    end_date: date = Query(...),
    confirmed_only: bool = False,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    confirmed_filter = "AND ip.is_confirmed = TRUE" if confirmed_only else ""
    cur.execute(
        f"""
        SELECT ip.*, ea.name AS entity_a_name, eb.name AS entity_b_name
        FROM intercompany_pairs ip
        LEFT JOIN entities ea ON ip.entity_a_id = ea.id
        LEFT JOIN entities eb ON ip.entity_b_id = eb.id
        WHERE ip.match_date >= %s AND ip.match_date <= %s {confirmed_filter}
        ORDER BY ip.match_date DESC
        """,
        [start_date, end_date],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return {"items": rows, "total": len(rows)}


@router.post("/pairs/{pair_id}/confirm")
def confirm(pair_id: int, conn: PgConnection = Depends(get_db)):
    try:
        result = confirm_pair(conn, pair_id)
        conn.commit()
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception:
        conn.rollback()
        raise


@router.delete("/pairs/{pair_id}")
def reject(pair_id: int, conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    cur.execute("DELETE FROM intercompany_pairs WHERE id = %s RETURNING id", [pair_id])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pair not found")
    conn.commit()
    cur.close()
    return {"deleted": True}

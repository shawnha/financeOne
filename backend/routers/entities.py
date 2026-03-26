"""법인 관리 API"""

from fastapi import APIRouter, Depends
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all

router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("")
def list_entities(conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, code, name, type, currency, parent_id, is_active FROM entities ORDER BY id"
    )
    rows = fetch_all(cur)
    cur.close()
    return rows

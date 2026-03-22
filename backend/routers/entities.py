"""법인 관리 API"""

from fastapi import APIRouter, Depends
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("")
def list_entities(conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, code, name, type, currency, parent_id, is_active FROM entities ORDER BY id"
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    return rows

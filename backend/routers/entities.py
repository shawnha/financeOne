"""법인 관리 API"""

from fastapi import APIRouter

from backend.database.connection import get_conn, put_conn

router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("")
def list_entities():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, code, name, type, currency, parent_id, is_active FROM entities ORDER BY id"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    finally:
        put_conn(conn)

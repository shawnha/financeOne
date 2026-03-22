"""계정과목 API"""

from fastapi import APIRouter, Depends
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("/standard")
def list_standard_accounts(conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, code, name, category, subcategory, normal_side, sort_order "
        "FROM standard_accounts WHERE is_active = true ORDER BY sort_order, code"
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


@router.get("/internal")
def list_internal_accounts(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    if entity_id is not None:
        cur.execute(
            """
            SELECT ia.id, ia.entity_id, ia.code, ia.name,
                   sa.code AS standard_code, sa.name AS standard_name,
                   ia.sort_order
            FROM internal_accounts ia
            LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
            WHERE ia.entity_id = %s AND ia.is_active = true
            ORDER BY ia.sort_order, ia.code
            """,
            [entity_id],
        )
    else:
        cur.execute(
            """
            SELECT ia.id, ia.entity_id, ia.code, ia.name,
                   sa.code AS standard_code, sa.name AS standard_name,
                   ia.sort_order
            FROM internal_accounts ia
            LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
            WHERE ia.is_active = true
            ORDER BY ia.entity_id, ia.sort_order, ia.code
            """
        )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


@router.get("/members")
def list_members(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    if entity_id is not None:
        cur.execute(
            "SELECT id, entity_id, name, role FROM members WHERE entity_id = %s AND is_active = true ORDER BY name",
            [entity_id],
        )
    else:
        cur.execute(
            "SELECT id, entity_id, name, role FROM members WHERE is_active = true ORDER BY entity_id, name"
        )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows

"""계정과목 API — CRUD for standard/internal accounts and members"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class InternalAccountCreate(BaseModel):
    entity_id: int
    code: str
    name: str
    standard_account_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = 0


class InternalAccountUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    standard_account_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class MemberCreate(BaseModel):
    entity_id: int
    name: str
    role: Optional[str] = "staff"


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None


# ---------------------------------------------------------------------------
# Standard accounts (read-only)
# ---------------------------------------------------------------------------

@router.get("/standard")
def list_standard_accounts(conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, code, name, category, subcategory, normal_side, sort_order "
        "FROM standard_accounts WHERE is_active = true ORDER BY sort_order, code"
    )
    rows = fetch_all(cur)
    cur.close()
    return rows


# ---------------------------------------------------------------------------
# Internal accounts — CRUD
# ---------------------------------------------------------------------------

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
                   ia.sort_order, ia.parent_id
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
                   ia.sort_order, ia.parent_id
            FROM internal_accounts ia
            LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
            WHERE ia.is_active = true
            ORDER BY ia.entity_id, ia.sort_order, ia.code
            """
        )
    rows = fetch_all(cur)
    cur.close()
    return rows


@router.post("/internal", status_code=201)
def create_internal_account(
    body: InternalAccountCreate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO internal_accounts
                (entity_id, code, name, standard_account_id, parent_id, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, entity_id, code, name, standard_account_id,
                      parent_id, sort_order, is_active
            """,
            [
                body.entity_id,
                body.code,
                body.name,
                body.standard_account_id,
                body.parent_id,
                body.sort_order,
            ],
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        conn.commit()
        return row
    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            raise HTTPException(
                status_code=409,
                detail=f"Account code '{body.code}' already exists for entity {body.entity_id}",
            )
        raise HTTPException(status_code=400, detail=error_msg)
    finally:
        cur.close()


@router.patch("/internal/{account_id}")
def update_internal_account(
    account_id: int,
    body: InternalAccountUpdate,
    conn: PgConnection = Depends(get_db),
):
    # Build dynamic SET clause from provided fields only
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = []
    params = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = %s")
        params.append(value)
    params.append(account_id)

    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE internal_accounts
            SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, entity_id, code, name, standard_account_id,
                      parent_id, sort_order, is_active
            """,
            params,
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail="Internal account not found")
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, result))
        conn.commit()
        return row
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


@router.delete("/internal/{account_id}")
def delete_internal_account(
    account_id: int,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        # Check for referencing transactions
        cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE internal_account_id = %s",
            [account_id],
        )
        tx_count = cur.fetchone()[0]

        # Soft-delete regardless, but include warning
        cur.execute(
            """
            UPDATE internal_accounts SET is_active = false
            WHERE id = %s AND is_active = true
            RETURNING id
            """,
            [account_id],
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Internal account not found or already deleted",
            )
        conn.commit()

        response = {"id": account_id, "deleted": True}
        if tx_count > 0:
            response["warning"] = (
                f"{tx_count} transaction(s) reference this account. "
                "They retain the reference but this account is now inactive."
            )
        return response
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Members — CRUD
# ---------------------------------------------------------------------------

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
    rows = fetch_all(cur)
    cur.close()
    return rows


@router.post("/members", status_code=201)
def create_member(
    body: MemberCreate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO members (entity_id, name, role)
            VALUES (%s, %s, %s)
            RETURNING id, entity_id, name, role, is_active
            """,
            [body.entity_id, body.name, body.role],
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        conn.commit()
        return row
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


@router.patch("/members/{member_id}")
def update_member(
    member_id: int,
    body: MemberUpdate,
    conn: PgConnection = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = []
    params = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = %s")
        params.append(value)
    params.append(member_id)

    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE members
            SET {', '.join(set_clauses)}
            WHERE id = %s AND is_active = true
            RETURNING id, entity_id, name, role, is_active
            """,
            params,
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail="Member not found")
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, result))
        conn.commit()
        return row
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


@router.delete("/members/{member_id}")
def delete_member(
    member_id: int,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        # Check for referencing transactions
        cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE member_id = %s",
            [member_id],
        )
        tx_count = cur.fetchone()[0]

        cur.execute(
            """
            UPDATE members SET is_active = false
            WHERE id = %s AND is_active = true
            RETURNING id
            """,
            [member_id],
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Member not found or already deleted",
            )
        conn.commit()

        response = {"id": member_id, "deleted": True}
        if tx_count > 0:
            response["warning"] = (
                f"{tx_count} transaction(s) reference this member. "
                "They retain the reference but this member is now inactive."
            )
        return response
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()

"""분개(Journal Entry) API"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import date
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.bookkeeping_engine import (
    create_journal_entry,
    bulk_create_journals,
    validate_trial_balance,
)

router = APIRouter(prefix="/api/journal-entries", tags=["journal-entries"])


class JournalLineInput(BaseModel):
    standard_account_id: int
    debit_amount: float = 0
    credit_amount: float = 0
    description: str = ""


class CreateJournalEntry(BaseModel):
    entity_id: int
    entry_date: date
    lines: list[JournalLineInput]
    description: str = ""
    is_adjusting: bool = False


class FromTransactions(BaseModel):
    entity_id: int
    transaction_ids: list[int]


@router.get("")
def list_journal_entries(
    entity_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []

    if entity_id is not None:
        where.append("je.entity_id = %s")
        params.append(entity_id)
    if date_from is not None:
        where.append("je.entry_date >= %s")
        params.append(date_from)
    if date_to is not None:
        where.append("je.entry_date <= %s")
        params.append(date_to)
    if status is not None:
        where.append("je.status = %s")
        params.append(status)

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(
        f"SELECT COUNT(*) FROM journal_entries je WHERE {where_clause}",
        params,
    )
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT je.id, je.entity_id, je.transaction_id, je.entry_date,
               je.description, je.is_adjusting, je.is_closing, je.status,
               je.created_at,
               e.name AS entity_name,
               (SELECT COALESCE(SUM(jel.debit_amount), 0)
                FROM journal_entry_lines jel
                WHERE jel.journal_entry_id = je.id) AS total_amount
        FROM journal_entries je
        LEFT JOIN entities e ON je.entity_id = e.id
        WHERE {where_clause}
        ORDER BY je.entry_date DESC, je.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    }


@router.get("/trial-balance")
def get_trial_balance(
    entity_id: int,
    as_of_date: Optional[date] = None,
    conn: PgConnection = Depends(get_db),
):
    return validate_trial_balance(conn, entity_id, as_of_date)


@router.get("/{je_id}")
def get_journal_entry(je_id: int, conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()

    cur.execute(
        """
        SELECT je.id, je.entity_id, je.transaction_id, je.entry_date,
               je.description, je.is_adjusting, je.is_closing, je.status,
               je.created_at, e.name AS entity_name
        FROM journal_entries je
        LEFT JOIN entities e ON je.entity_id = e.id
        WHERE je.id = %s
        """,
        [je_id],
    )
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Journal entry not found")
    header = dict(zip(cols, row))

    cur.execute(
        """
        SELECT jel.id, jel.standard_account_id, jel.debit_amount, jel.credit_amount,
               jel.description, jel.sort_order,
               sa.code AS account_code, sa.name AS account_name
        FROM journal_entry_lines jel
        LEFT JOIN standard_accounts sa ON jel.standard_account_id = sa.id
        WHERE jel.journal_entry_id = %s
        ORDER BY jel.sort_order
        """,
        [je_id],
    )
    li_cols = [d[0] for d in cur.description]
    lines = [dict(zip(li_cols, r)) for r in cur.fetchall()]
    cur.close()

    header["lines"] = lines
    return header


@router.post("")
def create_manual_journal_entry(
    body: CreateJournalEntry,
    conn: PgConnection = Depends(get_db),
):
    if not body.lines:
        raise HTTPException(400, "At least one line required")

    lines = [line.model_dump() for line in body.lines]

    try:
        je_id = create_journal_entry(
            conn=conn,
            entity_id=body.entity_id,
            lines=lines,
            entry_date=body.entry_date,
            description=body.description,
            is_adjusting=body.is_adjusting,
        )
        conn.commit()
        return {"id": je_id, "created": True}
    except ValueError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    except Exception:
        conn.rollback()
        raise


@router.post("/from-transactions")
def create_journals_from_transactions(
    body: FromTransactions,
    conn: PgConnection = Depends(get_db),
):
    if not body.transaction_ids:
        raise HTTPException(400, "No transaction IDs provided")

    try:
        result = bulk_create_journals(conn, body.entity_id, body.transaction_ids)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise

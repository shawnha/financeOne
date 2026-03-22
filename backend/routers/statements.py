"""재무제표 API"""

from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

router = APIRouter(prefix="/api/statements", tags=["statements"])


@router.get("")
def list_statements(
    entity_id: Optional[int] = None,
    fiscal_year: Optional[int] = None,
    statement_type: Optional[str] = None,
    is_consolidated: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []

    if entity_id is not None:
        where.append("fs.entity_id = %s")
        params.append(entity_id)
    if fiscal_year is not None:
        where.append("fs.fiscal_year = %s")
        params.append(fiscal_year)
    if statement_type is not None:
        where.append("fs.statement_type = %s")
        params.append(statement_type)
    if is_consolidated is not None:
        where.append("fs.is_consolidated = %s")
        params.append(is_consolidated)

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(f"SELECT COUNT(*) FROM financial_statements fs WHERE {where_clause}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT fs.id, fs.entity_id, fs.fiscal_year, fs.ki_num,
               fs.start_month, fs.end_month, fs.statement_type,
               fs.is_consolidated, fs.status, fs.auditor_name, fs.notes,
               e.name AS entity_name
        FROM financial_statements fs
        LEFT JOIN entities e ON fs.entity_id = e.id
        WHERE {where_clause}
        ORDER BY fs.fiscal_year DESC, fs.ki_num DESC
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


@router.get("/{stmt_id}")
def get_statement(stmt_id: int, conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()

    cur.execute(
        """
        SELECT fs.*, e.name AS entity_name
        FROM financial_statements fs
        LEFT JOIN entities e ON fs.entity_id = e.id
        WHERE fs.id = %s
        """,
        [stmt_id],
    )
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Statement not found")
    header = dict(zip(cols, row))

    cur.execute(
        """
        SELECT li.id, li.statement_id, li.statement_type, li.account_code,
               li.line_key, li.label, li.sort_order, li.is_section_header,
               li.auto_amount, li.auto_debit, li.auto_credit,
               li.manual_amount, li.manual_debit, li.manual_credit, li.note
        FROM financial_statement_line_items li
        WHERE li.statement_id = %s
        ORDER BY li.statement_type, li.sort_order
        """,
        [stmt_id],
    )
    li_cols = [d[0] for d in cur.description]
    line_items = [dict(zip(li_cols, r)) for r in cur.fetchall()]
    cur.close()

    header["line_items"] = line_items
    return header

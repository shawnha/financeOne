"""거래내역 API"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import date
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all
from backend.services.bookkeeping_engine import create_journal_from_transaction
from backend.services.mapping_service import learn_mapping_rule, auto_map_transaction

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionUpdate(BaseModel):
    internal_account_id: Optional[int] = None
    standard_account_id: Optional[int] = None
    is_confirmed: Optional[bool] = None
    note: Optional[str] = None


class BulkConfirm(BaseModel):
    ids: list[int]


@router.get("")
def list_transactions(
    entity_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    source_type: Optional[str] = None,
    is_confirmed: Optional[bool] = None,
    search: Optional[str] = None,
    member_id: Optional[int] = None,
    standard_account_id: Optional[int] = None,
    internal_account_id: Optional[int] = None,
    unclassified: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []

    if entity_id is not None:
        where.append("t.entity_id = %s")
        params.append(entity_id)
    if date_from is not None:
        where.append("t.date >= %s")
        params.append(date_from)
    if date_to is not None:
        where.append("t.date <= %s")
        params.append(date_to)
    if source_type is not None:
        where.append("t.source_type = %s")
        params.append(source_type)
    if is_confirmed is not None:
        where.append("t.is_confirmed = %s")
        params.append(is_confirmed)
    if member_id is not None:
        where.append("t.member_id = %s")
        params.append(member_id)
    if standard_account_id is not None:
        where.append("t.standard_account_id = %s")
        params.append(standard_account_id)
    if internal_account_id is not None:
        where.append("t.internal_account_id = %s")
        params.append(internal_account_id)
    if unclassified:
        where.append("t.is_confirmed = false AND t.standard_account_id IS NULL")
    if search:
        where.append("(t.description ILIKE %s OR t.counterparty ILIKE %s OR t.note ILIKE %s)")
        q = f"%{search}%"
        params.extend([q, q, q])

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    # Count
    cur.execute(f"SELECT COUNT(*) FROM transactions t WHERE {where_clause}", params)
    total = cur.fetchone()[0]

    # Data with JOINs
    cur.execute(
        f"""
        SELECT t.id, t.entity_id, t.date, t.amount, t.currency, t.type,
               t.description, t.counterparty, t.source_type,
               t.mapping_confidence, t.mapping_source, t.is_confirmed,
               t.is_duplicate, t.note, t.member_id,
               t.internal_account_id, t.standard_account_id, t.is_cancel, t.card_number,
               m.name AS member_name,
               ia.code AS internal_account_code, ia.name AS internal_account_name,
               sa.code AS standard_account_code, sa.name AS standard_account_name
        FROM transactions t
        LEFT JOIN members m ON t.member_id = m.id
        LEFT JOIN internal_accounts ia ON t.internal_account_id = ia.id
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE {where_clause}
        ORDER BY t.date DESC, t.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    rows = fetch_all(cur)
    cur.close()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    }


@router.patch("/{tx_id}")
def update_transaction(
    tx_id: int,
    body: TransactionUpdate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        sets = []
        params: list = []
        data = body.model_dump(exclude_none=True)
        if not data:
            raise HTTPException(400, "No fields to update")

        for key, val in data.items():
            sets.append(f"{key} = %s")
            params.append(val)

        sets.append("updated_at = NOW()")
        params.append(tx_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s RETURNING id, is_confirmed, standard_account_id",
            params,
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Transaction not found")

        tx_id_out, is_confirmed, std_account_id = row[0], row[1], row[2]
        journal_entry_id = None
        journal_error = None

        # 매핑 학습: internal_account_id 변경 시 mapping_rules UPSERT
        if body.internal_account_id is not None:
            # 거래의 counterparty + entity_id 조회
            cur.execute("SELECT counterparty, entity_id FROM transactions WHERE id = %s", [tx_id])
            tx_info = cur.fetchone()
            if tx_info and tx_info[0]:
                learn_mapping_rule(
                    cur,
                    entity_id=tx_info[1],
                    counterparty=tx_info[0],
                    internal_account_id=body.internal_account_id,
                )

            # 내부계정의 표준계정도 자동 설정
            if body.standard_account_id is None:
                cur.execute(
                    "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
                    [body.internal_account_id],
                )
                std_row = cur.fetchone()
                if std_row and std_row[0]:
                    cur.execute(
                        "UPDATE transactions SET standard_account_id = %s WHERE id = %s",
                        [std_row[0], tx_id],
                    )
                    std_account_id = std_row[0]

        # 확정 + 매핑 완료 → 자동 분개 생성 (원자성)
        if is_confirmed and std_account_id:
            try:
                journal_entry_id = create_journal_from_transaction(conn, tx_id_out)
            except ValueError as e:
                if "already exists" not in str(e):
                    journal_error = str(e)

        conn.commit()
        cur.close()
        return {"id": tx_id_out, "updated": True, "journal_entry_id": journal_entry_id, "journal_error": journal_error}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise


@router.post("/auto-map")
def auto_map_unmapped(
    entity_id: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """미분류 거래에 mapping_rules 기반 자동 매핑 일괄 적용"""
    cur = conn.cursor()
    try:
        # 미분류 거래 조회 (internal_account_id가 NULL이고 counterparty가 있는 거래)
        cur.execute(
            """
            SELECT id, counterparty
            FROM transactions
            WHERE entity_id = %s
              AND internal_account_id IS NULL
              AND counterparty IS NOT NULL
              AND counterparty != ''
            """,
            [entity_id],
        )
        unmapped = cur.fetchall()

        mapped_count = 0
        mapped_ids = []
        for tx_id, counterparty in unmapped:
            mapping = auto_map_transaction(cur, entity_id=entity_id, counterparty=counterparty)
            if mapping:
                cur.execute(
                    """
                    UPDATE transactions
                    SET internal_account_id = %s,
                        standard_account_id = %s,
                        mapping_confidence = %s,
                        mapping_source = 'rule',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    [
                        mapping["internal_account_id"],
                        mapping["standard_account_id"],
                        mapping["confidence"],
                        tx_id,
                    ],
                )
                mapped_count += 1
                mapped_ids.append(tx_id)

        conn.commit()
        cur.close()
        return {
            "total_unmapped": len(unmapped),
            "mapped": mapped_count,
            "mapped_ids": mapped_ids,
        }
    except Exception:
        conn.rollback()
        raise


@router.post("/bulk-confirm")
def bulk_confirm(body: BulkConfirm, conn: PgConnection = Depends(get_db)):
    if not body.ids:
        raise HTTPException(400, "No IDs provided")
    cur = conn.cursor()
    try:
        placeholders = ",".join(["%s"] * len(body.ids))
        cur.execute(
            f"UPDATE transactions SET is_confirmed = true, updated_at = NOW() WHERE id IN ({placeholders}) RETURNING id",
            body.ids,
        )
        updated = [r[0] for r in cur.fetchall()]

        # 벌크 확정 → 자동 분개 생성
        journal_created = 0
        journal_skipped = []
        for tx_id in updated:
            try:
                create_journal_from_transaction(conn, tx_id)
                journal_created += 1
            except ValueError as e:
                journal_skipped.append({"id": tx_id, "reason": str(e)})

        conn.commit()
        cur.close()
        return {"confirmed": len(updated), "ids": updated, "journals_created": journal_created, "journal_skipped": journal_skipped}
    except Exception:
        conn.rollback()
        raise

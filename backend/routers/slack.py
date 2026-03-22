"""Slack 메시지 매칭 API -- slack_messages <-> transactions 연결."""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

router = APIRouter(prefix="/api/slack", tags=["slack"])


class ConfirmMatch(BaseModel):
    transaction_id: int
    match_confidence: Optional[float] = None
    ai_reasoning: Optional[str] = None
    note: Optional[str] = None
    amount_override: Optional[float] = None
    text_override: Optional[str] = None
    project_tag_override: Optional[str] = None


class IgnoreMessage(BaseModel):
    reason: Optional[str] = None


@router.get("/messages")
def list_slack_messages(
    entity_id: Optional[int] = None,
    is_completed: Optional[bool] = None,
    is_cancelled: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    """List slack messages with match status."""
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []

    if entity_id is not None:
        where.append("sm.entity_id = %s")
        params.append(entity_id)
    if is_completed is not None:
        where.append("sm.is_completed = %s")
        params.append(is_completed)
    if is_cancelled is not None:
        where.append("sm.is_cancelled = %s")
        params.append(is_cancelled)

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(
        f"SELECT COUNT(*) FROM slack_messages sm WHERE {where_clause}",
        params,
    )
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT sm.id, sm.entity_id, sm.ts, sm.channel, sm.user_id, sm.text,
               sm.parsed_amount, sm.parsed_amount_vat_included,
               sm.vat_flag, sm.project_tag,
               sm.is_completed, sm.is_cancelled,
               sm.date_override, sm.reply_count,
               sm.created_at,
               tsm.id AS match_id,
               tsm.transaction_id AS matched_transaction_id,
               tsm.match_confidence,
               tsm.is_confirmed AS match_confirmed,
               tsm.is_manual AS match_manual
        FROM slack_messages sm
        LEFT JOIN transaction_slack_match tsm ON sm.id = tsm.slack_message_id
        WHERE {where_clause}
        ORDER BY sm.created_at DESC
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


@router.get("/messages/{message_id}/candidates")
def get_candidates(
    message_id: int,
    conn: PgConnection = Depends(get_db),
):
    """Find candidate transactions for a slack message (amount match +/-1, +/-3%, VAT x1.1)."""
    cur = conn.cursor()

    # Get the slack message
    cur.execute(
        "SELECT id, entity_id, parsed_amount, parsed_amount_vat_included, date_override FROM slack_messages WHERE id = %s",
        [message_id],
    )
    msg = cur.fetchone()
    if not msg:
        raise HTTPException(404, "Slack message not found")

    msg_id, entity_id, parsed_amount, parsed_amount_vat, date_override = msg

    if parsed_amount is None:
        cur.close()
        return {"candidates": [], "message_id": message_id, "reason": "parsed_amount is NULL"}

    amount = float(parsed_amount)

    # Build candidate conditions:
    # 1. Exact match +/- 1
    # 2. Within 3%
    # 3. VAT included (amount * 1.1)
    lower_3pct = round(amount * 0.97, 2)
    upper_3pct = round(amount * 1.03, 2)
    vat_amount = round(amount * 1.1, 2)
    vat_lower = round(vat_amount * 0.97, 2)
    vat_upper = round(vat_amount * 1.03, 2)

    where_parts = ["t.entity_id = %s"]
    params: list = [entity_id]

    # Amount matching: within 3% of parsed_amount OR within 3% of VAT amount
    where_parts.append(
        "(t.amount BETWEEN %s AND %s OR t.amount BETWEEN %s AND %s)"
    )
    params.extend([lower_3pct, upper_3pct, vat_lower, vat_upper])

    # Optionally filter by date if date_override is set (within 7 days)
    if date_override:
        where_parts.append("t.date BETWEEN %s - interval '7 days' AND %s + interval '7 days'")
        params.extend([date_override, date_override])

    # Exclude already matched transactions
    where_parts.append(
        "t.id NOT IN (SELECT transaction_id FROM transaction_slack_match WHERE is_confirmed = true)"
    )

    where_clause = " AND ".join(where_parts)

    cur.execute(
        f"""
        SELECT t.id, t.date, t.amount, t.currency, t.type,
               t.description, t.counterparty, t.source_type,
               t.is_confirmed,
               CASE
                   WHEN ABS(t.amount - %s) <= 1 THEN 'exact'
                   WHEN t.amount BETWEEN %s AND %s THEN 'within_3pct'
                   WHEN t.amount BETWEEN %s AND %s THEN 'vat_match'
                   ELSE 'fuzzy'
               END AS match_type,
               CASE
                   WHEN ABS(t.amount - %s) <= 1 THEN 0.95
                   WHEN t.amount BETWEEN %s AND %s THEN 0.80
                   WHEN t.amount BETWEEN %s AND %s THEN 0.75
                   ELSE 0.50
               END AS confidence
        FROM transactions t
        WHERE {where_clause}
        ORDER BY confidence DESC, ABS(t.amount - %s) ASC
        LIMIT 20
        """,
        [
            amount, lower_3pct, upper_3pct, vat_lower, vat_upper,  # match_type CASE
            amount, lower_3pct, upper_3pct, vat_lower, vat_upper,  # confidence CASE
        ] + params + [amount],  # ORDER BY
    )
    cols = [d[0] for d in cur.description]
    candidates = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    return {
        "message_id": message_id,
        "parsed_amount": amount,
        "candidates": candidates,
    }


@router.post("/messages/{message_id}/confirm")
def confirm_match(
    message_id: int,
    body: ConfirmMatch,
    conn: PgConnection = Depends(get_db),
):
    """Create a transaction_slack_match record and mark message as completed."""
    cur = conn.cursor()
    try:
        # Verify slack message exists
        cur.execute("SELECT id, entity_id FROM slack_messages WHERE id = %s", [message_id])
        msg = cur.fetchone()
        if not msg:
            raise HTTPException(404, "Slack message not found")

        # Verify transaction exists
        cur.execute("SELECT id FROM transactions WHERE id = %s", [body.transaction_id])
        if not cur.fetchone():
            raise HTTPException(404, "Transaction not found")

        # Check for existing confirmed match
        cur.execute(
            "SELECT id FROM transaction_slack_match WHERE slack_message_id = %s AND is_confirmed = true",
            [message_id],
        )
        if cur.fetchone():
            raise HTTPException(409, "이 Slack 메시지는 이미 매칭이 확정되었습니다.")

        # Create match record
        cur.execute(
            """
            INSERT INTO transaction_slack_match
                (transaction_id, slack_message_id, match_confidence, is_manual, is_confirmed,
                 ai_reasoning, note, amount_override, text_override, project_tag_override)
            VALUES (%s, %s, %s, true, true, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            [
                body.transaction_id, message_id,
                body.match_confidence or 1.0,
                body.ai_reasoning, body.note,
                body.amount_override, body.text_override, body.project_tag_override,
            ],
        )
        match_id = cur.fetchone()[0]

        # Mark slack message as completed
        cur.execute(
            "UPDATE slack_messages SET is_completed = true WHERE id = %s",
            [message_id],
        )

        conn.commit()
        cur.close()
        return {"match_id": match_id, "message_id": message_id, "confirmed": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise


@router.post("/messages/{message_id}/ignore")
def ignore_message(
    message_id: int,
    body: IgnoreMessage,
    conn: PgConnection = Depends(get_db),
):
    """Mark a slack message as cancelled/ignored."""
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE slack_messages SET is_cancelled = true WHERE id = %s RETURNING id",
            [message_id],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Slack message not found")

        conn.commit()
        cur.close()
        return {"message_id": message_id, "ignored": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise

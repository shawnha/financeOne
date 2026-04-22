"""ExpenseOne ↔ 거래 매칭 메뉴 엔드포인트.

미매칭 expense 목록 / 후보 거래 조회 / 수동 매칭 확정 / 매칭 풀기.
자동 매칭은 integrations.expenseone.sync_to_financeone에서 이미 수행됨.
이 라우터는 수동 매칭 UI용.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PgConnection
from pydantic import BaseModel

from backend.database.connection import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/expenseone-match", tags=["expenseone-match"])


# ── Helpers ───────────────────────────────────────────

def _fetch_dicts(cur) -> list[dict]:
    cols = [c[0] for c in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _expense_row(r: dict) -> dict:
    """expenseone.expenses row + match + entity dict."""
    return {
        "expense_id": str(r["id"]),
        "type": r["type"],
        "status": r["status"],
        "title": r["title"],
        "description": r["description"],
        "amount": int(r["amount"]) if r.get("amount") is not None else 0,
        "category": r["category"],
        "merchant_name": r.get("merchant_name"),
        "transaction_date": r["transaction_date"].isoformat() if r.get("transaction_date") else None,
        "card_last_four": r.get("card_last_four"),
        "bank_name": r.get("bank_name"),
        "account_holder": r.get("account_holder"),
        "is_urgent": bool(r.get("is_urgent")),
        "is_pre_paid": bool(r.get("is_pre_paid")),
        "approved_at": r["approved_at"].isoformat() if r.get("approved_at") else None,
        "company_id": str(r["company_id"]) if r.get("company_id") else None,
        "company_name": r.get("company_name"),
        "submitter_name": r.get("submitter_name"),
        "entity_id": r.get("entity_id"),
        "match": (
            {
                "match_id": r["match_id"],
                "transaction_id": r["match_tx_id"],
                "confidence": float(r["match_confidence"]) if r.get("match_confidence") is not None else None,
                "method": r.get("match_method"),
                "is_manual": bool(r.get("match_is_manual")),
                "is_confirmed": bool(r.get("match_is_confirmed")),
                "reasoning": r.get("match_reasoning"),
            }
            if r.get("match_id")
            else None
        ),
    }


def _company_to_entity_sql() -> str:
    """companies.name ↔ entities.name 매칭 subquery (LATERAL join 용)."""
    return """
        LEFT JOIN LATERAL (
            SELECT ent.id AS entity_id
            FROM expenseone.companies c2
            JOIN financeone.entities ent
              ON ent.name LIKE '%%' || c2.name || '%%' OR c2.name LIKE '%%' || ent.name || '%%'
            WHERE c2.id = e.company_id AND ent.is_active = TRUE
            LIMIT 1
        ) ent ON TRUE
    """


# ── Endpoints ─────────────────────────────────────────


@router.get("/unmatched-count")
def unmatched_count(
    entity_id: Optional[int] = Query(None),
    conn: PgConnection = Depends(get_db),
):
    """사이드바 뱃지용 — 매칭 안 된 승인 경비 개수."""
    cur = conn.cursor()
    where = ["e.status = 'APPROVED'"]
    params: list = []

    sql = f"""
        SELECT COUNT(*)
        FROM expenseone.expenses e
        {_company_to_entity_sql()}
        LEFT JOIN transaction_expenseone_match m ON m.expense_id = e.id
        WHERE {' AND '.join(where)} AND m.id IS NULL
    """
    if entity_id is not None:
        sql += " AND ent.entity_id = %s"
        params.append(entity_id)

    cur.execute(sql, params)
    count = cur.fetchone()[0]
    cur.close()
    return {"unmatched_count": count}


@router.get("/expenses")
def list_expenses(
    entity_id: Optional[int] = Query(None),
    status: str = Query("unmatched", description="unmatched|matched|all"),
    expense_type: Optional[str] = Query(None, description="CORPORATE_CARD|DEPOSIT_REQUEST"),
    month: Optional[str] = Query(None, description="YYYY-MM (transaction_date 기준)"),
    limit: int = Query(200, ge=1, le=500),
    conn: PgConnection = Depends(get_db),
):
    """승인된 ExpenseOne expense 리스트 + 매칭 상태."""
    cur = conn.cursor()
    where = ["e.status = 'APPROVED'"]
    params: list = []

    if expense_type:
        where.append("e.type = %s")
        params.append(expense_type)

    if month:
        try:
            y, m = month.split("-")
            where.append("e.transaction_date >= make_date(%s, %s, 1)")
            params.extend([int(y), int(m)])
            if int(m) == 12:
                where.append("e.transaction_date < make_date(%s, 1, 1)")
                params.append(int(y) + 1)
            else:
                where.append("e.transaction_date < make_date(%s, %s, 1)")
                params.extend([int(y), int(m) + 1])
        except (ValueError, IndexError):
            raise HTTPException(400, "month must be YYYY-MM")

    having = ""
    if status == "unmatched":
        having = "AND m.id IS NULL"
    elif status == "matched":
        having = "AND m.id IS NOT NULL"

    if entity_id is not None:
        where.append("ent.entity_id = %s")
        params.append(entity_id)

    sql = f"""
        SELECT
            e.id, e.type, e.status, e.title, e.description, e.amount, e.category,
            e.merchant_name, e.transaction_date, e.card_last_four,
            e.bank_name, e.account_holder,
            e.is_urgent, e.is_pre_paid, e.approved_at, e.company_id,
            c.name AS company_name,
            u.name AS submitter_name,
            ent.entity_id,
            m.id AS match_id,
            m.transaction_id AS match_tx_id,
            m.match_confidence,
            m.match_method,
            m.is_manual AS match_is_manual,
            m.is_confirmed AS match_is_confirmed,
            m.ai_reasoning AS match_reasoning
        FROM expenseone.expenses e
        LEFT JOIN expenseone.users u ON e.submitted_by_id = u.id
        LEFT JOIN expenseone.companies c ON e.company_id = c.id
        {_company_to_entity_sql()}
        LEFT JOIN transaction_expenseone_match m ON m.expense_id = e.id
        WHERE {' AND '.join(where)} {having}
        ORDER BY e.approved_at DESC NULLS LAST, e.id DESC
        LIMIT %s
    """
    cur.execute(sql, params + [limit])
    rows = _fetch_dicts(cur)
    cur.close()

    return {
        "expenses": [_expense_row(r) for r in rows],
        "total": len(rows),
    }


@router.get("/expenses/{expense_id}/candidates")
def get_candidates(
    expense_id: str,
    date_window: int = Query(7, ge=0, le=30),
    cross_entity: bool = Query(False, description="entity 무시 (intercompany 케이스)"),
    amount_tolerance_pct: float = Query(
        0.0, ge=0.0, le=10.0,
        description="금액 허용 오차 %. 해외결제 환율 차이·수수료 대응. 0=정확.",
    ),
    ignore_card_digits: bool = Query(
        False,
        description="카드 끝자리 ordering 무시 (끝자리 모르는 expense 매칭용)",
    ),
    conn: PgConnection = Depends(get_db),
):
    """단일 expense에 매칭 가능한 거래 후보 조회."""
    cur = conn.cursor()

    # expense 본체 조회
    cur.execute(
        f"""
        SELECT e.id, e.type, e.amount, e.transaction_date, e.approved_at,
               e.card_last_four, e.account_holder, e.merchant_name, e.title,
               e.company_id, ent.entity_id
        FROM expenseone.expenses e
        {_company_to_entity_sql()}
        WHERE e.id = %s
        """,
        [expense_id],
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "expense not found")

    _id, exp_type, amount, txn_date, approved_at, card_last4, holder, merchant, title, company_id, entity_id = row
    amount = int(amount) if amount else 0
    ref_date = txn_date or (approved_at.date() if approved_at else None)
    if not ref_date or amount <= 0:
        cur.close()
        return {"candidates": [], "expense_summary": None}

    # candidate source_type 결정
    if exp_type == "CORPORATE_CARD":
        source_types: tuple[str, ...] = (
            "lotte_card", "woori_card", "shinhan_card",
            "codef_lotte_card", "codef_woori_card", "codef_shinhan_card",
        )
        type_filter = "t.source_type = ANY(%s)"
    elif exp_type == "DEPOSIT_REQUEST":
        source_types = ("woori_bank", "codef_woori_bank", "codef_ibk_bank")
        type_filter = "t.source_type = ANY(%s) AND t.type = 'out'"
    else:
        source_types = ()
        type_filter = "TRUE"

    entity_filter = ""
    entity_param: Optional[int] = None
    if not cross_entity and entity_id is not None:
        entity_filter = "AND t.entity_id = %s"
        entity_param = entity_id

    # 금액 허용 오차 (예: 1% 설정 시 amount*0.99 ~ amount*1.01 사이)
    tol = max(0.0, min(amount_tolerance_pct, 10.0)) / 100.0
    amount_lo = amount * (1 - tol)
    amount_hi = amount * (1 + tol)

    # 카드 끝자리 우선 정렬 가중치 (expense의 card_last4 존재 시 매칭되는 카드를 위로)
    # card_last4는 숫자만 검증 (SQL injection 방지)
    card_order_clause = ""
    use_card_ordering = (
        exp_type == "CORPORATE_CARD"
        and card_last4
        and str(card_last4).isdigit()
        and not ignore_card_digits
    )
    if use_card_ordering:
        card_order_clause = f"""
            CASE WHEN t.card_number IS NOT NULL
                  AND LENGTH(t.card_number) >= 3
                  AND (
                    t.card_number = '****{card_last4}'
                    OR RIGHT(t.card_number, 4) = '{card_last4}'
                    OR RIGHT(t.card_number, 3) = RIGHT('{card_last4}', 3)
                  )
                THEN 0 ELSE 1 END,
        """

    sql = f"""
        SELECT
            t.id, t.entity_id, t.date, t.amount, t.type, t.source_type,
            t.counterparty, t.card_number, t.description,
            ent.name AS entity_name,
            m.expense_id AS already_linked_expense,
            ABS(t.date - %s::date) AS day_diff,
            ABS(t.amount - %s) AS amount_diff
        FROM transactions t
        JOIN entities ent ON ent.id = t.entity_id
        LEFT JOIN transaction_expenseone_match m ON m.transaction_id = t.id
        WHERE t.date BETWEEN (%s::date - (%s || ' days')::interval)
                         AND (%s::date + (%s || ' days')::interval)
          AND {type_filter}
          {entity_filter}
          AND t.amount BETWEEN %s AND %s
        ORDER BY
            CASE WHEN m.expense_id IS NULL THEN 0 ELSE 1 END,
            {card_order_clause}
            ABS(t.amount - %s) ASC,
            ABS(t.date - %s::date) ASC
        LIMIT 25
    """
    # param 순서:
    #   SELECT: day_diff ref_date, amount_diff amount
    #   WHERE: BETWEEN start ref_date, date_window, BETWEEN end ref_date, date_window,
    #          [source_types], [entity_id], amount_lo, amount_hi
    #   ORDER BY: amount ref (for ABS), ref_date
    params_full: list = [ref_date, amount, ref_date, date_window, ref_date, date_window]
    if source_types:
        params_full.append(list(source_types))
    if entity_param is not None:
        params_full.append(entity_param)
    params_full.extend([amount_lo, amount_hi, amount, ref_date])

    cur.execute(sql, params_full)
    rows = _fetch_dicts(cur)
    cur.close()

    candidates = [
        {
            "transaction_id": r["id"],
            "entity_id": r["entity_id"],
            "entity_name": r.get("entity_name"),
            "date": r["date"].isoformat() if r.get("date") else None,
            "amount": int(r["amount"]) if r.get("amount") is not None else 0,
            "type": r["type"],
            "source_type": r["source_type"],
            "counterparty": r.get("counterparty"),
            "card_number": r.get("card_number"),
            "description": r.get("description"),
            "day_diff": int(r["day_diff"]) if r.get("day_diff") is not None else None,
            "amount_diff": int(r["amount_diff"]) if r.get("amount_diff") is not None else None,
            "already_linked_expense": str(r["already_linked_expense"]) if r.get("already_linked_expense") else None,
        }
        for r in rows
    ]
    return {
        "expense_summary": {
            "expense_id": expense_id,
            "type": exp_type,
            "amount": amount,
            "date": ref_date.isoformat(),
            "card_last_four": card_last4,
            "account_holder": holder,
            "merchant_name": merchant,
            "title": title,
            "entity_id": entity_id,
        },
        "candidates": candidates,
    }


class ConfirmMatchBody(BaseModel):
    transaction_id: int
    note: Optional[str] = None


@router.post("/expenses/{expense_id}/confirm")
def confirm_match(
    expense_id: str,
    body: ConfirmMatchBody,
    conn: PgConnection = Depends(get_db),
):
    """수동 매칭 확정 — join 테이블에 INSERT/UPSERT + is_manual + is_confirmed."""
    cur = conn.cursor()
    try:
        # 대상 거래 검증
        cur.execute("SELECT id FROM transactions WHERE id = %s", [body.transaction_id])
        if not cur.fetchone():
            raise HTTPException(404, "transaction not found")

        # expense 존재 검증
        cur.execute("SELECT id, type FROM expenseone.expenses WHERE id = %s", [expense_id])
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "expense not found")
        exp_type = row[1] or ""

        # 해당 거래에 이미 다른 expense가 걸려있으면 거부 (1:1 unique는 expense_id에만 있음)
        cur.execute(
            """
            SELECT id, expense_id FROM transaction_expenseone_match
            WHERE transaction_id = %s AND expense_id != %s
            """,
            [body.transaction_id, expense_id],
        )
        existing = cur.fetchone()
        if existing:
            raise HTTPException(
                409,
                f"transaction {body.transaction_id} already matched to expense {existing[1]}",
            )

        cur.execute(
            """
            INSERT INTO transaction_expenseone_match
                (transaction_id, expense_id, expense_type, match_confidence,
                 match_method, is_manual, is_confirmed, ai_reasoning, note,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, TRUE, TRUE, %s, %s, NOW(), NOW())
            ON CONFLICT (expense_id) DO UPDATE SET
                transaction_id = EXCLUDED.transaction_id,
                match_method = EXCLUDED.match_method,
                is_manual = TRUE,
                is_confirmed = TRUE,
                ai_reasoning = EXCLUDED.ai_reasoning,
                note = COALESCE(EXCLUDED.note, transaction_expenseone_match.note),
                updated_at = NOW()
            RETURNING id
            """,
            [
                body.transaction_id,
                expense_id,
                exp_type,
                1.0,
                "manual",
                "수동 매칭",
                body.note,
            ],
        )
        match_id = cur.fetchone()[0]
        conn.commit()
        return {"ok": True, "match_id": match_id, "transaction_id": body.transaction_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        logger.exception("confirm_match failed")
        raise HTTPException(500, "confirm failed")
    finally:
        cur.close()


@router.delete("/expenses/{expense_id}/match")
def unlink_match(
    expense_id: str,
    conn: PgConnection = Depends(get_db),
):
    """매칭 풀기 — join row 삭제."""
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM transaction_expenseone_match WHERE expense_id = %s RETURNING id",
            [expense_id],
        )
        deleted = cur.fetchone()
        conn.commit()
        return {"ok": True, "deleted": deleted[0] if deleted else None}
    except Exception:
        conn.rollback()
        logger.exception("unlink_match failed")
        raise HTTPException(500, "unlink failed")
    finally:
        cur.close()


@router.post("/expenses/{expense_id}/confirm-auto")
def confirm_auto_match(
    expense_id: str,
    conn: PgConnection = Depends(get_db),
):
    """자동 매칭 결과 그대로 확정 (is_confirmed=TRUE로만 변경)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE transaction_expenseone_match
               SET is_confirmed = TRUE, updated_at = NOW()
             WHERE expense_id = %s
         RETURNING id, transaction_id
            """,
            [expense_id],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "match not found")
        conn.commit()
        return {"ok": True, "match_id": row[0], "transaction_id": row[1]}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        logger.exception("confirm_auto_match failed")
        raise HTTPException(500, "confirm-auto failed")
    finally:
        cur.close()

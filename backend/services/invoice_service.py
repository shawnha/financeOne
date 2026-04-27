"""invoice_service — 발생주의 레이어 (P2).

invoices (세금계산서/청구서) ↔ transactions (실제 입출금) 매칭 + 자동 매칭 helper.

비즈니스 규칙:
- invoice.total = invoice.amount + invoice.vat (저장 시 검증).
- invoice.status: open(미결제) / partial(부분결제) / paid(완납) / cancelled(취소).
- paid_total = SUM(invoice_payments.amount) ≤ invoice.total.
- direction='sales': transactions.type='in' 과 매칭 (받을 돈).
- direction='purchase': transactions.type='out' 과 매칭 (줄 돈).

자동 매칭 우선순위:
1. 정확 일치: counterparty + total + due_date 부근 (±7일)
2. 거래처 + 금액 일치 (날짜 무관, 부분결제 후보)
3. 미매칭 — 수동 매칭 유도

P2: 발생주의 정합성. Phase 3 연결재무제표 + K-GAAP 매출/매입 인식 시점 기초.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from psycopg2.extensions import connection as PgConnection

from backend.utils.db import fetch_all


def _quantize(amount) -> Decimal:
    return Decimal(str(amount)).quantize(Decimal("0.01"))


def create_invoice(
    conn: PgConnection,
    *,
    entity_id: int,
    direction: str,  # 'sales' | 'purchase'
    counterparty: str,
    issue_date: date,
    amount: Decimal,
    vat: Decimal = Decimal("0"),
    total: Optional[Decimal] = None,
    due_date: Optional[date] = None,
    document_no: Optional[str] = None,
    description: Optional[str] = None,
    counterparty_biz_no: Optional[str] = None,
    currency: str = "KRW",
    internal_account_id: Optional[int] = None,
    standard_account_id: Optional[int] = None,
    note: Optional[str] = None,
    raw_data: Optional[dict] = None,
) -> int:
    """invoice INSERT. total NULL 이면 amount + vat 자동 계산."""
    if direction not in ("sales", "purchase"):
        raise ValueError(f"invalid direction: {direction}")

    amount_q = _quantize(amount)
    vat_q = _quantize(vat)
    total_q = _quantize(total) if total is not None else (amount_q + vat_q)
    if total_q != (amount_q + vat_q):
        raise ValueError(f"total({total_q}) != amount({amount_q}) + vat({vat_q})")

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO invoices (
            entity_id, direction, counterparty, counterparty_biz_no,
            issue_date, due_date, document_no, description,
            amount, vat, total, currency,
            internal_account_id, standard_account_id, status, note, raw_data
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
        RETURNING id
        """,
        [
            entity_id, direction, counterparty, counterparty_biz_no,
            issue_date, due_date, document_no, description,
            float(amount_q), float(vat_q), float(total_q), currency,
            internal_account_id, standard_account_id, note,
            None if raw_data is None else __import__("json").dumps(raw_data, ensure_ascii=False),
        ],
    )
    invoice_id = cur.fetchone()[0]
    cur.close()
    return invoice_id


def get_invoice(conn: PgConnection, invoice_id: int) -> Optional[dict]:
    """invoice + 매칭된 payments 합계."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT i.id, i.entity_id, i.direction, i.counterparty, i.counterparty_biz_no,
               i.issue_date, i.due_date, i.document_no, i.description,
               i.amount, i.vat, i.total, i.currency,
               i.internal_account_id, i.standard_account_id, i.status, i.note,
               COALESCE((SELECT SUM(p.amount) FROM invoice_payments p
                         WHERE p.invoice_id = i.id), 0) AS paid_amount,
               i.created_at, i.updated_at
        FROM invoices i
        WHERE i.id = %s
        """,
        [invoice_id],
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    cols = [
        "id", "entity_id", "direction", "counterparty", "counterparty_biz_no",
        "issue_date", "due_date", "document_no", "description",
        "amount", "vat", "total", "currency",
        "internal_account_id", "standard_account_id", "status", "note",
        "paid_amount", "created_at", "updated_at",
    ]
    result = dict(zip(cols, row))
    paid = Decimal(str(result["paid_amount"]))
    total = Decimal(str(result["total"]))
    result["outstanding"] = float(total - paid)
    return result


def list_invoices(
    conn: PgConnection,
    *,
    entity_id: int,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    counterparty: Optional[str] = None,
    issue_date_from: Optional[date] = None,
    issue_date_to: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """invoice 리스트 + 매칭 합계."""
    where = ["i.entity_id = %s"]
    params: list = [entity_id]
    if direction:
        where.append("i.direction = %s")
        params.append(direction)
    if status:
        where.append("i.status = %s")
        params.append(status)
    if counterparty:
        where.append("i.counterparty ILIKE %s")
        params.append(f"%{counterparty}%")
    if issue_date_from:
        where.append("i.issue_date >= %s")
        params.append(issue_date_from)
    if issue_date_to:
        where.append("i.issue_date <= %s")
        params.append(issue_date_to)

    where_sql = " AND ".join(where)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT i.id, i.entity_id, i.direction, i.counterparty,
               i.issue_date, i.due_date, i.document_no, i.description,
               i.amount, i.vat, i.total, i.currency,
               i.internal_account_id, i.standard_account_id, i.status,
               COALESCE((SELECT SUM(p.amount) FROM invoice_payments p
                         WHERE p.invoice_id = i.id), 0) AS paid_amount,
               i.created_at
        FROM invoices i
        WHERE {where_sql}
        ORDER BY i.issue_date DESC, i.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [limit, offset],
    )
    rows = fetch_all(cur)
    cur.close()
    for r in rows:
        paid = Decimal(str(r.get("paid_amount") or 0))
        total = Decimal(str(r["total"]))
        r["outstanding"] = float(total - paid)
    return rows


def update_invoice_status(conn: PgConnection, invoice_id: int) -> str:
    """invoice_payments 합계 기반으로 status 자동 갱신.

    - cancelled 상태는 손대지 않음 (수동 cancel 보존).
    - paid_total = 0 → open
    - 0 < paid_total < total → partial
    - paid_total >= total → paid
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT i.status, i.total,
               COALESCE((SELECT SUM(p.amount) FROM invoice_payments p
                         WHERE p.invoice_id = i.id), 0)
        FROM invoices i WHERE i.id = %s
        """,
        [invoice_id],
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise ValueError(f"invoice {invoice_id} not found")
    current_status, total, paid = row
    if current_status == "cancelled":
        cur.close()
        return current_status

    total_d = Decimal(str(total))
    paid_d = Decimal(str(paid))
    if paid_d <= 0:
        new_status = "open"
    elif paid_d < total_d:
        new_status = "partial"
    else:
        new_status = "paid"

    if new_status != current_status:
        cur.execute(
            "UPDATE invoices SET status = %s, updated_at = NOW() WHERE id = %s",
            [new_status, invoice_id],
        )
    cur.close()
    return new_status


def match_invoice_payment(
    conn: PgConnection,
    *,
    invoice_id: int,
    transaction_id: int,
    amount: Optional[Decimal] = None,
    matched_by: str = "manual",
    note: Optional[str] = None,
) -> int:
    """invoice ↔ transaction 매칭.

    amount 미지정 시: invoice 미결제 잔액과 transaction 금액 중 작은 값 사용.
    분할결제(여러 transaction 매칭) 가능. 같은 invoice + transaction 쌍은 UNIQUE.

    direction 검증: sales → tx.type='in', purchase → tx.type='out'.

    Returns: invoice_payment.id
    """
    if matched_by not in ("manual", "auto", "rule"):
        raise ValueError(f"invalid matched_by: {matched_by}")

    cur = conn.cursor()
    cur.execute(
        "SELECT direction, total, entity_id, status FROM invoices WHERE id = %s",
        [invoice_id],
    )
    inv = cur.fetchone()
    if not inv:
        cur.close()
        raise ValueError(f"invoice {invoice_id} not found")
    direction, inv_total, inv_entity, inv_status = inv
    if inv_status == "cancelled":
        cur.close()
        raise ValueError(f"invoice {invoice_id} is cancelled — cannot match")

    cur.execute(
        "SELECT type, amount, entity_id, is_cancel FROM transactions WHERE id = %s",
        [transaction_id],
    )
    tx = cur.fetchone()
    if not tx:
        cur.close()
        raise ValueError(f"transaction {transaction_id} not found")
    tx_type, tx_amount, tx_entity, tx_is_cancel = tx
    if tx_is_cancel:
        cur.close()
        raise ValueError(f"transaction {transaction_id} is cancelled")

    if inv_entity != tx_entity:
        cur.close()
        raise ValueError(f"entity mismatch: invoice {inv_entity} != transaction {tx_entity}")

    expected_tx_type = "in" if direction == "sales" else "out"
    if tx_type != expected_tx_type:
        cur.close()
        raise ValueError(
            f"direction mismatch: invoice={direction} requires tx.type={expected_tx_type}, "
            f"got tx.type={tx_type}"
        )

    cur.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM invoice_payments WHERE invoice_id = %s",
        [invoice_id],
    )
    paid_so_far = Decimal(str(cur.fetchone()[0]))
    outstanding = Decimal(str(inv_total)) - paid_so_far

    tx_amount_d = Decimal(str(tx_amount))
    if amount is None:
        match_amount = min(outstanding, tx_amount_d)
    else:
        match_amount = _quantize(amount)
    if match_amount <= 0:
        cur.close()
        raise ValueError(f"match amount must be > 0, got {match_amount}")
    if match_amount > outstanding + Decimal("0.01"):  # rounding tolerance
        cur.close()
        raise ValueError(
            f"match amount {match_amount} exceeds outstanding {outstanding}"
        )

    cur.execute(
        """
        INSERT INTO invoice_payments (invoice_id, transaction_id, amount, matched_by, note)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        [invoice_id, transaction_id, float(match_amount), matched_by, note],
    )
    payment_id = cur.fetchone()[0]
    cur.close()
    update_invoice_status(conn, invoice_id)
    return payment_id


def unmatch_invoice_payment(conn: PgConnection, payment_id: int) -> None:
    """매칭 해제 + invoice status 재계산."""
    cur = conn.cursor()
    cur.execute("SELECT invoice_id FROM invoice_payments WHERE id = %s", [payment_id])
    row = cur.fetchone()
    if not row:
        cur.close()
        raise ValueError(f"invoice_payment {payment_id} not found")
    invoice_id = row[0]
    cur.execute("DELETE FROM invoice_payments WHERE id = %s", [payment_id])
    cur.close()
    update_invoice_status(conn, invoice_id)


def auto_match_candidates(
    conn: PgConnection,
    *,
    entity_id: int,
    days_window: int = 7,
    limit: int = 50,
) -> list[dict]:
    """미결제 invoice ↔ 미매칭 transaction 자동 매칭 후보 제안 (실행은 안 함).

    매칭 규칙:
    - direction 일치 (sales↔in, purchase↔out)
    - counterparty 일치 (ILIKE)
    - amount 일치 (invoice.outstanding == transaction.amount)
    - tx.date in [invoice.issue_date - days_window, invoice.due_date + days_window]

    Returns: [{invoice_id, transaction_id, amount, score, reason}, ...]
    """
    cur = conn.cursor()
    cur.execute(
        """
        WITH outstanding_invoices AS (
            SELECT i.id, i.direction, i.counterparty, i.issue_date, i.due_date,
                   i.total - COALESCE((SELECT SUM(p.amount) FROM invoice_payments p
                                       WHERE p.invoice_id = i.id), 0) AS outstanding
            FROM invoices i
            WHERE i.entity_id = %s AND i.status IN ('open', 'partial')
        ),
        unmatched_txs AS (
            SELECT t.id, t.type, t.counterparty, t.date, t.amount
            FROM transactions t
            WHERE t.entity_id = %s
              AND t.is_duplicate = false
              AND (t.is_cancel IS NOT TRUE)
              AND t.id NOT IN (SELECT transaction_id FROM invoice_payments)
        )
        SELECT inv.id AS invoice_id, tx.id AS transaction_id,
               LEAST(inv.outstanding, tx.amount) AS match_amount,
               inv.counterparty AS inv_party, tx.counterparty AS tx_party,
               inv.issue_date, COALESCE(inv.due_date, inv.issue_date) AS due_date,
               tx.date AS tx_date, inv.outstanding, tx.amount
        FROM outstanding_invoices inv
        JOIN unmatched_txs tx ON
             (inv.direction = 'sales'    AND tx.type = 'in')
          OR (inv.direction = 'purchase' AND tx.type = 'out')
        WHERE tx.counterparty ILIKE '%%' || inv.counterparty || '%%'
              OR inv.counterparty ILIKE '%%' || tx.counterparty || '%%'
        ORDER BY inv.issue_date DESC
        LIMIT %s
        """,
        [entity_id, entity_id, limit * 5],
    )
    rows = cur.fetchall()
    cur.close()

    candidates = []
    window = timedelta(days=days_window)
    for r in rows:
        inv_id, tx_id, match_amt, inv_party, tx_party, issue, due, tx_date, outstanding, tx_amt = r
        # 일자 범위 검증
        if tx_date < issue - window:
            continue
        if tx_date > due + window:
            continue
        # score: 0~100. 금액 정확 일치 + 일자 가까울수록 높음.
        amount_match = (Decimal(str(outstanding)) == Decimal(str(tx_amt)))
        date_diff = abs((tx_date - due).days)
        score = (60 if amount_match else 30) + max(0, 30 - date_diff)
        reason = []
        if amount_match:
            reason.append("amount=outstanding")
        else:
            reason.append("partial")
        reason.append(f"date_diff={date_diff}d")
        candidates.append({
            "invoice_id": inv_id,
            "transaction_id": tx_id,
            "amount": float(match_amt),
            "score": int(score),
            "reason": ", ".join(reason),
            "invoice_counterparty": inv_party,
            "transaction_counterparty": tx_party,
            "invoice_outstanding": float(outstanding),
            "transaction_amount": float(tx_amt),
            "tx_date": str(tx_date),
            "due_date": str(due),
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:limit]


def cancel_invoice(conn: PgConnection, invoice_id: int, note: Optional[str] = None) -> None:
    """invoice 취소 — 매칭된 payment 모두 해제 후 status='cancelled'."""
    cur = conn.cursor()
    cur.execute("DELETE FROM invoice_payments WHERE invoice_id = %s", [invoice_id])
    cur.execute(
        """
        UPDATE invoices
        SET status = 'cancelled',
            note = COALESCE(note, '') || CASE WHEN %s IS NOT NULL THEN E'\n[cancel] ' || %s ELSE '' END,
            updated_at = NOW()
        WHERE id = %s
        """,
        [note, note, invoice_id],
    )
    if cur.rowcount == 0:
        cur.close()
        raise ValueError(f"invoice {invoice_id} not found")
    cur.close()

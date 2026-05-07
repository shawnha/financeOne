"""Invoices API — 발생주의 레이어 (P2).

- POST   /api/invoices              — invoice 생성
- GET    /api/invoices               — 리스트 (filter: direction/status/counterparty/date)
- GET    /api/invoices/{id}          — 단건 + 매칭 합계
- PATCH  /api/invoices/{id}          — 수정 (cancelled invoice 는 거부)
- POST   /api/invoices/{id}/cancel   — invoice 취소 (매칭 자동 해제)
- DELETE /api/invoices/{id}          — 삭제 (cascade 매칭 행)
- POST   /api/invoices/{id}/payments — invoice ↔ transaction 매칭
- DELETE /api/invoice-payments/{id}  — 매칭 해제
- GET    /api/invoices/auto-match    — 자동 매칭 후보 조회 (실행은 안 함)
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from psycopg2.extensions import connection as PgConnection
from pydantic import BaseModel, Field

from backend.database.connection import get_db
from backend.services.invoice_service import (
    accrual_monthly_summary,
    auto_match_candidates,
    cancel_invoice,
    counterparty_balances,
    create_invoice,
    get_invoice,
    list_invoices,
    match_invoice_payment,
    unmatch_invoice_payment,
    update_invoice_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["invoices"])


# ── Schemas ────────────────────────────────────────────────────────────


class InvoiceCreate(BaseModel):
    entity_id: int
    direction: str = Field(..., pattern="^(sales|purchase)$")
    counterparty: str
    issue_date: date
    amount: Decimal
    vat: Decimal = Decimal("0")
    total: Optional[Decimal] = None
    due_date: Optional[date] = None
    document_no: Optional[str] = None
    description: Optional[str] = None
    counterparty_biz_no: Optional[str] = None
    currency: str = "KRW"
    internal_account_id: Optional[int] = None
    standard_account_id: Optional[int] = None
    note: Optional[str] = None


class InvoiceUpdate(BaseModel):
    counterparty: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    document_no: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    vat: Optional[Decimal] = None
    total: Optional[Decimal] = None
    counterparty_biz_no: Optional[str] = None
    internal_account_id: Optional[int] = None
    standard_account_id: Optional[int] = None
    note: Optional[str] = None


class PaymentCreate(BaseModel):
    transaction_id: int
    amount: Optional[Decimal] = None
    matched_by: str = Field(default="manual", pattern="^(manual|auto|rule)$")
    note: Optional[str] = None


class CancelRequest(BaseModel):
    note: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/invoices", status_code=201)
def post_invoice(body: InvoiceCreate, conn: PgConnection = Depends(get_db)):
    try:
        invoice_id = create_invoice(
            conn,
            entity_id=body.entity_id,
            direction=body.direction,
            counterparty=body.counterparty,
            issue_date=body.issue_date,
            amount=body.amount,
            vat=body.vat,
            total=body.total,
            due_date=body.due_date,
            document_no=body.document_no,
            description=body.description,
            counterparty_biz_no=body.counterparty_biz_no,
            currency=body.currency,
            internal_account_id=body.internal_account_id,
            standard_account_id=body.standard_account_id,
            note=body.note,
        )
        conn.commit()
        return get_invoice(conn, invoice_id)
    except ValueError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    except Exception:
        conn.rollback()
        logger.exception("create_invoice failed")
        raise HTTPException(500, "내부 오류")


@router.get("/invoices")
def get_invoices(
    entity_id: int = Query(...),
    direction: Optional[str] = Query(None, pattern="^(sales|purchase)$"),
    status: Optional[str] = Query(None, pattern="^(open|partial|paid|cancelled)$"),
    counterparty: Optional[str] = Query(None),
    issue_date_from: Optional[date] = Query(None),
    issue_date_to: Optional[date] = Query(None),
    source_kind: Optional[str] = Query(
        None,
        pattern="^(tax_invoice|platform_sales|manual)$",
        description="tax_invoice: 홈택스 통합조회 / platform_sales: NAVER 등 / manual: 수동",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: PgConnection = Depends(get_db),
):
    try:
        items = list_invoices(
            conn,
            entity_id=entity_id,
            direction=direction,
            status=status,
            counterparty=counterparty,
            issue_date_from=issue_date_from,
            issue_date_to=issue_date_to,
            source_kind=source_kind,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "count": len(items)}
    except Exception:
        logger.exception("list_invoices failed")
        raise HTTPException(500, "내부 오류")


@router.get("/invoices/accrual-summary")
def get_accrual_summary(
    entity_id: int = Query(...),
    months: int = Query(12, ge=1, le=36),
    conn: PgConnection = Depends(get_db),
):
    """월별 발생주의 매출/매입 (issue_date 기준, cancelled 제외)."""
    try:
        return accrual_monthly_summary(conn, entity_id=entity_id, months=months)
    except Exception:
        logger.exception("accrual_monthly_summary failed")
        raise HTTPException(500, "내부 오류")


@router.get("/invoices/counterparty-balances")
def get_counterparty_balances(
    entity_id: int = Query(...),
    direction: Optional[str] = Query(None, pattern="^(sales|purchase)$"),
    only_outstanding: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    conn: PgConnection = Depends(get_db),
):
    """거래처별 미수금/미지급금 잔액."""
    try:
        return {
            "items": counterparty_balances(
                conn, entity_id=entity_id,
                direction=direction, only_outstanding=only_outstanding, limit=limit,
            ),
        }
    except Exception:
        logger.exception("counterparty_balances failed")
        raise HTTPException(500, "내부 오류")


@router.get("/invoices/auto-match")
def get_auto_match_candidates(
    entity_id: int = Query(...),
    days_window: int = Query(7, ge=0, le=60),
    limit: int = Query(50, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    try:
        return {
            "candidates": auto_match_candidates(
                conn, entity_id=entity_id, days_window=days_window, limit=limit,
            )
        }
    except Exception:
        logger.exception("auto_match_candidates failed")
        raise HTTPException(500, "내부 오류")


@router.post("/invoices/auto-map")
def auto_map_invoices(
    entity_id: int = Query(...),
    direction: Optional[str] = Query(None, pattern="^(purchase|sales)$"),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    only_unmapped: bool = Query(True, description="True 면 standard_account_id IS NULL 만 갱신."),
    enable_ai: bool = Query(False),
    conn: PgConnection = Depends(get_db),
):
    """invoices 의 standard_account_id 자동 매핑.

    transactions 와 동일한 mapping_service 룰 사용 (counterparty + description 기반).
    options-B (VAT 정합) 분석 위해 매입 세금계산서 표준계정 매핑이 선행 작업.
    """
    from backend.services.mapping_service import auto_map_transaction

    cur = conn.cursor()
    try:
        cur.execute("SET search_path TO financeone, public")
        clauses = ["entity_id = %s"]
        params: list = [entity_id]
        if direction:
            clauses.append("direction = %s")
            params.append(direction)
        if year and month:
            clauses.append("issue_date >= %s AND issue_date < %s")
            params.append(f"{year}-{month:02d}-01")
            next_month = month + 1
            next_year = year
            if next_month > 12:
                next_month = 1
                next_year = year + 1
            params.append(f"{next_year}-{next_month:02d}-01")
        if only_unmapped:
            clauses.append("standard_account_id IS NULL")
        where = " AND ".join(clauses)

        cur.execute(
            f"""
            SELECT id, counterparty, description, standard_account_id, direction
            FROM invoices
            WHERE {where}
            ORDER BY issue_date, id
            """,
            params,
        )
        targets = cur.fetchall()

        new_mapped = 0
        updated = 0
        skipped_no_match = 0
        mapped_ids = []
        examples = []
        for inv_id, counterparty, description, current_sa, inv_direction in targets:
            mapping = auto_map_transaction(
                cur, entity_id=entity_id,
                counterparty=counterparty,
                description=description,
                enable_ai=enable_ai,
                direction=inv_direction,  # 'sales' or 'purchase'
            )
            if not mapping or not mapping.get("standard_account_id"):
                skipped_no_match += 1
                continue
            new_sa = mapping["standard_account_id"]
            if new_sa == current_sa:
                continue
            cur.execute(
                """
                UPDATE invoices
                SET standard_account_id = %s, updated_at = NOW()
                WHERE id = %s
                """,
                [new_sa, inv_id],
            )
            if current_sa is None:
                new_mapped += 1
            else:
                updated += 1
            mapped_ids.append(inv_id)
            if len(examples) < 10:
                examples.append({
                    "invoice_id": inv_id,
                    "counterparty": counterparty,
                    "standard_account_id": new_sa,
                    "confidence": float(mapping.get("confidence", 0)),
                    "match_type": mapping.get("match_type"),
                })

        conn.commit()
        cur.close()
        return {
            "total_targets": len(targets),
            "new_mapped": new_mapped,
            "updated": updated,
            "skipped_no_match": skipped_no_match,
            "mapped_ids": mapped_ids,
            "examples": examples,
        }
    except Exception:
        conn.rollback()
        logger.exception("invoices auto-map failed")
        raise


@router.get("/invoices/{invoice_id}")
def get_invoice_endpoint(invoice_id: int, conn: PgConnection = Depends(get_db)):
    inv = get_invoice(conn, invoice_id)
    if not inv:
        raise HTTPException(404, f"invoice {invoice_id} not found")
    return inv


@router.patch("/invoices/{invoice_id}")
def patch_invoice(invoice_id: int, body: InvoiceUpdate, conn: PgConnection = Depends(get_db)):
    inv = get_invoice(conn, invoice_id)
    if not inv:
        raise HTTPException(404, "invoice not found")
    if inv["status"] == "cancelled":
        raise HTTPException(400, "cancelled invoice cannot be modified")

    fields = body.model_dump(exclude_none=True)
    if not fields:
        return inv

    # total 일관성 검증
    new_amount = fields.get("amount", inv["amount"])
    new_vat = fields.get("vat", inv["vat"])
    new_total = fields.get("total")
    if new_total is None and ("amount" in fields or "vat" in fields):
        new_total = Decimal(str(new_amount)) + Decimal(str(new_vat))
        fields["total"] = new_total
    if new_total is not None:
        if Decimal(str(new_total)) != Decimal(str(new_amount)) + Decimal(str(new_vat)):
            raise HTTPException(400, "total != amount + vat")

    # PATCH 동적 SQL
    set_parts = []
    params: list = []
    for k, v in fields.items():
        if isinstance(v, Decimal):
            v = float(v)
        set_parts.append(f"{k} = %s")
        params.append(v)
    set_parts.append("updated_at = NOW()")
    params.append(invoice_id)

    cur = conn.cursor()
    try:
        cur.execute(
            f"UPDATE invoices SET {', '.join(set_parts)} WHERE id = %s",
            params,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("patch_invoice failed")
        raise HTTPException(500, "내부 오류")
    finally:
        cur.close()
    return get_invoice(conn, invoice_id)


@router.post("/invoices/{invoice_id}/cancel")
def post_cancel_invoice(invoice_id: int, body: CancelRequest, conn: PgConnection = Depends(get_db)):
    try:
        cancel_invoice(conn, invoice_id, note=body.note)
        conn.commit()
        return get_invoice(conn, invoice_id)
    except ValueError as e:
        conn.rollback()
        raise HTTPException(404, str(e))
    except Exception:
        conn.rollback()
        logger.exception("cancel_invoice failed")
        raise HTTPException(500, "내부 오류")


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int, conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM invoices WHERE id = %s", [invoice_id])
        if cur.rowcount == 0:
            raise HTTPException(404, "invoice not found")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        logger.exception("delete_invoice failed")
        raise HTTPException(500, "내부 오류")
    finally:
        cur.close()


@router.post("/invoices/{invoice_id}/payments", status_code=201)
def post_payment(invoice_id: int, body: PaymentCreate, conn: PgConnection = Depends(get_db)):
    try:
        payment_id = match_invoice_payment(
            conn,
            invoice_id=invoice_id,
            transaction_id=body.transaction_id,
            amount=body.amount,
            matched_by=body.matched_by,
            note=body.note,
        )
        conn.commit()
        return {"payment_id": payment_id, "invoice": get_invoice(conn, invoice_id)}
    except ValueError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    except Exception:
        conn.rollback()
        logger.exception("match_invoice_payment failed")
        raise HTTPException(500, "내부 오류")


@router.delete("/invoice-payments/{payment_id}", status_code=204)
def delete_payment(payment_id: int, conn: PgConnection = Depends(get_db)):
    try:
        unmatch_invoice_payment(conn, payment_id)
        conn.commit()
    except ValueError as e:
        conn.rollback()
        raise HTTPException(404, str(e))
    except Exception:
        conn.rollback()
        logger.exception("unmatch_invoice_payment failed")
        raise HTTPException(500, "내부 오류")


# ── Excel import ──────────────────────────────────────────────────


@router.post("/invoices/import")
async def import_invoices_excel(
    entity_id: int = Form(...),
    our_biz_no: Optional[str] = Form(None),
    dry_run: bool = Form(True),
    skip_unknown_direction: bool = Form(True),
    file: UploadFile = File(...),
    conn: PgConnection = Depends(get_db),
):
    """세금계산서 Excel 일괄 업로드.

    - dry_run=True (기본): 파싱만 하고 INSERT 안 함 — 미리보기.
    - dry_run=False: 중복(document_no 일치) 제외하고 INSERT.
    - skip_unknown_direction=True: direction='unknown' 행 (our_biz_no 와 매칭 안 되는
      행) skip. False 면 unknown 그대로 INSERT (사용자가 수동 결정 필요).

    Returns:
        {parsed, inserted, duplicates, skipped, errors, stats, column_map}
    """
    from backend.services.parsers.invoice_excel import parse_invoice_excel
    import json as _json

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "빈 파일")

    try:
        result = parse_invoice_excel(file_bytes, file.filename or "invoice.xlsx", our_biz_no=our_biz_no)
    except Exception as e:
        logger.exception("invoice excel parse failed")
        raise HTTPException(400, f"파싱 실패: {type(e).__name__}: {e}")

    parsed = result["parsed"]
    errors = result["errors"]
    inserted = 0
    duplicates = 0
    skipped = 0

    if not dry_run:
        cur = conn.cursor()
        try:
            for inv in parsed:
                if inv["direction"] == "unknown" and skip_unknown_direction:
                    skipped += 1
                    continue
                # 중복 감지 (entity_id + document_no + issue_date)
                if inv.get("document_no"):
                    cur.execute(
                        """
                        SELECT id FROM invoices
                        WHERE entity_id = %s AND document_no = %s AND issue_date = %s
                        LIMIT 1
                        """,
                        [entity_id, inv["document_no"], inv["issue_date"]],
                    )
                    if cur.fetchone():
                        duplicates += 1
                        continue
                cur.execute(
                    """
                    INSERT INTO invoices (
                        entity_id, direction, counterparty, counterparty_biz_no,
                        issue_date, due_date, document_no,
                        amount, vat, total, currency,
                        description, status, raw_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'KRW', %s, 'open', %s)
                    """,
                    [
                        entity_id, inv["direction"], inv["counterparty"], inv["counterparty_biz_no"],
                        inv["issue_date"], inv["due_date"], inv["document_no"],
                        inv["amount"], inv["vat"], inv["total"],
                        inv["description"],
                        _json.dumps(inv["raw"], ensure_ascii=False),
                    ],
                )
                inserted += 1
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("invoice excel insert failed")
            raise HTTPException(500, "INSERT 실패")
        finally:
            cur.close()

    return {
        "dry_run": dry_run,
        "parsed": parsed if dry_run else [],  # dry_run 미리보기에서만 전체 행 반환
        "preview": parsed[:10] if not dry_run else [],
        "inserted": inserted,
        "duplicates": duplicates,
        "skipped": skipped,
        "errors": errors,
        "stats": result["stats"],
        "column_map": result["column_map"],
        "header_row": result["header_row"],
    }

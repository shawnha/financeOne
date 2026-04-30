"""SalesOne 통합 — salesone.orders → financeone.invoices 자동 동기화 (P3-8).

같은 Supabase 프로젝트의 salesone 스키마를 cross-schema query 로 직접 조회.
ExpenseOne 통합과 동일 패턴 (project_expenseone_integration.md).

매출 인식 시점 (K-GAAP 발생주의):
- NAVER 등 플랫폼: 구매확정일 (productOrder.decisionDate) — orders.delivered_at 또는 raw_data.
  미구매확정 주문은 invoice 생성 X (취소 가능성).
- SHOPIFY/AMAZON 등 글로벌: orders.order_date (보수적, 추후 정밀화).

수수료 처리:
- NAVER: paymentCommission + knowledgeShoppingSellingInterlockCommission 등.
  → invoice.amount = totalPaymentAmount, 정산 시점 분개로 별도 (지급수수료) 인식.

회사 매핑: settings.salesone_company_id 키 (entity_id 별).

중복 감지: invoices.note 에 'salesone:order_id' 마커. 같은 order_id 는 INSERT skip.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)


def get_salesone_company_id(conn: PgConnection, entity_id: int) -> Optional[str]:
    """settings.salesone_company_id 조회 — entity_id ↔ salesone.company_id 매핑."""
    cur = conn.cursor()
    cur.execute(
        "SELECT value FROM financeone.settings WHERE entity_id = %s AND key = 'salesone_company_id'",
        [entity_id],
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def _decision_date(raw_data: dict | str | None) -> Optional[date]:
    """NAVER raw_data 의 decisionDate (구매확정일) → date.

    decisionDate 없으면 None — 매출 인식 보류.
    """
    if not raw_data:
        return None
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            return None
    if not isinstance(raw_data, dict):
        return None
    po = raw_data.get("productOrder", {})
    if not isinstance(po, dict):
        return None
    dd = po.get("decisionDate")
    if not dd:
        return None
    try:
        # ISO format with timezone (e.g., 2026-01-07T15:40:53.398+09:00)
        return datetime.fromisoformat(dd).date()
    except (ValueError, TypeError):
        return None


def _is_taxation(raw_data: dict | str | None) -> bool:
    """NAVER raw_data.productOrder.taxType == 'TAXATION' (부가세 과세)."""
    if not raw_data:
        return False
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            return False
    if not isinstance(raw_data, dict):
        return False
    po = raw_data.get("productOrder", {})
    if not isinstance(po, dict):
        return False
    return po.get("taxType") == "TAXATION"


def _split_vat(total: Decimal, taxation: bool) -> tuple[Decimal, Decimal]:
    """부가세 과세건이면 total = supply * 1.1 → 공급가액/부가세 분리.

    Returns: (supply_amount, vat). round to 0 decimal (원 단위).
    """
    if not taxation or total <= 0:
        return (total, Decimal("0"))
    # supply = total / 1.1, vat = total - supply (반올림 차이는 vat 에 흡수)
    supply = (total / Decimal("1.1")).quantize(Decimal("1"))
    vat = total - supply
    return (supply, vat)


def _expected_settlement(raw_data: dict | str | None) -> tuple[Decimal, Decimal]:
    """NAVER raw_data → (expectedSettlementAmount, totalCommission).

    Returns: (settle_amount, commission_amount). 못 구하면 (0, 0).
    """
    if not raw_data:
        return (Decimal("0"), Decimal("0"))
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            return (Decimal("0"), Decimal("0"))
    if not isinstance(raw_data, dict):
        return (Decimal("0"), Decimal("0"))
    po = raw_data.get("productOrder", {})
    if not isinstance(po, dict):
        return (Decimal("0"), Decimal("0"))
    settle = Decimal(str(po.get("expectedSettlementAmount") or 0))
    pay_comm = Decimal(str(po.get("paymentCommission") or 0))
    know_comm = Decimal(str(po.get("knowledgeShoppingSellingInterlockCommission") or 0))
    sale_comm = Decimal(str(po.get("saleCommission") or 0))
    chan_comm = Decimal(str(po.get("channelCommission") or 0))
    total_comm = pay_comm + know_comm + sale_comm + chan_comm
    return (settle, total_comm)


def fetch_orders(
    conn: PgConnection,
    *,
    company_id: str,
    start_date: date,
    end_date: date,
    platforms: Optional[list[str]] = None,
) -> list[dict]:
    """salesone.orders + external_orders.raw_data 조회 (cross-schema)."""
    cur = conn.cursor()
    where = ["o.company_id = %s",
             "o.order_date >= %s",
             "o.order_date < %s + INTERVAL '1 day'"]
    params: list = [company_id, start_date, end_date]
    if platforms:
        where.append("o.external_source = ANY(%s)")
        params.append(platforms)
    cur.execute(
        f"""
        SELECT o.id, o.order_number, o.external_order_number, o.external_source,
               o.order_date, o.delivered_at,
               o.total_amount, o.net_amount, o.refund_amount,
               o.settlement_amount, o.commission_amount,
               o.financial_status, o.fulfillment_status,
               o.recipient_name,
               eo.raw_data
        FROM salesone.orders o
        LEFT JOIN salesone.external_orders eo ON eo.mapped_order_id = o.id
        WHERE {' AND '.join(where)}
        ORDER BY o.order_date
        """,
        params,
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def sync_orders_to_invoices(
    conn: PgConnection,
    *,
    entity_id: int,
    start_date: date,
    end_date: date,
    platforms: Optional[list[str]] = None,
    sales_std_code: str = "40100",  # 상품매출
    skip_existing_naver: bool = True,
    dry_run: bool = True,
) -> dict:
    """salesone.orders → financeone.invoices INSERT.

    NAVER 의 경우 raw_data.decisionDate(구매확정일) 가 있는 주문만 invoice 생성.
    issue_date = decisionDate (없으면 order_date fallback).
    invoice.amount = order.total_amount (totalPaymentAmount).
    invoice.note 에 'salesone:<order_id>' 마커 — 중복 방지.

    skip_existing_naver=True (기본): 회계법인 원장에서 import 한 기존 NAVER invoices
    삭제 후 salesone source 로 재생성. 분개도 함께 정리.

    Returns: {fetched, created, skipped_dup, skipped_no_decision, deleted_old}
    """
    from backend.services.invoice_service import create_invoice, cancel_invoice

    company_id = get_salesone_company_id(conn, entity_id)
    if not company_id:
        raise RuntimeError(
            f"settings.salesone_company_id 미등록 (entity_id={entity_id})."
        )

    orders = fetch_orders(
        conn, company_id=company_id, start_date=start_date, end_date=end_date,
        platforms=platforms,
    )
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # standard_account_id lookup — K-GAAP (sales 통합은 한국 법인용)
    cur.execute(
        "SELECT id FROM standard_accounts WHERE code = %s AND gaap_type = 'K_GAAP'",
        [sales_std_code],
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise RuntimeError(f"standard_account {sales_std_code} 미존재")
    sales_acc_id = row[0]

    deleted_old = 0
    if not dry_run:
        # 회계법인 원장 import NAVER + 기존 salesone NAVER 모두 삭제 후 재생성.
        # P3-9a 부가세 분리 변경 반영을 위해 idempotent 재생성.
        if skip_existing_naver:
            cur.execute(
                """
                SELECT id, journal_entry_id FROM invoices
                WHERE entity_id = %s
                  AND issue_date BETWEEN %s AND %s
                  AND (counterparty ILIKE '%%네이버%%'
                       OR counterparty ILIKE 'NAVER%%'
                       OR note LIKE 'salesone:%%')
                """,
                [entity_id, start_date, end_date],
            )
            old_invs = cur.fetchall()
            for inv_id, je_id in old_invs:
                if je_id:
                    cur.execute("DELETE FROM journal_entry_lines WHERE journal_entry_id = %s", [je_id])
                    cur.execute("DELETE FROM journal_entries WHERE id = %s", [je_id])
                cur.execute("DELETE FROM invoice_payments WHERE invoice_id = %s", [inv_id])
                cur.execute("DELETE FROM invoices WHERE id = %s", [inv_id])
                deleted_old += 1
            conn.commit()

    created = 0
    skipped_dup = 0
    skipped_no_decision = 0

    for o in orders:
        order_id = o["id"]
        marker = f"salesone:{order_id}"

        # 중복 감지 (note marker)
        cur.execute(
            "SELECT id FROM invoices WHERE entity_id = %s AND note LIKE %s LIMIT 1",
            [entity_id, f"{marker}%"],
        )
        if cur.fetchone():
            skipped_dup += 1
            continue

        # 매출 인식일 = 구매확정일 (NAVER) 또는 order_date fallback
        decision = _decision_date(o.get("raw_data"))
        if o["external_source"] == "NAVER":
            if not decision:
                skipped_no_decision += 1
                continue
            issue_date = decision
        else:
            # SHOPIFY/AMAZON/TIKTOK 등 — 보수적으로 order_date 사용
            issue_date = o["order_date"].date() if o["order_date"] else None
            if not issue_date:
                skipped_no_decision += 1
                continue

        total = Decimal(str(o.get("total_amount") or 0))
        if total <= 0:
            # 0원 주문 (시딩 / 광고샘플 등) — invoice 생성 X
            skipped_no_decision += 1
            continue

        # P3-9a: 부가세 분리 (NAVER taxType=TAXATION 인 경우 1/11 분리)
        taxation = _is_taxation(o.get("raw_data"))
        supply, vat = _split_vat(total, taxation)

        counterparty = f"{o['external_source']} - {o.get('recipient_name') or order_id[:8]}"
        external_no = o.get("external_order_number") or o.get("order_number") or order_id

        if dry_run:
            created += 1
            continue

        try:
            create_invoice(
                conn,
                entity_id=entity_id,
                direction="sales",
                counterparty=counterparty[:200],
                issue_date=issue_date,
                amount=supply,  # 공급가액 (부가세 제외)
                vat=vat,         # 부가세 (TAXATION 이면 total/11, ELSE 0)
                total=total,
                document_no=external_no,
                description=f"{o['external_source']} order {external_no}",
                standard_account_id=sales_acc_id,
                note=f"{marker} | platform={o['external_source']}",
                raw_data={
                    "order_id": order_id,
                    "external_source": o["external_source"],
                    "settlement_amount": str(o.get("settlement_amount") or 0),
                    "commission_amount": str(o.get("commission_amount") or 0),
                    "refund_amount": str(o.get("refund_amount") or 0),
                },
            )
            created += 1
        except Exception as e:
            logger.warning("salesone order %s import failed: %s", order_id, e)

    if not dry_run:
        conn.commit()
    cur.close()

    return {
        "fetched": len(orders),
        "created": created,
        "skipped_dup": skipped_dup,
        "skipped_no_decision": skipped_no_decision,
        "deleted_old": deleted_old,
        "company_id": company_id,
        "period": f"{start_date}~{end_date}",
    }

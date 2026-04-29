"""HOI (US GAAP) 재무제표 — Intuit QBO Report API 활용.

QBO 의 BalanceSheet / ProfitAndLoss Report 를 그대로 가져와 line_items 로 변환.
QBO 가 직접 계산한 잔액 + hierarchy 그대로 → 25년 PDF 양식과 100% 일치.

Generator 흐름:
1. _load_tokens 로 OAuth tokens 조회
2. QBO Report API 호출 (Accrual basis)
3. recursive parse → flat list (depth 별 indent label)
4. statement_id 의 line_items 로 INSERT
"""
from __future__ import annotations

import logging
import os
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg2.extensions import connection as PgConnection

from backend.services.integrations.qbo import QBOClient, _load_tokens, QBOError

logger = logging.getLogger(__name__)


def _get_client() -> QBOClient:
    """QBO Production client (env-based)."""
    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID", "")
    client_secret = os.environ.get("QUICKBOOKS_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("QUICKBOOKS_REDIRECT_URI", "")
    if not client_id or not client_secret:
        raise QBOError("QuickBooks credentials not configured")
    return QBOClient(client_id, client_secret, redirect_uri or "https://example.com/cb")


def _fetch_report(
    conn: PgConnection,
    entity_id: int,
    report_type: str,
    params: dict[str, str],
) -> dict[str, Any]:
    """QBO Report API 호출 + token refresh 자동 처리."""
    realm_id, access_token, refresh_token = _load_tokens(conn, entity_id)

    client = _get_client()
    try:
        from urllib.parse import urlencode
        endpoint = f"reports/{report_type}?{urlencode(params)}"
        return client._request(
            "GET", endpoint, realm_id, access_token, refresh_token, conn, entity_id,
        )
    finally:
        client.close()


def _parse_amount(s: Any) -> Decimal:
    """ColData value → Decimal. 빈 문자열/None 은 0."""
    if s is None:
        return Decimal("0")
    s = str(s).strip().replace(",", "")
    if not s:
        return Decimal("0")
    # QBO 는 음수를 "-123.45" 또는 "(123.45)" 로 표기 가능
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _walk_rows(
    rows: list[dict],
    depth: int,
    items: list[dict],
    statement_type: str,
    order_ref: list[int],
    parent_path: str = "",
) -> None:
    """QBO Report rows 재귀 walk → flat line_items.

    QBO row types:
    - Section: Header(라벨) → Rows(자식들) → Summary(합계)
    - Data: ColData[label, amount]
    """
    for row in rows:
        row_type = row.get("type", "")
        col = row.get("ColData") or []

        if row_type == "Section":
            header = row.get("Header", {})
            header_cols = header.get("ColData", [])
            label = header_cols[0].get("value", "") if header_cols else ""
            # 일부 Section 은 Header 없이 Summary 만 있는 경우도 있음
            child_rows = row.get("Rows", {}).get("Row", [])
            summary = row.get("Summary", {})
            summary_cols = summary.get("ColData", [])
            summary_label = summary_cols[0].get("value", "") if summary_cols else ""
            summary_amount = _parse_amount(summary_cols[1].get("value") if len(summary_cols) > 1 else None)

            # Header 표시
            if label:
                indent = "  " * (depth + 1)
                items.append({
                    "statement_type": statement_type,
                    "line_key": _make_key(parent_path, label, "h", order_ref[0]),
                    "label": f"{indent}{label}",
                    "sort_order": order_ref[0],
                    "auto_amount": float(summary_amount) if not child_rows else 0,
                    "auto_debit": 0, "auto_credit": 0,
                    "is_section_header": True,
                })
                order_ref[0] += 10

            # 자식들 walk
            if child_rows:
                _walk_rows(child_rows, depth + 1, items, statement_type, order_ref, label)

            # Summary (합계) — 자식이 있을 때만
            if child_rows and summary_label:
                indent = "  " * (depth + 1)
                items.append({
                    "statement_type": statement_type,
                    "line_key": _make_key(parent_path, summary_label, "s", order_ref[0]),
                    "label": f"{indent}{summary_label}",
                    "sort_order": order_ref[0],
                    "auto_amount": float(summary_amount),
                    "auto_debit": 0, "auto_credit": 0,
                    "is_section_header": True,
                })
                order_ref[0] += 10

        elif row_type == "Data" and col:
            label = col[0].get("value", "") if col else ""
            amount = _parse_amount(col[1].get("value") if len(col) > 1 else None)
            indent = "  " * (depth + 2)  # data 행은 헤더보다 2단계 더 인덴트
            items.append({
                "statement_type": statement_type,
                "account_code": col[0].get("id"),  # QBO account id
                "line_key": _make_key(parent_path, label, "d", order_ref[0]),
                "label": f"{indent}{label}",
                "sort_order": order_ref[0],
                "auto_amount": float(amount),
                "auto_debit": 0, "auto_credit": 0,
                "is_section_header": False,
            })
            order_ref[0] += 10

        # 그 외 type (Empty, blank 등) 은 skip


def _make_key(parent: str, label: str, suffix: str, order: int) -> str:
    """unique line_key 생성."""
    base = (parent + "_" + label).strip("_").replace(" ", "_").replace(":", "")[:60]
    return f"{base}_{suffix}_{order}"


def fetch_qbo_balance_sheet(
    conn: PgConnection,
    entity_id: int,
    as_of_date: date,
) -> tuple[list[dict], dict]:
    """QBO BalanceSheet Report → line_items + 합계 dict."""
    report = _fetch_report(
        conn, entity_id, "BalanceSheet",
        {"accounting_method": "Accrual", "end_date": as_of_date.isoformat()},
    )
    rows = report.get("Rows", {}).get("Row", [])

    items: list[dict] = []
    order = [100]
    _walk_rows(rows, 0, items, "balance_sheet", order)

    # 합계 추출 — top-level Summary 들에서 Total Assets / Total Liab+Equity 찾기
    totals = {"total_assets": 0.0, "total_liabilities": 0.0, "total_equity": 0.0}
    for it in items:
        if "Total Assets" in it["label"]:
            totals["total_assets"] = it["auto_amount"]
        elif "Total Liabilities and Equity" in it["label"] or "Total Liabilities & Equity" in it["label"]:
            totals["liab_equity"] = it["auto_amount"]
        elif it["label"].strip() == "Total Liabilities":
            totals["total_liabilities"] = it["auto_amount"]
        elif it["label"].strip() == "Total Equity":
            totals["total_equity"] = it["auto_amount"]

    diff = totals["total_assets"] - (totals.get("liab_equity") or
                                     (totals["total_liabilities"] + totals["total_equity"]))
    totals["is_balanced"] = abs(diff) < 0.01
    totals["difference"] = diff
    totals["net_income"] = 0.0  # PL report 에서 채움

    return items, totals


def fetch_qbo_profit_loss(
    conn: PgConnection,
    entity_id: int,
    start_date: date,
    end_date: date,
) -> tuple[list[dict], dict]:
    """QBO ProfitAndLoss Report → line_items + 합계 dict."""
    report = _fetch_report(
        conn, entity_id, "ProfitAndLoss",
        {
            "accounting_method": "Accrual",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    rows = report.get("Rows", {}).get("Row", [])

    items: list[dict] = []
    order = [100]
    _walk_rows(rows, 0, items, "income_statement", order)

    totals = {
        "total_revenue": 0.0, "total_cogs": 0.0, "gross_profit": 0.0,
        "total_sga": 0.0, "operating_income": 0.0,
        "total_other_income": 0.0, "total_other_expense": 0.0,
        "income_before_tax": 0.0, "total_tax": 0.0, "net_income": 0.0,
    }
    for it in items:
        lbl = it["label"].strip()
        if lbl == "Total Income":
            totals["total_revenue"] = it["auto_amount"]
        elif lbl == "Total Cost of Goods Sold":
            totals["total_cogs"] = it["auto_amount"]
        elif lbl == "Gross Profit":
            totals["gross_profit"] = it["auto_amount"]
        elif lbl == "Total Expenses":
            totals["total_sga"] = it["auto_amount"]
        elif lbl == "Net Operating Income":
            totals["operating_income"] = it["auto_amount"]
        elif lbl == "Total Other Income":
            totals["total_other_income"] = it["auto_amount"]
        elif lbl == "Total Other Expenses":
            totals["total_other_expense"] = it["auto_amount"]
        elif lbl == "Net Other Income":
            pass  # other income - other expense
        elif lbl == "Net Income":
            totals["net_income"] = it["auto_amount"]

    totals["income_before_tax"] = totals["net_income"]  # QBO 는 tax provision 없음 (Schedule K-1 에서 처리)
    return items, totals


def generate_qbo_balance_sheet(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    fiscal_year: int,
    as_of_date: date,
    start_date: date,
) -> dict:
    """HOI BS — QBO Report API 사용. 25년 PDF 양식 그대로."""
    items, totals = fetch_qbo_balance_sheet(conn, entity_id, as_of_date)
    for item in items:
        from .helpers import _insert_line_item
        _insert_line_item(cur, stmt_id, item)
    return totals


def generate_qbo_income_statement(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    start_date: date,
    end_date: date,
) -> dict:
    """HOI PL — QBO Report API 사용."""
    items, totals = fetch_qbo_profit_loss(conn, entity_id, start_date, end_date)
    for item in items:
        from .helpers import _insert_line_item
        _insert_line_item(cur, stmt_id, item)
    return totals

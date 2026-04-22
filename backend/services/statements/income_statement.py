"""손익계산서 생성 — K-GAAP 공시 그룹 기반."""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from .helpers import _insert_line_item, _section_header


# ── 공시 그룹 정의 (legacy + K-GAAP) ──────────────
IS_REVENUE_SUBS = ["매출", "영업수익"]
IS_COGS_SUBS = ["매출원가"]
IS_SGA_SUBS = ["판매관리비", "판매비와관리비"]
IS_OTHER_INCOME_SUBS = ["영업외수익"]
IS_OTHER_EXPENSE_SUBS = ["영업외비용"]
IS_TAX_SUBS = ["법인세비용", "법인세", "법인세등"]


def _sum_by_subs(balances: list, category: str, subs: list[str]) -> list:
    """category + subcategory in subs 인 계정만 추출."""
    return [
        b for b in balances
        if b["category"] == category and (b.get("subcategory") or "") in subs
    ]


def _emit_bucket(
    items: list,
    st: str,
    key_prefix: str,
    accounts: list,
    label: str,
    order: int,
    header_label: str | None = None,
    indent: int = 2,
) -> tuple[Decimal, int]:
    """header → 계정들 → 소계 emit. 소계는 bucket total."""
    if header_label is not None:
        items.append(_section_header(st, f"{key_prefix}_header", header_label, order))
        order += 10
    total = Decimal("0")
    indent_str = " " * indent
    for b in accounts:
        items.append({
            "statement_type": st, "account_code": b["code"],
            "line_key": f"{key_prefix}_{b['code']}",
            "label": f"{indent_str}{b['name']}",
            "sort_order": order,
            "auto_amount": float(b["balance"]),
            "auto_debit": float(b["debit_total"]),
            "auto_credit": float(b["credit_total"]),
        })
        total += Decimal(str(b["balance"]))
        order += 10
    items.append({
        "statement_type": st, "line_key": f"{key_prefix}_total",
        "label": label, "sort_order": order,
        "auto_amount": float(total), "auto_debit": 0, "auto_credit": 0,
    })
    order += 10
    return total, order


# --- 손익계산서 ---

def generate_income_statement(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    start_date: date,
    end_date: date,
) -> dict:
    """손익계산서 생성 — K-GAAP 공시 항목 집계."""
    balances = get_all_account_balances(conn, entity_id, from_date=start_date, to_date=end_date)

    st = "income_statement"
    items = []
    order = 100

    # ── 매출 ──
    revenue_accounts = _sum_by_subs(balances, "수익", IS_REVENUE_SUBS)
    total_revenue, order = _emit_bucket(
        items, st, "rev", revenue_accounts, "매출 합계", order,
        header_label="매출",
    )

    # ── 매출원가 ──
    cogs_accounts = _sum_by_subs(balances, "비용", IS_COGS_SUBS)
    total_cogs = Decimal("0")
    if cogs_accounts:
        total_cogs, order = _emit_bucket(
            items, st, "cogs", cogs_accounts, "매출원가 합계", order,
            header_label="매출원가",
        )

    gross_profit = total_revenue - total_cogs
    items.append({
        "statement_type": st, "line_key": "gross_profit",
        "label": "매출총이익", "sort_order": order,
        "auto_amount": float(gross_profit), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # ── 판매비와관리비 ──
    sga_accounts = _sum_by_subs(balances, "비용", IS_SGA_SUBS)
    total_sga, order = _emit_bucket(
        items, st, "sga", sga_accounts, "판매비와관리비 합계", order,
        header_label="판매비와관리비",
    )

    operating_income = gross_profit - total_sga
    items.append({
        "statement_type": st, "line_key": "operating_income",
        "label": "영업이익", "sort_order": order,
        "auto_amount": float(operating_income), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # ── 영업외수익 ──
    other_income_accounts = _sum_by_subs(balances, "수익", IS_OTHER_INCOME_SUBS)
    total_other_income = Decimal("0")
    if other_income_accounts:
        total_other_income, order = _emit_bucket(
            items, st, "oi", other_income_accounts, "영업외수익 합계", order,
            header_label="영업외수익",
        )

    # ── 영업외비용 ──
    other_expense_accounts = _sum_by_subs(balances, "비용", IS_OTHER_EXPENSE_SUBS)
    total_other_expense = Decimal("0")
    if other_expense_accounts:
        total_other_expense, order = _emit_bucket(
            items, st, "oe", other_expense_accounts, "영업외비용 합계", order,
            header_label="영업외비용",
        )

    income_before_tax = operating_income + total_other_income - total_other_expense
    items.append({
        "statement_type": st, "line_key": "income_before_tax",
        "label": "법인세차감전순이익", "sort_order": order,
        "auto_amount": float(income_before_tax), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # ── 법인세 ──
    tax_accounts = _sum_by_subs(balances, "비용", IS_TAX_SUBS)
    total_tax = Decimal("0")
    if tax_accounts:
        total_tax, order = _emit_bucket(
            items, st, "tax", tax_accounts, "법인세등 합계", order,
            header_label="법인세등",
        )

    net_income = income_before_tax - total_tax
    items.append({
        "statement_type": st, "line_key": "net_income",
        "label": "당기순이익", "sort_order": order,
        "auto_amount": float(net_income), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    return {
        "total_revenue": float(total_revenue),
        "total_cogs": float(total_cogs),
        "gross_profit": float(gross_profit),
        "total_sga": float(total_sga),
        "operating_income": float(operating_income),
        "total_other_income": float(total_other_income),
        "total_other_expense": float(total_other_expense),
        "income_before_tax": float(income_before_tax),
        "total_tax": float(total_tax),
        "net_income": float(net_income),
    }

"""발생주의 손익계산서 — K-GAAP 정합 view (회계법인 결산자료 base).

설계 doc: docs/statements-accrual-plan.md (Phase A)

데이터 소스 분기:
  - 매출 (수익):    wholesale_sales (도매 매출관리 xlsx import)
  - 매출원가:       wholesale_purchases.supply_amount (도매 매입관리 — PDF 정합 base)
                   ※ 도매업 단순화: 매출원가 ≈ 기간 매입 (재고 변동 무시).
                   PDF 가결산 자료가 동일 방식 (검증 99.2%).
  - 판관비/영업외/세금: journal_entries (기존 income_statement.py 와 동일)

이중 카운팅 방지:
  - journal_entries 의 수익(매출), 비용(매출원가) 카테고리는 EXCLUDE
  - 판관비(판매관리비/판매비와관리비), 영업외수익/비용, 법인세 만 journal_entries 에서

VAT 처리 (옵션 ②):
  - vat_excluded=True (default): wholesale_sales.supply_amount 사용 (VAT 제외)
                                cogs_unit_price /1.1 (관행: VAT 포함 단가)
                                판관비는 standard_accounts.is_vat_taxable 에 따라 /1.1 또는 as-is
  - vat_excluded=False: wholesale_sales.total_amount, cogs_unit_price as-is, 판관비 as-is
"""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from .helpers import _insert_line_item


# 발생주의 모드: journal_entries 에서 가져올 카테고리 (수익/매출원가는 EXCLUDE)
SGA_SUBS = ("판매관리비", "판매비와관리비")
OTHER_INCOME_SUBS = ("영업외수익",)
OTHER_EXPENSE_SUBS = ("영업외비용",)
TAX_SUBS = ("법인세비용", "법인세", "법인세등")


def _fetch_revenue_cogs(
    conn: PgConnection,
    entity_id: int,
    start_date: date,
    end_date: date,
    vat_excluded: bool,
) -> dict:
    """매출 / 매출원가 / VAT 집계.

    매출       = wholesale_sales (지수)
    매출원가   = wholesale_purchases (PDF 정합 base — 도매업 단순화)
    부가세예수금 = SUM(wholesale_sales.vat) — BS 에서 사용
    부가세대급금 = SUM(wholesale_purchases.vat) — BS 에서 사용

    Returns: {revenue, cogs, sales_count, vat_collected, vat_paid}
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          COALESCE(SUM(total_amount), 0) AS revenue_incl,
          COALESCE(SUM(COALESCE(supply_amount, total_amount / 1.1)), 0) AS revenue_excl,
          COALESCE(SUM(vat), 0) AS vat_collected,
          COUNT(*) AS sales_count
        FROM wholesale_sales
        WHERE entity_id = %s AND sales_date >= %s AND sales_date <= %s
        """,
        [entity_id, start_date, end_date],
    )
    sales_row = cur.fetchone()

    cur.execute(
        """
        SELECT
          COALESCE(SUM(total_amount), 0) AS purchases_incl,
          COALESCE(SUM(COALESCE(supply_amount, total_amount / 1.1)), 0) AS purchases_excl,
          COALESCE(SUM(vat), 0) AS vat_paid,
          COUNT(*) AS purchases_count
        FROM wholesale_purchases
        WHERE entity_id = %s AND purchase_date >= %s AND purchase_date <= %s
        """,
        [entity_id, start_date, end_date],
    )
    pur_row = cur.fetchone()
    cur.close()

    if vat_excluded:
        return {
            "revenue": Decimal(str(sales_row[1])),
            "cogs": Decimal(str(pur_row[1])),
            "vat_collected": Decimal(str(sales_row[2])),
            "vat_paid": Decimal(str(pur_row[2])),
            "sales_count": sales_row[3],
            "purchases_count": pur_row[3],
        }
    return {
        "revenue": Decimal(str(sales_row[0])),
        "cogs": Decimal(str(pur_row[0])),
        "vat_collected": Decimal(str(sales_row[2])),
        "vat_paid": Decimal(str(pur_row[2])),
        "sales_count": sales_row[3],
        "purchases_count": pur_row[3],
    }


def _fetch_journal_subcat_total(
    conn: PgConnection,
    entity_id: int,
    start_date: date,
    end_date: date,
    category: str,
    subs: tuple[str, ...],
    vat_excluded: bool,
) -> tuple[Decimal, list[dict]]:
    """journal_entries (transactions base) 에서 특정 category/subcat 집계.

    수익/매출원가는 호출하지 말 것 (이중 카운팅 방지) — 발생주의는 wholesale_sales 사용.

    Returns: (total, [{code, name, amount}])
    - vat_excluded=True 시 standard_accounts.is_vat_taxable 활용 옵션 ②
    """
    cur = conn.cursor()
    if vat_excluded:
        amount_expr = "CASE WHEN s.is_vat_taxable THEN t.amount / 1.1 ELSE t.amount END"
    else:
        amount_expr = "t.amount"

    cur.execute(
        f"""
        SELECT s.code, s.name, COALESCE(SUM({amount_expr}), 0)
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s
          AND t.date >= %s AND t.date <= %s
          AND s.category = %s AND s.subcategory = ANY(%s)
          AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
        GROUP BY s.code, s.name
        ORDER BY s.code
        """,
        [entity_id, start_date, end_date, category, list(subs)],
    )
    rows = cur.fetchall()
    cur.close()

    items = [{"code": r[0], "name": r[1], "amount": Decimal(str(r[2]))} for r in rows]
    total = sum((it["amount"] for it in items), Decimal("0"))
    return total, items


def _emit_simple_bucket(
    items: list,
    st: str,
    key_prefix: str,
    accounts: list[dict],
    header_label: str,
    total: Decimal,
    order: int,
    indent: int = 2,
) -> int:
    """K-GAAP PDF 양식: 헤더에 합계 + indent 된 계정들.

    accounts: [{"code", "name", "amount"}]
    """
    items.append({
        "statement_type": st,
        "line_key": f"{key_prefix}_header",
        "label": header_label,
        "sort_order": order,
        "auto_amount": float(total),
        "auto_debit": 0,
        "auto_credit": 0,
        "is_section_header": True,
    })
    order += 10

    indent_str = " " * indent
    for a in accounts:
        items.append({
            "statement_type": st,
            "account_code": a["code"],
            "line_key": f"{key_prefix}_{a['code']}",
            "label": f"{indent_str}{a['name']}",
            "sort_order": order,
            "auto_amount": float(a["amount"]),
            "auto_debit": 0,
            "auto_credit": 0,
        })
        order += 10
    return order


def generate_income_statement_accrual(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    start_date: date,
    end_date: date,
    vat_excluded: bool = True,
) -> dict:
    """발생주의 손익계산서 생성.

    PDF 양식 (K-GAAP) 일치:
        Ⅰ. 매출액         (wholesale_sales)
        Ⅱ. 매출원가       (wholesale_sales × cogs_unit_price)
        Ⅲ. 매출총이익
        Ⅳ. 판매비와관리비 (journal_entries)
        Ⅴ. 영업이익
        Ⅵ. 영업외수익     (journal_entries)
        Ⅶ. 영업외비용     (journal_entries)
        Ⅷ. 법인세차감전순이익
        Ⅸ. 법인세등       (journal_entries)
        Ⅹ. 당기순이익
    """
    rc = _fetch_revenue_cogs(conn, entity_id, start_date, end_date, vat_excluded)
    revenue = rc["revenue"]
    cogs = rc["cogs"]

    sga_total, sga_items = _fetch_journal_subcat_total(
        conn, entity_id, start_date, end_date, "비용", SGA_SUBS, vat_excluded
    )
    other_income_total, other_income_items = _fetch_journal_subcat_total(
        conn, entity_id, start_date, end_date, "수익", OTHER_INCOME_SUBS, vat_excluded=False
    )
    other_expense_total, other_expense_items = _fetch_journal_subcat_total(
        conn, entity_id, start_date, end_date, "비용", OTHER_EXPENSE_SUBS, vat_excluded
    )
    tax_total, tax_items = _fetch_journal_subcat_total(
        conn, entity_id, start_date, end_date, "비용", TAX_SUBS, vat_excluded=False
    )

    st = "income_statement"
    items: list[dict] = []
    order = 100

    # Ⅰ. 매출액 (wholesale_sales — 단일 라인, 도매 합산)
    items.append({
        "statement_type": st,
        "line_key": "rev_header",
        "label": "Ⅰ. 매출액",
        "sort_order": order,
        "auto_amount": float(revenue),
        "auto_debit": 0,
        "auto_credit": 0,
        "is_section_header": True,
    })
    order += 10
    items.append({
        "statement_type": st,
        "line_key": "rev_wholesale",
        "label": "  상품매출",
        "sort_order": order,
        "auto_amount": float(revenue),
        "auto_debit": 0,
        "auto_credit": 0,
    })
    order += 20

    # Ⅱ. 매출원가
    items.append({
        "statement_type": st,
        "line_key": "cogs_header",
        "label": "Ⅱ. 매출원가",
        "sort_order": order,
        "auto_amount": float(cogs),
        "auto_debit": 0,
        "auto_credit": 0,
        "is_section_header": True,
    })
    order += 10
    items.append({
        "statement_type": st,
        "line_key": "cogs_wholesale",
        "label": "  상품매출원가",
        "sort_order": order,
        "auto_amount": float(cogs),
        "auto_debit": 0,
        "auto_credit": 0,
    })
    order += 20

    # Ⅲ. 매출총이익
    gross_profit = revenue - cogs
    items.append({
        "statement_type": st,
        "line_key": "gross_profit",
        "label": "Ⅲ. 매출총이익" if gross_profit >= 0 else "Ⅲ. 매출총손실",
        "sort_order": order,
        "auto_amount": float(abs(gross_profit)),
        "auto_debit": 0,
        "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # Ⅳ. 판매비와관리비
    order = _emit_simple_bucket(items, st, "sga", sga_items, "Ⅳ. 판매비와관리비", sga_total, order)
    order += 10

    # Ⅴ. 영업이익
    operating_income = gross_profit - sga_total
    items.append({
        "statement_type": st,
        "line_key": "operating_income",
        "label": "Ⅴ. 영업이익" if operating_income >= 0 else "Ⅴ. 영업손실",
        "sort_order": order,
        "auto_amount": float(abs(operating_income)),
        "auto_debit": 0,
        "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # Ⅵ. 영업외수익
    if other_income_items:
        order = _emit_simple_bucket(items, st, "oi", other_income_items, "Ⅵ. 영업외수익", other_income_total, order)
        order += 10

    # Ⅶ. 영업외비용
    if other_expense_items:
        order = _emit_simple_bucket(items, st, "oe", other_expense_items, "Ⅶ. 영업외비용", other_expense_total, order)
        order += 10

    # Ⅷ. 법인세차감전순이익
    income_before_tax = operating_income + other_income_total - other_expense_total
    items.append({
        "statement_type": st,
        "line_key": "income_before_tax",
        "label": "Ⅷ. 법인세차감전순이익" if income_before_tax >= 0 else "Ⅷ. 법인세차감전손실",
        "sort_order": order,
        "auto_amount": float(abs(income_before_tax)),
        "auto_debit": 0,
        "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # Ⅸ. 법인세등
    if tax_items:
        order = _emit_simple_bucket(items, st, "tax", tax_items, "Ⅸ. 법인세등", tax_total, order)
        order += 10
    else:
        items.append({
            "statement_type": st,
            "line_key": "tax_zero",
            "label": "Ⅸ. 법인세등",
            "sort_order": order,
            "auto_amount": 0,
            "auto_debit": 0,
            "auto_credit": 0,
            "is_section_header": True,
        })
        order += 20

    # Ⅹ. 당기순이익
    net_income = income_before_tax - tax_total
    items.append({
        "statement_type": st,
        "line_key": "net_income",
        "label": "Ⅹ. 당기순이익" if net_income >= 0 else "Ⅹ. 당기순손실",
        "sort_order": order,
        "auto_amount": float(abs(net_income)),
        "auto_debit": 0,
        "auto_credit": 0,
        "is_section_header": True,
    })

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    return {
        "total_revenue": float(revenue),
        "total_cogs": float(cogs),
        "gross_profit": float(gross_profit),
        "total_sga": float(sga_total),
        "operating_income": float(operating_income),
        "total_other_income": float(other_income_total),
        "total_other_expense": float(other_expense_total),
        "income_before_tax": float(income_before_tax),
        "total_tax": float(tax_total),
        "net_income": float(net_income),
        "vat_collected": float(rc["vat_collected"]),
        "vat_paid": float(rc["vat_paid"]),
        "sales_count": rc["sales_count"],
        "purchases_count": rc["purchases_count"],
        "vat_excluded": vat_excluded,
    }

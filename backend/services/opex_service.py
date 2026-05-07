"""OpEx (실질 운영비, SG&A) 서비스 — 월별 시리즈 + 해당 월 상세 (KPI + 카테고리 + 거래).

도매업 한아원홀세일에서 외상매입금 결제(부채/유동부채)에 SG&A 가 묻혀버려
가시성 X. standard_accounts.category='비용' AND subcategory IN
('판매관리비','판매비와관리비') 만 추려 별도 페이지로 표시.

매출원가/영업외비용/법인세/자산취득/부채상환은 운영비 아님 — 자동 제외.
HOI(US-GAAP, category='Expense') 는 Phase A 미지원 — 빈 데이터.
"""

from decimal import Decimal

from psycopg2.extensions import connection as PgConnection

from backend.utils.db import build_date_range, fetch_all


# K-GAAP SG&A 식별. category='비용' 안에서 매출원가/영업외/법인세 제외 → 판관비만.
SGA_SUBCATEGORIES = ("판매관리비", "판매비와관리비")


def get_opex_summary_data(
    conn: PgConnection,
    entity_id: int,
    months: int = 12,
) -> dict:
    """월별 운영비 시리즈 — 차트용.

    Returns: { months: [{month, expense}], available_months }
    """
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT to_char(date_trunc('month', t.date), 'YYYY-MM') AS month
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s
          AND s.category = '비용'
          AND s.subcategory = ANY(%s)
          AND t.type = 'out'
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
        ORDER BY month
        """,
        [entity_id, list(SGA_SUBCATEGORIES)],
    )
    available_months = [r[0] for r in cur.fetchall()]

    if not available_months:
        cur.close()
        return {"months": [], "available_months": []}

    target_months = available_months[-months:]
    first_month = target_months[0]
    first_year, first_mon = int(first_month[:4]), int(first_month[5:7])
    first_date = f"{first_year:04d}-{first_mon:02d}-01"

    cur.execute(
        """
        SELECT
            to_char(date_trunc('month', t.date), 'YYYY-MM') AS month,
            COALESCE(SUM(t.amount), 0) AS expense,
            COUNT(*) AS tx_count
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s
          AND s.category = '비용'
          AND s.subcategory = ANY(%s)
          AND t.type = 'out'
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
          AND t.date >= %s::date
        GROUP BY date_trunc('month', t.date)
        ORDER BY month
        """,
        [entity_id, list(SGA_SUBCATEGORIES), first_date],
    )
    expense_by_month = {r[0]: (Decimal(str(r[1])), r[2]) for r in cur.fetchall()}
    cur.close()

    result_months = []
    for m in target_months:
        expense, tx_count = expense_by_month.get(m, (Decimal(0), 0))
        result_months.append({
            "month": m,
            "expense": float(expense),
            "tx_count": tx_count,
        })

    return {
        "months": result_months,
        "available_months": available_months,
    }


def get_opex_detail(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
) -> dict:
    """해당 월 운영비 상세 — KPI + 카테고리 breakdown + 거래 list."""
    start, end = build_date_range(year, month)

    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.date, t.amount, t.description, t.counterparty,
               t.source_type,
               t.internal_account_id,
               ia.name AS internal_account_name,
               pia.name AS parent_account_name,
               t.standard_account_id,
               s.code AS std_code, s.name AS std_name
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        LEFT JOIN internal_accounts ia ON t.internal_account_id = ia.id
        LEFT JOIN internal_accounts pia ON ia.parent_id = pia.id
        WHERE t.entity_id = %s
          AND s.category = '비용'
          AND s.subcategory = ANY(%s)
          AND t.type = 'out'
          AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
        ORDER BY t.date, t.id
        """,
        [entity_id, list(SGA_SUBCATEGORIES), start, end],
    )
    rows = fetch_all(cur)

    # Prev month total — for change_pct
    prev_y = year if month > 1 else year - 1
    prev_m = month - 1 if month > 1 else 12
    prev_start, prev_end = build_date_range(prev_y, prev_m)
    cur.execute(
        """
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s
          AND s.category = '비용'
          AND s.subcategory = ANY(%s)
          AND t.type = 'out'
          AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
        """,
        [entity_id, list(SGA_SUBCATEGORIES), prev_start, prev_end],
    )
    prev_total = Decimal(str(cur.fetchone()[0]))

    # YoY (12개월 전)
    yoy_y = year - 1
    yoy_start, yoy_end = build_date_range(yoy_y, month)
    cur.execute(
        """
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE t.entity_id = %s
          AND s.category = '비용'
          AND s.subcategory = ANY(%s)
          AND t.type = 'out'
          AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
        """,
        [entity_id, list(SGA_SUBCATEGORIES), yoy_start, yoy_end],
    )
    yoy_total = Decimal(str(cur.fetchone()[0]))
    cur.close()

    total = sum((Decimal(str(r["amount"])) for r in rows), Decimal(0))
    tx_count = len(rows)

    change_pct = (
        round(float((total - prev_total) / prev_total * 100), 1)
        if prev_total > 0 else None
    )
    yoy_pct = (
        round(float((total - yoy_total) / yoy_total * 100), 1)
        if yoy_total > 0 else None
    )

    # 표준계정별 breakdown — 절감 candidate 1차 추림
    by_std: dict[str, dict] = {}
    for r in rows:
        key = f"{r['std_code']} {r['std_name']}"
        if key not in by_std:
            by_std[key] = {
                "std_code": r["std_code"],
                "std_name": r["std_name"],
                "amount": Decimal(0),
                "tx_count": 0,
            }
        by_std[key]["amount"] += Decimal(str(r["amount"]))
        by_std[key]["tx_count"] += 1

    std_breakdown = sorted(
        [{**v, "amount": float(v["amount"])} for v in by_std.values()],
        key=lambda x: x["amount"],
        reverse=True,
    )

    # 내부계정 parent (대분류) 별 breakdown — 사용자 친화적 라벨
    by_parent: dict[str, dict] = {}
    for r in rows:
        key = r["parent_account_name"] or r["internal_account_name"] or "미분류"
        if key not in by_parent:
            by_parent[key] = {
                "parent_name": key,
                "amount": Decimal(0),
                "tx_count": 0,
            }
        by_parent[key]["amount"] += Decimal(str(r["amount"]))
        by_parent[key]["tx_count"] += 1

    parent_breakdown = sorted(
        [{**v, "amount": float(v["amount"])} for v in by_parent.values()],
        key=lambda x: x["amount"],
        reverse=True,
    )

    serialized_rows = [
        {
            "id": r["id"],
            "date": str(r["date"]),
            "amount": float(r["amount"]),
            "description": r["description"],
            "counterparty": r.get("counterparty"),
            "source_type": r.get("source_type"),
            "internal_account_name": r.get("internal_account_name"),
            "parent_account_name": r.get("parent_account_name"),
            "std_code": r.get("std_code"),
            "std_name": r.get("std_name"),
        }
        for r in rows
    ]

    return {
        "year": year,
        "month": month,
        "entity_id": entity_id,
        "total": float(total),
        "tx_count": tx_count,
        "prev_total": float(prev_total),
        "change_pct": change_pct,
        "yoy_total": float(yoy_total),
        "yoy_pct": yoy_pct,
        "std_breakdown": std_breakdown,
        "parent_breakdown": parent_breakdown,
        "transactions": serialized_rows,
    }

"""외상매출금 / 매출회수율 분석 서비스.

매출관리 (wholesale_sales) 의 발생주의 매출 vs 거래내역 (transactions) 의
실제 입금 (상품매출 코드 40100) 을 거래처 단위로 통합. payee_aliases 로
약국 사장 개인명 ↔ 약국 정식명 연결.

용도:
- 거래처별 발생/회수/외상 잔액
- 월별 매출 회수율 추이
- 외상 회수 지연 거래처 알림
"""

from decimal import Decimal

from psycopg2.extensions import connection as PgConnection


def get_receivables_summary(
    conn: PgConnection, entity_id: int,
    year: int | None = None, month: int | None = None,
) -> dict:
    """거래처별 외상매출금 + 회수율 분석.

    Args:
        year/month: 지정 시 해당 월까지 누적. 없으면 전체 기간.

    Returns:
        총 발생/회수/외상 + 거래처별 detail (top 50)
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    period_filter_sales = ""
    period_filter_tx = ""
    params_sales = [entity_id]
    params_tx = [entity_id]

    if year and month:
        # ~ year-month 마지막 날까지 누적
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year = year + 1
        end_date = f"{next_year}-{next_month:02d}-01"
        period_filter_sales = "AND sales_date < %s"
        period_filter_tx = "AND t.date < %s"
        params_sales.append(end_date)
        params_tx.append(end_date)

    cur.execute(
        f"""
        WITH alias_map AS (
            -- 거래내역 counterparty → 매출관리 canonical 거래처
            SELECT alias, canonical_name FROM payee_aliases WHERE entity_id = %s
            UNION ALL
            -- 매출관리 거래처는 자기 자신 매핑 (counterparty 가 동일하면 그대로 매칭)
            SELECT DISTINCT payee_name AS alias, payee_name AS canonical_name
            FROM wholesale_sales WHERE entity_id = %s
        ),
        sales AS (
            SELECT payee_name AS canonical, SUM(total_amount) AS billed, COUNT(*) AS sales_count
            FROM wholesale_sales
            WHERE entity_id = %s {period_filter_sales}
            GROUP BY payee_name
        ),
        collected AS (
            SELECT am.canonical_name AS canonical,
                   SUM(t.amount) AS received, COUNT(*) AS receive_count
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            JOIN alias_map am ON am.alias = t.counterparty
            WHERE t.entity_id = %s AND t.type = 'in' AND s.code = '40100'
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
              {period_filter_tx}
            GROUP BY am.canonical_name
        )
        SELECT
            COALESCE(s.canonical, c.canonical) AS canonical,
            COALESCE(s.billed, 0) AS billed,
            COALESCE(c.received, 0) AS received,
            COALESCE(s.billed, 0) - COALESCE(c.received, 0) AS outstanding,
            COALESCE(s.sales_count, 0) AS sales_count,
            COALESCE(c.receive_count, 0) AS receive_count
        FROM sales s
        FULL OUTER JOIN collected c USING (canonical)
        ORDER BY ABS(COALESCE(s.billed, 0) - COALESCE(c.received, 0)) DESC
        """,
        [entity_id, entity_id, *params_sales, *params_tx],
    )
    rows = cur.fetchall()

    total_billed = Decimal(0)
    total_received = Decimal(0)
    total_outstanding = Decimal(0)
    detail = []
    no_match_received = []  # 매출관리에 없는데 입금만 있는 (alias 없는 거래처)
    for r in rows:
        canonical, billed, received, outstanding, sc, rc = r
        billed = Decimal(str(billed))
        received = Decimal(str(received))
        outstanding = Decimal(str(outstanding))
        total_billed += billed
        total_received += received
        total_outstanding += outstanding
        item = {
            "canonical": canonical,
            "billed": float(billed),
            "received": float(received),
            "outstanding": float(outstanding),
            "sales_count": sc,
            "receive_count": rc,
            "collection_rate_pct": float(received / billed * 100) if billed > 0 else None,
        }
        if billed == 0 and received > 0:
            no_match_received.append(item)
        else:
            detail.append(item)

    cur.close()

    overall_rate = (
        float(total_received / total_billed * 100) if total_billed > 0 else None
    )

    return {
        "entity_id": entity_id,
        "year": year, "month": month,
        "total_billed": float(total_billed),
        "total_received": float(total_received),
        "total_outstanding": float(total_outstanding),
        "collection_rate_pct": overall_rate,
        "payee_count": len(detail),
        "detail": detail[:100],  # top 100
        "no_match_received": no_match_received[:30],  # alias 없는 입금
    }


def get_receivables_monthly(
    conn: PgConnection, entity_id: int, months: int = 12,
) -> dict:
    """월별 발생/회수/회수율 추이."""
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    cur.execute(
        """
        SELECT to_char(date_trunc('month', sales_date), 'YYYY-MM') AS m,
               SUM(total_amount) AS billed
        FROM wholesale_sales WHERE entity_id = %s GROUP BY 1 ORDER BY 1
        """,
        [entity_id],
    )
    sales_by_month = {r[0]: float(r[1]) for r in cur.fetchall()}

    cur.execute(
        """
        WITH alias_map AS (
            SELECT alias, canonical_name FROM payee_aliases WHERE entity_id = %s
            UNION ALL
            SELECT DISTINCT payee_name, payee_name FROM wholesale_sales WHERE entity_id = %s
        )
        SELECT to_char(date_trunc('month', t.date), 'YYYY-MM') AS m,
               SUM(t.amount) AS received
        FROM transactions t
        JOIN standard_accounts s ON s.id = t.standard_account_id
        JOIN alias_map am ON am.alias = t.counterparty
        WHERE t.entity_id = %s AND t.type='in' AND s.code='40100'
          AND t.is_duplicate=false AND (t.is_cancel IS NOT TRUE)
        GROUP BY 1 ORDER BY 1
        """,
        [entity_id, entity_id, entity_id],
    )
    received_by_month = {r[0]: float(r[1]) for r in cur.fetchall()}

    all_months = sorted(set(list(sales_by_month) + list(received_by_month)))[-months:]
    cumulative_outstanding = 0.0
    rows = []
    for m in all_months:
        billed = sales_by_month.get(m, 0)
        received = received_by_month.get(m, 0)
        cumulative_outstanding += billed - received
        rows.append({
            "month": m,
            "billed": billed,
            "received": received,
            "monthly_diff": billed - received,
            "cumulative_outstanding": cumulative_outstanding,
            "collection_rate_pct": (received / billed * 100) if billed > 0 else None,
        })
    cur.close()
    return {"entity_id": entity_id, "months": rows}

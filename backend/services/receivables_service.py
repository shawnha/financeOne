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

# 도매 법인 — 수금을 은행 입금 이름매칭 대신 SIMS customer_collections(입금) 코드 기준으로 집계.
# wholesale_sales.payee_code ↔ customer_collections.customer_code 100% 정합 (customer_name == payee_name).
_WHOLESALE_ENTITIES = {13}


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

    is_wholesale = entity_id in _WHOLESALE_ENTITIES

    end_date = None
    if year and month:
        # ~ year-month 마지막 날까지 누적
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year = year + 1
        end_date = f"{next_year}-{next_month:02d}-01"

    # ar_opening_balances 의 가장 최근 opening_date — 그 이후의 발생/회수만 카운트
    # (opening 이전은 잔고에 이미 net 으로 반영됨)
    cur.execute(
        "SELECT MAX(opening_date) FROM ar_opening_balances WHERE entity_id = %s AND direction = 'receivable'",
        [entity_id],
    )
    latest_opening = cur.fetchone()[0]  # date or None

    period_filter_sales = ""
    params_sales = [entity_id]
    if end_date:
        period_filter_sales += " AND sales_date < %s"
        params_sales.append(end_date)
    if latest_opening is not None:
        period_filter_sales += " AND sales_date > %s"
        params_sales.append(latest_opening)

    # 기초잔고 (ar_opening_balances) 도 거래처별 sales 에 가산.
    # 기초 보정 조건: opening_date <= 조회 끝 (year+month 가 지정되면 end_date, 없으면 무제한).
    opening_filter = ""
    opening_params: list = []
    if end_date:
        opening_filter = "AND opening_date < %s"
        opening_params.append(end_date)

    # CTE 조립 — 도매 법인은 수금을 SIMS customer_collections(입금) 로 집계 (코드=이름 정합).
    ctes: list[str] = []
    params: list = []
    if not is_wholesale:
        ctes.append(
            """alias_map AS (
            SELECT alias, canonical_name FROM payee_aliases WHERE entity_id = %s
            UNION ALL
            SELECT DISTINCT payee_name AS alias, payee_name AS canonical_name
            FROM wholesale_sales WHERE entity_id = %s
        )"""
        )
        params += [entity_id, entity_id]

    ctes.append(
        f"""sales AS (
            SELECT payee_name AS canonical, SUM(total_amount) AS billed, COUNT(*) AS sales_count
            FROM wholesale_sales
            WHERE entity_id = %s {period_filter_sales}
            GROUP BY payee_name
        )"""
    )
    params += params_sales

    ctes.append(
        f"""opening AS (
            SELECT payee_name AS canonical, SUM(balance) AS opening_balance
            FROM ar_opening_balances
            WHERE entity_id = %s AND direction = 'receivable' {opening_filter}
            GROUP BY payee_name
        )"""
    )
    params += [entity_id, *opening_params]

    coll_filter = ""
    coll_params: list = [entity_id]
    if is_wholesale:
        if end_date:
            coll_filter += " AND trans_date < %s"
            coll_params.append(end_date)
        if latest_opening is not None:
            coll_filter += " AND trans_date > %s"
            coll_params.append(latest_opening)
        ctes.append(
            f"""collected AS (
            SELECT customer_name AS canonical, SUM(amount) AS received, COUNT(*) AS receive_count
            FROM customer_collections
            WHERE entity_id = %s AND io_gu = '입금' {coll_filter}
            GROUP BY customer_name
        )"""
        )
        params += coll_params
    else:
        period_filter_tx = ""
        params_tx = [entity_id]
        if end_date:
            period_filter_tx += " AND t.date < %s"
            params_tx.append(end_date)
        if latest_opening is not None:
            period_filter_tx += " AND t.date > %s"
            params_tx.append(latest_opening)
        ctes.append(
            f"""collected AS (
            SELECT am.canonical_name AS canonical,
                   SUM(t.amount) AS received, COUNT(*) AS receive_count
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            JOIN alias_map am ON am.alias = t.counterparty
            WHERE t.entity_id = %s AND t.type = 'in' AND s.code IN ('40100', '10800')
              AND t.is_duplicate = false AND (t.is_cancel IS NOT TRUE)
              {period_filter_tx}
            GROUP BY am.canonical_name
        )"""
        )
        params += params_tx

    cur.execute(
        "WITH " + ",\n".join(ctes) + """
        SELECT
            COALESCE(s.canonical, o.canonical, c.canonical) AS canonical,
            COALESCE(s.billed, 0) + COALESCE(o.opening_balance, 0) AS billed,
            COALESCE(c.received, 0) AS received,
            COALESCE(s.billed, 0) + COALESCE(o.opening_balance, 0) - COALESCE(c.received, 0) AS outstanding,
            COALESCE(s.sales_count, 0) AS sales_count,
            COALESCE(c.receive_count, 0) AS receive_count
        FROM sales s
        FULL OUTER JOIN opening o USING (canonical)
        FULL OUTER JOIN collected c USING (canonical)
        ORDER BY ABS(COALESCE(s.billed, 0) + COALESCE(o.opening_balance, 0) - COALESCE(c.received, 0)) DESC
        """,
        params,
    )
    rows = cur.fetchall()

    # 기초잔고 총합 (KPI 표시용)
    cur.execute(
        """
        SELECT COALESCE(SUM(balance), 0) FROM ar_opening_balances
        WHERE entity_id = %s AND direction = 'receivable'
        """ + (" AND opening_date < %s" if (year and month) else ""),
        [entity_id] + ([end_date] if (year and month) else []),
    )
    total_opening = Decimal(str(cur.fetchone()[0]))

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

    # 수금방식 분해 (도매 — 보통예금/카드결제/더샵몰 등). 그 외 법인은 빈 배열.
    collection_methods: list = []
    if is_wholesale:
        cur.execute(
            f"""
            SELECT method, SUM(amount) AS amt, COUNT(*) AS cnt
            FROM customer_collections
            WHERE entity_id = %s AND io_gu = '입금' {coll_filter}
            GROUP BY method ORDER BY amt DESC
            """,
            coll_params,
        )
        mrows = cur.fetchall()
        mtotal = sum((Decimal(str(r[1])) for r in mrows), Decimal(0)) or Decimal(1)
        collection_methods = [
            {
                "method": m or "기타",
                "amount": float(Decimal(str(amt))),
                "count": cnt,
                "pct": float(Decimal(str(amt)) / mtotal * 100),
            }
            for m, amt, cnt in mrows
        ]

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
        "opening_balance": float(total_opening),
        "collection_rate_pct": overall_rate,
        "payee_count": len(detail),
        "detail": detail[:100],  # top 100
        "no_match_received": no_match_received[:30],  # alias 없는 입금
        "collection_methods": collection_methods,
    }


def get_receivables_daily(
    conn: PgConnection, entity_id: int,
    start_date: str | None = None, end_date: str | None = None,
) -> dict:
    """일별 발생/회수/누적 외상매출금.

    Args:
        start_date / end_date: 'YYYY-MM-DD'. 미지정 시 전체 기간.

    Returns:
        {entity_id, days: [{date, billed, received, daily_diff, cumulative_outstanding, collection_rate_pct}]}
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    sales_filter = "WHERE entity_id = %s"
    sales_params = [entity_id]
    tx_filter = "AND t.entity_id = %s AND t.type='in' AND s.code IN ('40100', '10800') AND t.is_duplicate=false AND (t.is_cancel IS NOT TRUE)"
    tx_params = [entity_id, entity_id, entity_id]
    if start_date:
        sales_filter += " AND sales_date >= %s"; sales_params.append(start_date)
        tx_filter += " AND t.date >= %s"; tx_params.append(start_date)
    if end_date:
        sales_filter += " AND sales_date <= %s"; sales_params.append(end_date)
        tx_filter += " AND t.date <= %s"; tx_params.append(end_date)

    # latest opening_date 이전 발생/회수는 opening 에 net 으로 반영됨 → 제외
    cur.execute(
        "SELECT MAX(opening_date) FROM ar_opening_balances WHERE entity_id = %s AND direction = 'receivable'",
        [entity_id],
    )
    latest_opening = cur.fetchone()[0]
    if latest_opening is not None:
        sales_filter += " AND sales_date > %s"; sales_params.append(latest_opening)
        tx_filter += " AND t.date > %s"; tx_params.append(latest_opening)

    cur.execute(
        f"""
        SELECT to_char(sales_date, 'YYYY-MM-DD') AS d, SUM(total_amount) AS billed
        FROM wholesale_sales {sales_filter}
        GROUP BY 1 ORDER BY 1
        """,
        sales_params,
    )
    sales_by_day = {r[0]: float(r[1]) for r in cur.fetchall()}

    if entity_id in _WHOLESALE_ENTITIES:
        coll_filter = "WHERE entity_id = %s AND io_gu = '입금'"
        coll_params: list = [entity_id]
        if start_date:
            coll_filter += " AND trans_date >= %s"; coll_params.append(start_date)
        if end_date:
            coll_filter += " AND trans_date <= %s"; coll_params.append(end_date)
        if latest_opening is not None:
            coll_filter += " AND trans_date > %s"; coll_params.append(latest_opening)
        cur.execute(
            f"""
            SELECT to_char(trans_date, 'YYYY-MM-DD') AS d, SUM(amount) AS received
            FROM customer_collections {coll_filter}
            GROUP BY 1 ORDER BY 1
            """,
            coll_params,
        )
    else:
        cur.execute(
            f"""
            WITH alias_map AS (
                SELECT alias, canonical_name FROM payee_aliases WHERE entity_id = %s
                UNION ALL
                SELECT DISTINCT payee_name, payee_name FROM wholesale_sales WHERE entity_id = %s
            )
            SELECT to_char(t.date, 'YYYY-MM-DD') AS d, SUM(t.amount) AS received
            FROM transactions t
            JOIN standard_accounts s ON s.id = t.standard_account_id
            JOIN alias_map am ON am.alias = t.counterparty
            WHERE TRUE {tx_filter}
            GROUP BY 1 ORDER BY 1
            """,
            tx_params,
        )
    received_by_day = {r[0]: float(r[1]) for r in cur.fetchall()}

    # 기초잔고: latest opening_date 까지의 ar_opening_balances 합산 (start_date 무관)
    cur.execute(
        """
        SELECT COALESCE(SUM(balance), 0) FROM ar_opening_balances
        WHERE entity_id = %s AND direction = 'receivable'
        """,
        [entity_id],
    )
    opening_carry = float(cur.fetchone()[0])

    all_days = sorted(set(list(sales_by_day) + list(received_by_day)))
    cumulative = opening_carry  # 기초잔고에서 시작
    rows = []
    for d in all_days:
        billed = sales_by_day.get(d, 0)
        received = received_by_day.get(d, 0)
        cumulative += billed - received
        rows.append({
            "date": d,
            "billed": billed,
            "received": received,
            "daily_diff": billed - received,
            "cumulative_outstanding": cumulative,
            "collection_rate_pct": (received / billed * 100) if billed > 0 else None,
        })
    cur.close()
    return {"entity_id": entity_id, "opening_balance": opening_carry, "days": rows}


def get_receivables_monthly(
    conn: PgConnection, entity_id: int, months: int = 12,
) -> dict:
    """월별 발생/회수/회수율 추이.

    ar_opening_balances 가 있으면 그 이후 월만 표시 (이전은 opening 에 net 으로 반영).
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # latest opening_date — 그 이전 월은 sales/received 모두 무시
    cur.execute(
        "SELECT MAX(opening_date) FROM ar_opening_balances WHERE entity_id = %s AND direction = 'receivable'",
        [entity_id],
    )
    latest_opening = cur.fetchone()[0]
    sales_filter = ""
    tx_filter = ""
    sales_params: list = [entity_id]
    tx_params: list = [entity_id, entity_id, entity_id]
    if latest_opening is not None:
        sales_filter = "AND sales_date > %s"
        tx_filter = "AND t.date > %s"
        sales_params.append(latest_opening)
        tx_params.append(latest_opening)

    cur.execute(
        f"""
        SELECT to_char(date_trunc('month', sales_date), 'YYYY-MM') AS m,
               SUM(total_amount) AS billed
        FROM wholesale_sales WHERE entity_id = %s {sales_filter}
        GROUP BY 1 ORDER BY 1
        """,
        sales_params,
    )
    sales_by_month = {r[0]: float(r[1]) for r in cur.fetchall()}

    if entity_id in _WHOLESALE_ENTITIES:
        coll_filter = ""
        coll_params: list = [entity_id]
        if latest_opening is not None:
            coll_filter = "AND trans_date > %s"
            coll_params.append(latest_opening)
        cur.execute(
            f"""
            SELECT to_char(date_trunc('month', trans_date), 'YYYY-MM') AS m,
                   SUM(amount) AS received
            FROM customer_collections
            WHERE entity_id = %s AND io_gu = '입금' {coll_filter}
            GROUP BY 1 ORDER BY 1
            """,
            coll_params,
        )
    else:
        cur.execute(
        f"""
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
        WHERE t.entity_id = %s AND t.type='in' AND s.code IN ('40100', '10800')
          AND t.is_duplicate=false AND (t.is_cancel IS NOT TRUE)
          {tx_filter}
        GROUP BY 1 ORDER BY 1
        """,
        tx_params,
    )
    received_by_month = {r[0]: float(r[1]) for r in cur.fetchall()}

    all_months = sorted(set(list(sales_by_month) + list(received_by_month)))[-months:]

    # 기초잔고: all_months 중 가장 빠른 월의 1일 이전 ar_opening_balances 합산
    opening_carry = 0.0
    if all_months:
        first_m = all_months[0]
        # 'YYYY-MM' → 'YYYY-MM-01'
        cur.execute(
            """
            SELECT COALESCE(SUM(balance), 0) FROM ar_opening_balances
            WHERE entity_id = %s AND direction = 'receivable' AND opening_date < %s
            """,
            [entity_id, f"{first_m}-01"],
        )
        opening_carry = float(cur.fetchone()[0])

    cumulative_outstanding = opening_carry
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
    return {"entity_id": entity_id, "opening_balance": opening_carry, "months": rows}

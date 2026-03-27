"""Cashflow service — 기초잔고 역산, 일별 잔고 추적, 월별 요약, 카드비용 그룹핑.

순수 계산 함수 (build_daily_rows, aggregate_monthly_summary, group_card_expenses)와
DB 조회 함수 (get_actual_cashflow, get_monthly_summary, get_card_expenses)를 분리.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional

from psycopg2.extensions import connection as PgConnection

from backend.utils.db import build_date_range, fetch_all


# ── Pure computation functions (no DB) ───────────────────────────────────────


def build_daily_rows(
    transactions: list[dict],
    opening_balance: Decimal,
) -> list[dict]:
    """은행 거래 리스트 + 기초잔고 → 일별 running balance 행 리스트.

    Returns list of dicts:
      - opening row (type="opening")
      - transaction rows with running balance
      - closing row (type="closing")
    """
    rows = []

    # Opening row
    rows.append({
        "type": "opening",
        "date": None,
        "description": "시작 잔고",
        "amount": Decimal("0"),
        "balance": opening_balance,
        "tx_id": None,
    })

    balance = opening_balance
    for tx in transactions:
        amount = Decimal(str(tx["amount"]))
        if tx["type"] == "in":
            balance += amount
        else:  # out
            balance -= amount

        rows.append({
            "type": tx["type"],
            "date": tx["date"],
            "description": tx.get("description", ""),
            "counterparty": tx.get("counterparty"),
            "amount": amount,
            "balance": balance,
            "tx_id": tx.get("id"),
            "source_type": tx.get("source_type"),
        })

    # Closing row
    rows.append({
        "type": "closing",
        "date": None,
        "description": "기말 잔고",
        "amount": Decimal("0"),
        "balance": balance,
        "tx_id": None,
    })

    return rows


def aggregate_monthly_summary(
    transactions: list[dict],
    year: int,
    month: int,
) -> dict:
    """거래 리스트 → 단일 월 요약 (income, expense, net)."""
    income = Decimal("0")
    expense = Decimal("0")

    for tx in transactions:
        amount = Decimal(str(tx["amount"]))
        if tx["type"] == "in":
            income += amount
        else:
            expense += amount

    return {
        "year": year,
        "month": month,
        "income": income,
        "expense": expense,
        "net": income - expense,
    }


def calc_card_timing_adjustment(
    prev_month_card: Decimal,
    curr_month_card: Decimal,
) -> Decimal:
    """카드 시차 보정 = 전월 카드 사용(확정) - 당월 카드 사용(예상).

    양수 → 전월 사용이 더 많아 카드대금 결제 부담 증가.
    음수 → 당월 사용이 더 많아 카드대금 결제 부담 감소.
    """
    return prev_month_card - curr_month_card


def calc_forecast_closing(
    opening_balance: Decimal,
    forecast_income: Decimal,
    forecast_expense: Decimal,
    forecast_card_usage: Decimal,
    card_timing_adjustment: Decimal,
) -> Decimal:
    """예상 기말잔고 = 기초 + 예상입금 - 예상출금 - 예상카드사용 + 시차보정."""
    return (
        opening_balance
        + forecast_income
        - forecast_expense
        - forecast_card_usage
        + card_timing_adjustment
    )


def group_card_expenses(transactions: list[dict]) -> list[dict]:
    """카드 거래 리스트 → 소스별 → 회원별 그룹핑 + 내부계정 breakdown.

    Returns list of source groups, each containing:
      - source_type, total_expense, total_refund, net, tx_count
      - members: [{member_name, member_id, transactions, subtotal, refund}]
      - account_breakdown: [{account_name, amount, tx_count}]
    """
    if not transactions:
        return []

    # Group by source_type
    by_source: dict[str, list[dict]] = defaultdict(list)
    for tx in transactions:
        by_source[tx["source_type"]].append(tx)

    result = []
    for source_type, source_txs in sorted(by_source.items()):
        total_expense = Decimal("0")
        total_refund = Decimal("0")

        # Group by member
        by_member: dict[Optional[int], list[dict]] = defaultdict(list)
        for tx in source_txs:
            by_member[tx.get("member_id")].append(tx)

        members = []
        for member_id, member_txs in by_member.items():
            member_expense = Decimal("0")
            member_refund = Decimal("0")
            for tx in member_txs:
                amount = Decimal(str(tx["amount"]))
                if tx["type"] == "in":
                    member_refund += amount
                    total_refund += amount
                else:
                    member_expense += amount
                    total_expense += amount

            members.append({
                "member_id": member_id,
                "member_name": member_txs[0].get("member_name"),
                "transactions": member_txs,
                "subtotal": member_expense,
                "refund": member_refund,
                "net": member_expense - member_refund,
                "tx_count": len(member_txs),
            })

        # Account breakdown at source level
        account_totals: dict[str, Decimal] = defaultdict(Decimal)
        account_counts: dict[str, int] = defaultdict(int)
        for tx in source_txs:
            if tx["type"] == "out":
                acct = tx.get("account_name") or "기타"
                account_totals[acct] += Decimal(str(tx["amount"]))
                account_counts[acct] += 1

        account_breakdown = sorted(
            [
                {"account_name": name, "amount": amount, "tx_count": account_counts[name]}
                for name, amount in account_totals.items()
            ],
            key=lambda x: x["amount"],
            reverse=True,
        )

        result.append({
            "source_type": source_type,
            "total_expense": total_expense,
            "total_refund": total_refund,
            "net": total_expense - total_refund,
            "tx_count": len(source_txs),
            "members": members,
            "account_breakdown": account_breakdown,
        })

    return result


# ── DB query functions ───────────────────────────────────────────────────────


def get_opening_balance(conn: PgConnection, entity_id: int, year: int, month: int) -> Decimal:
    """해당 월 기초잔고 조회 — balance_snapshots에서 해당 월 이전 최신 스냅샷."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(balance), 0)
        FROM balance_snapshots
        WHERE (entity_id, date, account_name) IN (
            SELECT entity_id, MAX(date), account_name
            FROM balance_snapshots
            WHERE entity_id = %s
              AND date <= make_date(%s, %s, 1)
            GROUP BY entity_id, account_name
        )
        """,
        [entity_id, year, month],
    )
    result = Decimal(str(cur.fetchone()[0]))
    cur.close()
    return result


def get_bank_transactions(conn: PgConnection, entity_id: int, year: int, month: int) -> list[dict]:
    """특정 월 은행 거래 조회 (시간순)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.date, t.type, t.amount, t.description, t.counterparty,
               t.source_type
        FROM transactions t
        WHERE t.entity_id = %s
          AND t.source_type IN ('woori_bank', 'mercury_api', 'manual')
          AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false
        ORDER BY t.date, t.id
        """,
        [entity_id, *build_date_range(year, month)],
    )
    rows = fetch_all(cur)
    cur.close()
    return rows


def get_card_transactions(conn: PgConnection, entity_id: int, year: int, month: int) -> list[dict]:
    """특정 월 카드 사용 내역 조회 (소스→회원→일자순)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.date, t.type, t.amount, t.description, t.counterparty,
               t.source_type, t.member_id,
               m.name AS member_name,
               sa.name AS account_name, sa.code AS account_code
        FROM transactions t
        LEFT JOIN members m ON t.member_id = m.id
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE t.entity_id = %s
          AND t.source_type IN ('lotte_card', 'woori_card')
          AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false
        ORDER BY t.source_type, t.member_id, t.date, t.id
        """,
        [entity_id, *build_date_range(year, month)],
    )
    rows = fetch_all(cur)
    cur.close()
    return rows


def get_monthly_summary_data(
    conn: PgConnection,
    entity_id: int,
    months: int = 12,
) -> dict:
    """월별 요약 (차트용) — opening balance + N개월 income/expense/net.

    Returns: { months: [...], available_months: ["YYYY-MM", ...] }
    """
    cur = conn.cursor()

    # 데이터가 있는 월 목록 조회
    cur.execute(
        """
        SELECT DISTINCT to_char(date_trunc('month', date), 'YYYY-MM') AS month
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'mercury_api', 'manual')
          AND is_duplicate = false
        ORDER BY month
        """,
        [entity_id],
    )
    available_months = [r[0] for r in cur.fetchall()]

    if not available_months:
        cur.close()
        return {"months": [], "available_months": []}

    # 최근 N개월만 사용
    target_months = available_months[-months:]
    first_month = target_months[0]  # "YYYY-MM"
    first_year, first_mon = int(first_month[:4]), int(first_month[5:7])

    # Opening balance for the first month
    opening = get_opening_balance(conn, entity_id, first_year, first_mon)

    # Monthly aggregation
    cur.execute(
        """
        SELECT
            to_char(date_trunc('month', date), 'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'mercury_api', 'manual')
          AND is_duplicate = false
          AND to_char(date_trunc('month', date), 'YYYY-MM') >= %s
        GROUP BY date_trunc('month', date)
        ORDER BY month
        """,
        [entity_id, first_month],
    )

    result_months = []
    running = opening
    for r in cur.fetchall():
        month_str = r[0]
        income = Decimal(str(r[1]))
        expense = Decimal(str(r[2]))
        net = income - expense
        month_opening = running
        running = running + net
        result_months.append({
            "month": month_str,
            "opening_balance": float(month_opening),
            "income": float(income),
            "expense": float(expense),
            "net": float(net),
            "closing_balance": float(running),
        })

    cur.close()

    return {
        "months": result_months,
        "available_months": available_months,
        "period_start_balance": float(opening),
        "period_end_balance": float(running) if result_months else float(opening),
    }


def get_card_total_net(conn: PgConnection, entity_id: int, year: int, month: int) -> Decimal:
    """특정 월 카드 순 사용액 (출금 - 환불)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0)
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('lotte_card', 'woori_card')
          AND date >= %s AND date < %s
          AND is_duplicate = false
        """,
        [entity_id, *build_date_range(year, month)],
    )
    result = Decimal(str(cur.fetchone()[0]))
    cur.close()
    return result


def get_forecast_cashflow(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
) -> dict:
    """예상 현금흐름 — forecasts + 시차 보정 + 실제 진행 비교.

    Returns: opening, forecast items, forecast_closing, actual progress, card timing, diff.
    """
    cur = conn.cursor()

    # 1. 기초잔고 (전월 확정 기말)
    opening = get_opening_balance(conn, entity_id, year, month)

    # 2. Forecast 항목 조회
    cur.execute(
        """
        SELECT id, category, subcategory, type, forecast_amount, actual_amount,
               is_recurring, note
        FROM forecasts
        WHERE entity_id = %s AND year = %s AND month = %s
        ORDER BY type, category
        """,
        [entity_id, year, month],
    )
    items = fetch_all(cur)

    # 3. Forecast 합산 (카드 카테고리 제외한 일반 입출금)
    forecast_income = Decimal("0")
    forecast_expense = Decimal("0")
    forecast_card_usage = Decimal("0")

    for item in items:
        amt = Decimal(str(item["forecast_amount"]))
        if item["type"] == "in":
            forecast_income += amt
        else:  # out
            if item["category"] == "카드사용":
                forecast_card_usage += amt
            else:
                forecast_expense += amt

    # 4. 카드 시차 보정
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    prev_card_net = get_card_total_net(conn, entity_id, prev_year, prev_month)

    # 당월 예상 카드 사용: forecast에 있으면 사용, 없으면 전월 실적 fallback
    curr_card_actual = get_card_total_net(conn, entity_id, year, month)
    curr_card_estimate = forecast_card_usage if forecast_card_usage > 0 else prev_card_net

    timing_adj = calc_card_timing_adjustment(prev_card_net, curr_card_estimate)

    # 5. 예상 기말
    forecast_closing = calc_forecast_closing(
        opening_balance=opening,
        forecast_income=forecast_income,
        forecast_expense=forecast_expense,
        forecast_card_usage=curr_card_estimate,
        card_timing_adjustment=timing_adj,
    )

    # 6. 실제 진행 기준 기말 (은행 거래 기준)
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'mercury_api', 'manual')
          AND date >= %s AND date < %s
          AND is_duplicate = false
        """,
        [entity_id, *build_date_range(year, month)],
    )
    row = cur.fetchone()
    actual_income = Decimal(str(row[0]))
    actual_expense = Decimal(str(row[1]))
    actual_closing = opening + actual_income - actual_expense

    diff = actual_closing - forecast_closing

    cur.close()

    return {
        "year": year,
        "month": month,
        "entity_id": entity_id,
        "opening_balance": float(opening),
        "forecast_income": float(forecast_income),
        "forecast_expense": float(forecast_expense),
        "forecast_card_usage": float(curr_card_estimate),
        "card_timing": {
            "prev_month_card": float(prev_card_net),
            "curr_month_card_actual": float(curr_card_actual),
            "curr_month_card_estimate": float(curr_card_estimate),
            "adjustment": float(timing_adj),
        },
        "forecast_closing": float(forecast_closing),
        "actual_income": float(actual_income),
        "actual_expense": float(actual_expense),
        "actual_closing": float(actual_closing),
        "diff": float(diff),
        "items": [
            {
                "id": i["id"],
                "category": i["category"],
                "subcategory": i["subcategory"],
                "type": i["type"],
                "forecast_amount": float(i["forecast_amount"]),
                "actual_amount": float(i["actual_amount"]) if i["actual_amount"] else None,
                "is_recurring": i["is_recurring"],
                "note": i["note"],
            }
            for i in items
        ],
    }

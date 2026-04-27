"""Cashflow service — 기초잔고 역산, 일별 잔고 추적, 월별 요약, 카드비용 그룹핑.

순수 계산 함수 (build_daily_rows, aggregate_monthly_summary, group_card_expenses)와
DB 조회 함수 (get_actual_cashflow, get_monthly_summary, get_card_expenses)를 분리.
"""

import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from psycopg2.extensions import connection as PgConnection

from backend.utils.db import build_date_range, fetch_all
from backend.utils.timezone import today_kst


# ── source_type 분류 ─────────────────────────────────
# Excel 업로드 + Codef API pull + 외부 연동 모두 포함
BANK_SOURCES = (
    "woori_bank", "codef_woori_bank", "codef_ibk_bank",
    "mercury_api", "manual",
)
CARD_SOURCES = (
    "lotte_card", "woori_card", "shinhan_card",
    "codef_lotte_card", "codef_woori_card", "codef_shinhan_card",
)


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
            "internal_account_id": tx.get("internal_account_id"),
            "internal_account_name": tx.get("internal_account_name"),
            "internal_account_parent_id": tx.get("internal_account_parent_id"),
            "parent_account_name": tx.get("parent_account_name"),
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
    """카드 시차 보정 = 당월 카드 예상 - 전월 카드 사용(확정).

    음수 → 전월 사용이 더 많아 카드대금 결제 부담 증가 (통장에서 더 빠짐).
    양수 → 당월 사용이 더 많아 카드대금 결제 부담 감소 (통장에서 덜 빠짐).
    """
    return curr_month_card - prev_month_card


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


def clamp_day_to_month(day: int, year: int, month: int) -> int:
    """day(1-31) 를 (year, month) 의 last_day 로 clamp (예: 4월 31일 → 30일).

    P1-5: payment_day / expected_day 가 31인 항목을 4월/6월/9월/11월(30일까지) 또는
    2월(28~29일)에서 동일하게 마지막 날로 처리. predicted_ending 합성 분기와
    generate_daily_schedule 가 같은 helper 사용 → 일관성 보장.
    """
    last_day = calendar.monthrange(year, month)[1]
    return min(max(1, int(day)), last_day)


def predicted_ending_mode(
    as_of: date,
    month_start: date,
    month_end: date,
) -> str:
    """Predicted-ending 합성 모드 결정 (pure function).

    - "completed":   조회 월이 이미 지나감 → predicted = actual_closing (100% 실제)
    - "future":      아직 시작 전인 월 → predicted = adjusted_forecast_closing (100% 예상)
    - "progressive": 월 진행 중 (마지막 날 포함) → 어제까지 실제 + 오늘 이후 예상

    P0-2: 오늘이 마지막 날인 경우 ("today == last_day")는 progressive 로 처리해야
    expected_day == last_day 인 forecast 가 import 되지 않아도 누락되지 않음.
    "as_of > month_end" 만 completed (한 칸 지난 월) 로 분류.
    """
    if as_of > month_end:
        return "completed"
    if as_of < month_start:
        return "future"
    return "progressive"


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


def get_opening_balance(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
    _allow_predicted_fallback: bool = True,
) -> Decimal:
    """해당 월 기초잔고 조회.

    정책:
    - 전월이 이미 종료된 경우 (today > prev_month_end): balance_snapshots 기반 "확정" 값
    - 전월이 아직 진행 중인 경우 (today <= prev_month_end): 전월 predicted_ending (시계열 합성)
      → 월말까지 기다리지 않고도 다음 월 예상을 합리적으로 계산.
      → 4/30이 지나면 자동으로 snapshot 기반으로 전환.

    _allow_predicted_fallback=False: 재귀 방지용. 내부 호출(prev-month forecast 계산 시)에서 사용.
    """
    today = today_kst()
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    prev_last_day = calendar.monthrange(prev_year, prev_month)[1]
    prev_month_end = date(prev_year, prev_month, prev_last_day)

    # 전월 진행 중 + 재귀 허용 → 전월 predicted_ending 시도
    if _allow_predicted_fallback and today <= prev_month_end:
        try:
            prev_result = get_forecast_cashflow(conn, entity_id, prev_year, prev_month, as_of=today)
            return Decimal(str(prev_result["predicted_ending"]))
        except Exception:
            # predicted 계산 실패 시 snapshot으로 fallback (silent)
            pass

    # 전월 종료 OR fallback: balance_snapshots 기반
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
               t.source_type, t.internal_account_id,
               ia.name AS internal_account_name,
               ia.parent_id AS internal_account_parent_id,
               pia.name AS parent_account_name
        FROM transactions t
        LEFT JOIN internal_accounts ia ON t.internal_account_id = ia.id
        LEFT JOIN internal_accounts pia ON ia.parent_id = pia.id
        WHERE t.entity_id = %s
          AND t.source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
          AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
        ORDER BY t.date, t.id
        """,
        [entity_id, *build_date_range(year, month)],
    )
    rows = fetch_all(cur)
    cur.close()
    return rows


def get_card_transactions(conn: PgConnection, entity_id: int, year: int, month: int) -> list[dict]:
    """특정 월 카드 사용 내역 조회 (소스→회원→일자순).

    취소건(type='in', is_cancel=TRUE)도 포함 → group_card_expenses 가 refund/net 분리.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.date, t.type, t.amount, t.description, t.counterparty,
               t.source_type, t.member_id, t.is_cancel,
               m.name AS member_name,
               sa.name AS account_name, sa.code AS account_code
        FROM transactions t
        LEFT JOIN members m ON t.member_id = m.id
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE t.entity_id = %s
          AND t.source_type IN ('lotte_card', 'woori_card', 'shinhan_card', 'codef_lotte_card', 'codef_woori_card', 'codef_shinhan_card')
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
          AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
          AND is_duplicate = false
          AND (is_cancel IS NOT TRUE)
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
          AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
          AND is_duplicate = false
          AND (is_cancel IS NOT TRUE)
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


def get_active_card_settings(conn: PgConnection, entity_id: int) -> list[dict]:
    """card_settings에서 활성 카드 목록 조회 (ARCH-1)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT source_type, card_name, payment_day, statement_day, billing_start_day
        FROM card_settings
        WHERE entity_id = %s AND is_active = true
        ORDER BY payment_day
        """,
        [entity_id],
    )
    rows = fetch_all(cur)
    cur.close()
    return rows


def get_card_total_net(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
    source_type: Optional[str] = None,
) -> Decimal:
    """특정 월 카드 순 사용액 (정상 출금 - 취소/환불). source_type 지정 시 해당 카드 family 매칭.

    취소건은 parser/Codef에서 type='in' + is_cancel=TRUE 로 별도 row 삽입됨.
    따라서 cancel row를 WHERE 에서 제외하면 환불이 차감되지 않아 net 과대평가.
    SUM 식에서 type='in' 전체를 차감 (cancel 포함), type='out' 은 is_cancel=TRUE 만 제외.

    card_settings.source_type은 'lotte_card' 같은 bare 값이지만 실제 거래는
    'codef_lotte_card' (Codef API 동기화) 또는 'lotte_card' (Excel 업로드) 등
    복수 source_type으로 기록됨. 따라서 bare name과 codef_* 변형 모두 매칭.
    """
    cur = conn.cursor()
    if source_type:
        # family matching: bare + codef_ prefixed
        source_variants = [source_type]
        if not source_type.startswith("codef_"):
            source_variants.append(f"codef_{source_type}")
        else:
            # codef_lotte_card → also include lotte_card
            source_variants.append(source_type.replace("codef_", "", 1))
        cur.execute(
            """
            SELECT COALESCE(SUM(
                CASE
                    WHEN type = 'out' AND is_cancel IS NOT TRUE THEN amount
                    WHEN type = 'in' THEN -amount
                    ELSE 0
                END
            ), 0)
            FROM transactions
            WHERE entity_id = %s
              AND source_type = ANY(%s)
              AND date >= %s AND date < %s
              AND is_duplicate = false
            """,
            [entity_id, source_variants, *build_date_range(year, month)],
        )
    else:
        cur.execute(
            """
            SELECT COALESCE(SUM(
                CASE
                    WHEN type = 'out' AND is_cancel IS NOT TRUE THEN amount
                    WHEN type = 'in' THEN -amount
                    ELSE 0
                END
            ), 0)
            FROM transactions
            WHERE entity_id = %s
              AND source_type IN ('lotte_card', 'woori_card', 'shinhan_card', 'codef_lotte_card', 'codef_woori_card', 'codef_shinhan_card')
              AND date >= %s AND date < %s
              AND is_duplicate = false
            """,
            [entity_id, *build_date_range(year, month)],
        )
    result = Decimal(str(cur.fetchone()[0]))
    cur.close()
    return result


def _split_forecasts_by_today(
    items: list[dict],
    today_day: Optional[int],
    actual_by_account: Optional[dict] = None,
) -> dict:
    """forecast 항목을 today_day 기준으로 과거/미래로 분리.

    분류 정책:
    - expected_day < today_day → past (이미 지나감 — 실제 거래로 대체, remaining 제외)
    - expected_day >= today_day → remaining (미래 — 전액 예상)
    - expected_day IS NULL → remaining에 "미실현분(=max(0, forecast-actual))"만 포함
      이유: NULL-day 구독/정기 지출은 월 중 이미 결제됐을 수 있음.

    카드 vs 은행 판별:
    - forecast.payment_method='bank'이지만 실제 거래가 주로 카드이면
      실질적으로 카드 지출. bank 예상 기말에는 영향 없고 timing_adj로 처리됨.
      → remaining_expense 대신 remaining_card로 분류하거나 제외.
    """
    past_in = Decimal("0"); past_expense = Decimal("0"); past_card = Decimal("0")
    rem_in = Decimal("0"); rem_expense = Decimal("0"); rem_card = Decimal("0")
    for item in items:
        forecast_amt = Decimal(str(item["forecast_amount"]))
        exp_day = item.get("expected_day")
        is_past = (today_day is not None) and (exp_day is not None) and (int(exp_day) < int(today_day))

        # 계정별 실제 결제 분포 (bank vs card)
        acct_id = item.get("internal_account_id")
        bank_actual = Decimal("0"); card_actual = Decimal("0")
        if acct_id and actual_by_account is not None:
            info = actual_by_account.get((acct_id, item["type"]), {})
            bank_actual = Decimal(str(info.get("bank", 0) or 0))
            card_actual = Decimal(str(info.get("card", 0) or 0))
        total_actual = bank_actual + card_actual

        # NULL-day: 미실현분만 remaining으로 처리
        effective_amt = forecast_amt
        if exp_day is None and acct_id:
            effective_amt = max(Decimal("0"), forecast_amt - total_actual)

        # 실제 결제 방식이 카드 주류(>50%)인데 forecast는 bank로 잡힌 경우 → 카드로 재분류
        is_actual_card_dominant = (total_actual > 0) and (card_actual > bank_actual)
        item_pm = item.get("payment_method", "bank")
        effective_pm = "card" if (is_actual_card_dominant and item_pm != "card") else item_pm

        if item["type"] == "in":
            if is_past:
                past_in += forecast_amt
            else:
                rem_in += effective_amt
        else:
            if effective_pm == "card":
                if is_past:
                    past_card += forecast_amt
                else:
                    rem_card += effective_amt
            else:
                if is_past:
                    past_expense += forecast_amt
                else:
                    rem_expense += effective_amt
    return {
        "past_in": past_in, "past_expense": past_expense, "past_card": past_card,
        "remaining_in": rem_in, "remaining_expense": rem_expense, "remaining_card": rem_card,
    }


def sync_forecast_actuals(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
) -> dict:
    """forecasts.actual_amount 를 transactions 합계로 동기화.

    P0-3: 이 작업은 read-only GET 경로에서 수행되지 않음 (race 방지).
    호출 시점: (1) Codef sync / Excel upload 직후, (2) POST /forecast/sync-actuals
    수동 endpoint, (3) 스케줄러 주기 동기화.

    내부계정 매핑된 거래만 대상 — 미매핑 거래는 unmapped 합계로 별도 표시.

    Returns: {"updated": <int>, "checked": <int>}
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.internal_account_id, t.type, SUM(t.amount) AS total
        FROM transactions t
        WHERE t.entity_id = %s
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
          AND t.internal_account_id IS NOT NULL
        GROUP BY t.internal_account_id, t.type
        """,
        [entity_id, year, month, year, month],
    )
    rows = cur.fetchall()
    updated = 0
    for acct_id, acct_type, total in rows:
        cur.execute(
            """
            UPDATE forecasts
            SET actual_amount = %s, updated_at = NOW()
            WHERE entity_id = %s AND year = %s AND month = %s
              AND internal_account_id = %s AND type = %s
              AND (actual_amount IS DISTINCT FROM %s)
            """,
            [float(total), entity_id, year, month, acct_id, acct_type, float(total)],
        )
        updated += cur.rowcount
    conn.commit()
    cur.close()
    return {"checked": len(rows), "updated": updated}


def get_forecast_cashflow(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
    as_of: Optional[date] = None,
) -> dict:
    """예상 현금흐름 — forecasts + 시차 보정 + 실제 진행 비교.

    as_of: 시계열 합성 기준일 (기본 today). 월 내이면 "실제 as_of까지 + 남은 기간 예상"으로 합성.

    Returns: opening, forecast items, forecast_closing, actual progress, card timing, diff.
    """
    cur = conn.cursor()

    # 시계열 합성 기준일
    as_of = as_of or today_kst()
    month_start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)
    if as_of < month_start:
        # 미래 월: 실제 발생분 없음, 전체를 예상으로 취급
        today_day_in_month: Optional[int] = 0
    elif as_of > month_end:
        # 지난 월: 전체 실제로 완료
        today_day_in_month = last_day
    else:
        today_day_in_month = as_of.day

    # 1. 기초잔고 — 전월 진행 중이면 predicted_ending fallback,
    #    아니면 balance_snapshots. 내부 호출 시 재귀 방지를 위해 _allow_predicted_fallback
    #    은 호출자가 명시하지 않으면 True가 기본값이므로, 여기서도 표준 동작 사용.
    opening = get_opening_balance(conn, entity_id, year, month)

    # opening 값의 출처 표시 — UI 라벨용 ("확정" vs "예상")
    _prev_year = year if month > 1 else year - 1
    _prev_month = month - 1 if month > 1 else 12
    _prev_last = calendar.monthrange(_prev_year, _prev_month)[1]
    _prev_end = date(_prev_year, _prev_month, _prev_last)
    opening_source = "predicted" if today_kst() <= _prev_end else "confirmed"

    # 2. Forecast 항목 조회 (expected_day, payment_method 포함)
    cur.execute(
        """
        SELECT f.id, f.category, f.subcategory, f.type, f.forecast_amount, f.actual_amount,
               f.is_recurring, f.note, f.internal_account_id, f.expected_day, f.payment_method,
               f.line_items,
               ia.name AS internal_account_name, ia.parent_id AS internal_account_parent_id,
               parent_ia.name AS parent_account_name
        FROM forecasts f
        LEFT JOIN internal_accounts ia ON f.internal_account_id = ia.id
        LEFT JOIN internal_accounts parent_ia ON ia.parent_id = parent_ia.id
        WHERE f.entity_id = %s AND f.year = %s AND f.month = %s
        ORDER BY f.type, f.category
        """,
        [entity_id, year, month],
    )
    items = fetch_all(cur)

    # 2-bis. 내부계정별 실제 거래 합계 (bank vs card 분리)
    cur.execute(
        """
        SELECT t.internal_account_id, t.type, ia.name AS account_name,
               SUM(CASE WHEN t.source_type IN ('woori_bank','codef_woori_bank','codef_ibk_bank','mercury_api','manual')
                        THEN t.amount ELSE 0 END) AS bank_total,
               SUM(CASE WHEN t.source_type IN ('lotte_card','woori_card','shinhan_card',
                                               'codef_lotte_card','codef_woori_card','codef_shinhan_card',
                                               'expenseone_card','gowid_api')
                        THEN t.amount ELSE 0 END) AS card_total,
               SUM(t.amount) AS total
        FROM transactions t
        LEFT JOIN internal_accounts ia ON ia.id = t.internal_account_id
        WHERE t.entity_id = %s
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
          AND t.internal_account_id IS NOT NULL
        GROUP BY t.internal_account_id, t.type, ia.name
        """,
        [entity_id, year, month, year, month],
    )
    actual_by_account = {}
    for row in cur.fetchall():
        actual_by_account[(row[0], row[1])] = {
            "name": row[2],
            "bank": float(row[3] or 0),
            "card": float(row[4] or 0),
            "total": float(row[5] or 0),
        }

    # 2-bis-b. (P0-3) actual_amount DB 동기화는 read-only GET 에서 수행하지 않음.
    # GET 경로에서 UPDATE+commit 시 사용자가 PATCH 로 수동 설정한 actual_amount 가
    # 페이지 로드만으로 덮어써지는 race 발생. sync_forecast_actuals() 를 데이터
    # import 경로(codef sync, excel upload)와 별도 POST endpoint 에서 호출.

    # 2-ter. 미매핑 거래 합계 (internal_account_id IS NULL, 은행 거래만)
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense,
            COUNT(*) AS cnt
        FROM transactions
        WHERE entity_id = %s
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND is_duplicate = false
          AND (is_cancel IS NOT TRUE)
          AND internal_account_id IS NULL
          AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
        """,
        [entity_id, year, month, year, month],
    )
    unmapped_row = cur.fetchone()
    unmapped_income = float(unmapped_row[0])
    unmapped_expense = float(unmapped_row[1])
    unmapped_count = int(unmapped_row[2])

    # 3. Forecast 합산 — raw payment_method 만 사용 (P1-1 baseline 안정화).
    #
    # 이전엔 effective_pm 재분류(작은 카드 거래 1건만 들어와도 계정 전체가 카드로 재분류) 가
    # forecast_closing baseline 까지 영향 → 실제 거래 도착마다 baseline 변동 → Codex 지적.
    # 수정: forecast_closing 은 forecasts.payment_method 그대로 합산 (안정).
    # 실제 카드 주류 재분류는 predicted_ending 합성 단계의 _split_forecasts_by_today() 가 처리.
    forecast_income = Decimal("0")
    forecast_expense = Decimal("0")
    forecast_card_usage = Decimal("0")
    warnings = []
    reclassified_count = 0  # 정보 표시 — predicted_ending 에서 재분류되는 항목 수

    for item in items:
        amt = Decimal(str(item["forecast_amount"]))
        if item["type"] == "in":
            forecast_income += amt
            continue

        db_pm = item.get("payment_method", "bank")
        if db_pm == "card":
            forecast_card_usage += amt
        else:
            forecast_expense += amt

        # 정보 표시용: 실제 거래 기준 카드 주류이면 predicted_ending 단계에서 재분류됨 — 카운트만.
        acct_id = item.get("internal_account_id")
        if acct_id:
            info = actual_by_account.get((acct_id, "out"), {})
            bank_a = Decimal(str(info.get("bank", 0) or 0))
            card_a = Decimal(str(info.get("card", 0) or 0))
            if (bank_a + card_a) > 0 and card_a > bank_a and db_pm != "card":
                reclassified_count += 1

    if reclassified_count > 0:
        warnings.append(
            f"{reclassified_count}개 예상항목이 실제 거래 기준 카드 결제로 잡혀 "
            f"예상 기말 합성에서만 재분류됩니다 (forecast_closing baseline 은 영향 없음)."
        )

    # 4. 카드별 시차 보정 (card_settings 기반 — ARCH-1)
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12

    cards = get_active_card_settings(conn, entity_id)
    if not cards:
        warnings.append("카드 설정이 없습니다. 카드 시차보정이 적용되지 않았습니다.")

    card_details = []
    total_prev_card = Decimal("0")
    total_curr_card = Decimal("0")
    for card in cards:
        prev = get_card_total_net(conn, entity_id, prev_year, prev_month, source_type=card["source_type"])
        curr = get_card_total_net(conn, entity_id, year, month, source_type=card["source_type"])
        total_prev_card += prev
        total_curr_card += curr
        card_details.append({
            "source_type": card["source_type"],
            "card_name": card["card_name"],
            "payment_day": card["payment_day"],
            "prev_month": float(prev),
            "curr_month": float(curr),
        })

    # 전체 카드 합산 (source_type 없이 조회 — fallback for when cards is empty)
    prev_card_net = total_prev_card if cards else get_card_total_net(conn, entity_id, prev_year, prev_month)
    curr_card_actual = total_curr_card if cards else get_card_total_net(conn, entity_id, year, month)
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

    # 5-bis. 조정 예상 기말 (미분류 반영)
    adjusted_forecast_closing = forecast_closing + Decimal(str(unmapped_income)) - Decimal(str(unmapped_expense))

    # 6. 실제 진행 기준 기말 (은행 거래 기준) — 월 전체
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
          AND date >= %s AND date < %s
          AND is_duplicate = false
          AND (is_cancel IS NOT TRUE)
        """,
        [entity_id, *build_date_range(year, month)],
    )
    row = cur.fetchone()
    actual_income = Decimal(str(row[0]))
    actual_expense = Decimal(str(row[1]))
    actual_closing = opening + actual_income - actual_expense

    diff = actual_closing - adjusted_forecast_closing

    # 6-ter. 시계열 합성 예상 기말 (today까지 실제 + 남은 기간 예상)
    # 이미 지나간 expected_day의 예상은 실제 발생분으로 대체 — 유령 예상 제거
    predicted_ending: Decimal
    mode = predicted_ending_mode(as_of, month_start, month_end)
    if mode == "completed":
        # 지난 월(이미 종료): 예상 기말 = 실제 월말 잔고 (100% 실제)
        predicted_ending = actual_closing
    elif mode == "future":
        # 월 시작 전: 예상 기말 = 기초 + 전체 예상 + 시차보정
        predicted_ending = adjusted_forecast_closing
    else:
        # 월 진행 중 (오늘이 last_day 인 경우 포함): 어제(today-1)까지 실제 + 오늘 이후(today 포함) 예상
        # "오늘" 건은 아직 실제 DB에 없을 수 있으므로 예상으로 취급.
        cutoff_date = date(year, month, today_day_in_month - 1) if today_day_in_month > 1 else None
        actual_in_to_today = Decimal("0"); actual_out_to_today = Decimal("0")
        if cutoff_date is not None:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN type='in' THEN amount ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN type='out' THEN amount ELSE 0 END), 0)
                FROM transactions
                WHERE entity_id = %s
                  AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
                  AND date >= %s AND date <= %s
                  AND is_duplicate = false
                  AND (is_cancel IS NOT TRUE)
                """,
                [entity_id, month_start, cutoff_date],
            )
            row = cur.fetchone()
            actual_in_to_today = Decimal(str(row[0]))
            actual_out_to_today = Decimal(str(row[1]))

        split = _split_forecasts_by_today(items, today_day_in_month, actual_by_account)

        # 카드 관련 bank 영향:
        # - 당월 카드 사용(rem_card) → 차월 청구 → 이번 달 bank 영향 없음 (제외)
        # - 전월 카드 청구 → 이번 달 bank에서 결제. payment_day가 이미 지났으면
        #   actual_to_yesterday에 포함(중복 방지), 아직 안 지났으면 remaining으로 추가.
        unpaid_prev_card = Decimal("0")
        if cards:
            # 각 카드의 전월 사용분 중 아직 결제 안 된(clamped payment_day > today) 것만 합산.
            # P1-5: payment_day=31 카드를 4월(30일까지) 같이 짧은 달에 처리할 때 clamp 미적용 시
            # today=30 인 경우 31>30=True 로 잘못 합산 → today 결제 거래와 중복 위험.
            # generate_daily_schedule 와 동일하게 clamp_day_to_month() 사용.
            for card in cards:
                raw_pd = card.get("payment_day") or 0
                if raw_pd <= 0:
                    continue
                clamped_pd = clamp_day_to_month(raw_pd, year, month)
                if clamped_pd > today_day_in_month:
                    src = card["source_type"]
                    prev_card_for_source = get_card_total_net(conn, entity_id, prev_year, prev_month, source_type=src)
                    unpaid_prev_card += prev_card_for_source
        else:
            # 카드 설정 없을 때 fallback: max payment_day 기준
            unpaid_prev_card = prev_card_net  # 보수적

        predicted_ending = (
            opening
            + actual_in_to_today - actual_out_to_today
            + split["remaining_in"] - split["remaining_expense"]
            - unpaid_prev_card
        )

    # 6-bis. 일별 실제 잔고 (그래프용 — 계단식)
    bank_txs = get_bank_transactions(conn, entity_id, year, month)
    actual_daily_balances = []
    running = opening
    last_actual_day = 0
    for tx in bank_txs:
        amt = Decimal(str(tx["amount"]))
        if tx["type"] == "in":
            running += amt
        else:
            running -= amt
        day = tx["date"].day if hasattr(tx["date"], "day") else int(str(tx["date"]).split("-")[2])
        last_actual_day = max(last_actual_day, day)
        actual_daily_balances.append({
            "day": day,
            "balance": float(running),
            "type": tx["type"],
            "amount": float(amt),
        })
    # 일별 집계: 최종 잔고 + 거래 목록
    daily_balance_by_day: dict[int, float] = {}
    daily_txs_by_day: dict[int, list[dict]] = defaultdict(list)
    for pt in actual_daily_balances:
        daily_balance_by_day[pt["day"]] = pt["balance"]
    for tx in bank_txs:
        day = tx["date"].day if hasattr(tx["date"], "day") else int(str(tx["date"]).split("-")[2])
        daily_txs_by_day[day].append({
            "description": tx.get("counterparty") or tx.get("description", ""),
            "amount": float(tx["amount"]),
            "type": tx["type"],
            "account": tx.get("internal_account_name"),
        })
    actual_daily_points = [
        {
            "day": d,
            "balance": b,
            "net_change": sum(
                t["amount"] if t["type"] == "in" else -t["amount"]
                for t in daily_txs_by_day.get(d, [])
            ),
            "transactions": daily_txs_by_day.get(d, []),
        }
        for d, b in sorted(daily_balance_by_day.items())
    ]

    # 예산 초과 항목 (실제 >= 예상 * 1.1)
    over_budget = []
    for i in items:
        if i.get("internal_account_id") and i["type"] == "out":
            forecast = float(i["forecast_amount"])
            actual = actual_by_account.get((i["internal_account_id"], "out"), {}).get("total", 0.0)
            if forecast > 0 and actual >= forecast * 1.1:
                over_budget.append({
                    "category": i["category"],
                    "internal_account_id": i["internal_account_id"],
                    "forecast": forecast,
                    "actual": actual,
                    "diff_pct": round((actual / forecast - 1) * 100, 1),
                })

    # 미예산 실제 거래 (forecast에 없는 계정의 거래)
    forecast_account_ids = {
        (i["internal_account_id"], i["type"])
        for i in items if i.get("internal_account_id")
    }
    unbudgeted_actuals = []
    for (acct_id, acct_type), info in actual_by_account.items():
        if (acct_id, acct_type) not in forecast_account_ids:
            unbudgeted_actuals.append({
                "internal_account_id": acct_id,
                "account_name": info["name"] or f"계정 #{acct_id}",
                "type": acct_type,
                "actual_amount": info["total"],
            })
    unbudgeted_actuals.sort(key=lambda x: x["actual_amount"], reverse=True)

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
            "card_details": card_details,
        },
        "card_settings": [
            {
                "source_type": c["source_type"],
                "card_name": c["card_name"],
                "payment_day": c["payment_day"],
            }
            for c in cards
        ],
        "forecast_closing": float(forecast_closing),
        "adjusted_forecast_closing": float(adjusted_forecast_closing),
        "predicted_ending": float(predicted_ending),
        "as_of_date": as_of.isoformat(),
        "today_day_in_month": today_day_in_month,
        "opening_source": opening_source,
        "actual_income": float(actual_income),
        "actual_expense": float(actual_expense),
        "actual_closing": float(actual_closing),
        "diff": float(diff),  # actual_closing - adjusted_forecast_closing (variance bridge baseline)
        # P1-3: predicted_ending 기준 차이 — KPI 카드/정합도 표시는 이 값으로 통일.
        "diff_vs_predicted": float(actual_closing - predicted_ending),
        "diff_pct_vs_predicted": (
            float((actual_closing - predicted_ending) / abs(predicted_ending) * 100)
            if predicted_ending != 0 else 0.0
        ),
        "actual_daily_points": actual_daily_points,
        "last_actual_day": last_actual_day,
        "over_budget": over_budget,
        "unbudgeted_actuals": unbudgeted_actuals,
        "unmapped_income": unmapped_income,
        "unmapped_expense": unmapped_expense,
        "unmapped_count": unmapped_count,
        "warnings": warnings,
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
                "internal_account_id": i.get("internal_account_id"),
                "internal_account_name": i.get("internal_account_name"),
                "internal_account_parent_id": i.get("internal_account_parent_id"),
                "parent_account_name": i.get("parent_account_name"),
                "expected_day": i.get("expected_day"),
                "payment_method": i.get("payment_method", "bank"),
                "line_items": i.get("line_items"),
                "actual_from_transactions": actual_by_account.get(
                    (i.get("internal_account_id"), i["type"]), {}
                ).get("total", 0.0) if i.get("internal_account_id") else None,
            }
            for i in items
        ],
    }


def get_variance_bridge(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
) -> dict:
    """예상 vs 실제 차이를 6개 버킷으로 분해하는 Variance Bridge.

    부호 규칙: 양수 = 실제가 예상보다 높음, 음수 = 실제가 예상보다 낮음.
    """
    cur = conn.cursor()

    # 기초잔고
    opening = get_opening_balance(conn, entity_id, year, month)

    # Forecast 합산
    cur.execute(
        """
        SELECT type, COALESCE(payment_method, 'bank'), SUM(forecast_amount)
        FROM forecasts
        WHERE entity_id = %s AND year = %s AND month = %s
        GROUP BY type, COALESCE(payment_method, 'bank')
        """,
        [entity_id, year, month],
    )
    forecast_income = Decimal("0")
    forecast_expense_bank = Decimal("0")
    forecast_expense_card = Decimal("0")
    for row in cur.fetchall():
        typ, pm, total = row
        if typ == "in":
            forecast_income += total
        else:
            if pm == "card":
                forecast_expense_card += total
            else:
                forecast_expense_bank += total

    # 실제 은행 거래 (전체)
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0),
            COUNT(*)
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
          AND date >= %s AND date < %s
          AND is_duplicate = false
          AND (is_cancel IS NOT TRUE)
        """,
        [entity_id, *build_date_range(year, month)],
    )
    actual_income, actual_expense_total, bank_tx_count = cur.fetchone()

    # 은행 출금 중 카드대금 결제 분리 (이중 계산 방지)
    cur.execute(
        """
        SELECT COALESCE(SUM(amount), 0), COUNT(*)
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
          AND date >= %s AND date < %s
          AND is_duplicate = false
          AND (is_cancel IS NOT TRUE)
          AND type = 'out'
          AND (counterparty ILIKE '%%롯데카드%%'
               OR counterparty ILIKE '%%우리카드%%'
               OR counterparty ILIKE '%%카드결제%%')
        """,
        [entity_id, *build_date_range(year, month)],
    )
    card_payment_via_bank, card_payment_count = cur.fetchone()
    actual_expense_bank = actual_expense_total - card_payment_via_bank

    # 카드 시차보정
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12

    prev_card_net = get_card_total_net(conn, entity_id, prev_year, prev_month)
    curr_card_actual = get_card_total_net(conn, entity_id, year, month)
    curr_card_estimate = forecast_expense_card if forecast_expense_card > 0 else prev_card_net
    forecast_timing = curr_card_estimate - prev_card_net

    # 미매핑 거래
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0),
            COUNT(*)
        FROM transactions
        WHERE entity_id = %s
          AND date >= %s AND date < %s
          AND is_duplicate = false
          AND (is_cancel IS NOT TRUE)
          AND internal_account_id IS NULL
          AND source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
        """,
        [entity_id, *build_date_range(year, month)],
    )
    unmapped_income, unmapped_expense, unmapped_count = cur.fetchone()

    # Forecast/actual closing 계산
    forecast_closing = (
        opening + forecast_income - forecast_expense_bank
        - curr_card_estimate + forecast_timing
    )
    adjusted_forecast = forecast_closing + unmapped_income - unmapped_expense
    actual_closing = opening + actual_income - actual_expense_total
    total_diff = actual_closing - adjusted_forecast

    # 6개 버킷 (부호: 양수=실제가 높음, 음수=실제가 낮음)
    b1_opening = Decimal("0")  # 같은 snapshot 사용하므로 0
    b2_income = actual_income - forecast_income
    b3_expense = -(actual_expense_bank - forecast_expense_bank)
    b4_card = prev_card_net - Decimal(str(card_payment_via_bank))
    b5_unmapped = unmapped_income - unmapped_expense
    bucket_sum = b1_opening + b2_income + b3_expense + b4_card + b5_unmapped
    b6_residual = total_diff - bucket_sum

    # Data quality checks
    cur.execute(
        "SELECT COUNT(DISTINCT source_type) FROM transactions "
        "WHERE entity_id = %s AND source_type IN ('lotte_card', 'woori_card', 'shinhan_card', 'codef_lotte_card', 'codef_woori_card', 'codef_shinhan_card') "
        "AND date >= %s AND date < %s AND is_duplicate = false "
        "AND (is_cancel IS NOT TRUE)",
        [entity_id, *build_date_range(year, month)],
    )
    card_source_count = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM card_settings WHERE entity_id = %s AND is_active = true",
        [entity_id],
    )
    card_setting_count = cur.fetchone()[0]
    missing_card_settings = max(0, card_source_count - card_setting_count)

    cur.execute(
        "SELECT COUNT(*) FROM forecasts "
        "WHERE entity_id = %s AND year = %s AND month = %s AND actual_amount IS NULL",
        [entity_id, year, month],
    )
    unresolved_forecasts = cur.fetchone()[0]

    # Missing snapshots: count bank accounts without prior-month snapshot
    cur.execute(
        """
        SELECT COUNT(DISTINCT account_name) FROM balance_snapshots
        WHERE entity_id = %s AND date <= make_date(%s, %s, 1)
        """,
        [entity_id, year, month],
    )
    snapshot_accounts = cur.fetchone()[0]
    missing_snapshots = max(0, 1 - snapshot_accounts)  # at least 1 account expected

    residual_threshold = max(abs(total_diff) * Decimal("0.2"), Decimal("100000"))
    high_unexplained = abs(b6_residual) > residual_threshold

    # 드릴다운: 입금/출금 항목별 forecast 매칭 여부
    # forecast에 등록된 internal_account_id → forecast_amount 매핑
    cur.execute(
        "SELECT internal_account_id, SUM(forecast_amount) FROM forecasts "
        "WHERE entity_id = %s AND year = %s AND month = %s AND type = 'out' "
        "AND internal_account_id IS NOT NULL GROUP BY internal_account_id",
        [entity_id, year, month],
    )
    forecast_out_map = {r[0]: float(r[1]) for r in cur.fetchall()}
    cur.execute(
        "SELECT internal_account_id, SUM(forecast_amount) FROM forecasts "
        "WHERE entity_id = %s AND year = %s AND month = %s AND type = 'in' "
        "AND internal_account_id IS NOT NULL GROUP BY internal_account_id",
        [entity_id, year, month],
    )
    forecast_in_map = {r[0]: float(r[1]) for r in cur.fetchall()}

    # 실제 은행 거래를 내부계정별로 집계 (카드대금 제외)
    cur.execute(
        """
        SELECT ia.name, t.internal_account_id, t.type,
               SUM(t.amount) AS total, COUNT(*) AS cnt
        FROM transactions t
        LEFT JOIN internal_accounts ia ON t.internal_account_id = ia.id
        WHERE t.entity_id = %s
          AND t.source_type IN ('woori_bank', 'codef_woori_bank', 'codef_ibk_bank', 'mercury_api', 'manual')
          AND t.date >= %s AND t.date < %s
          AND t.is_duplicate = false
          AND (t.is_cancel IS NOT TRUE)
          AND NOT (t.type = 'out' AND (
              t.counterparty ILIKE '%%롯데카드%%'
              OR t.counterparty ILIKE '%%우리카드%%'
              OR t.counterparty ILIKE '%%카드결제%%'))
        GROUP BY ia.name, t.internal_account_id, t.type
        ORDER BY total DESC
        """,
        [entity_id, *build_date_range(year, month)],
    )
    expense_drivers = []
    income_drivers = []
    for row in cur.fetchall():
        name, acct_id, tx_type, total, cnt = row
        forecast_map = forecast_out_map if tx_type == "out" else forecast_in_map
        forecast_amt = forecast_map.get(acct_id) if acct_id else None
        driver = {
            "account_name": name or "(미매핑)",
            "internal_account_id": acct_id,
            "amount": float(total),
            "tx_count": int(cnt),
            "forecasted": forecast_amt is not None,
            "forecast_amount": forecast_amt,
        }
        if tx_type == "out":
            expense_drivers.append(driver)
        else:
            income_drivers.append(driver)

    cur.close()

    buckets = [
        {"name": "기초잔고 차이", "amount": float(b1_opening),
         "detail": "예상과 실제 동일 소스 사용" if b1_opening == 0 else "스냅샷 차이"},
        {"name": "입금 차이", "amount": float(b2_income),
         "detail": f"실제 {float(actual_income):,.0f} - 예상 {float(forecast_income):,.0f}",
         "drivers": income_drivers},
        {"name": "출금 차이", "amount": float(b3_expense),
         "detail": f"실제 {float(actual_expense_bank):,.0f} - 예상 {float(forecast_expense_bank):,.0f} (카드대금 제외)",
         "drivers": expense_drivers},
        {"name": "카드 결제", "amount": float(b4_card),
         "detail": f"예상 카드대금 {float(prev_card_net):,.0f} - 실제 카드대금 {float(card_payment_via_bank):,.0f}"},
        {"name": "미매핑 거래", "amount": float(b5_unmapped),
         "detail": f"미분류 {unmapped_count}건 (입금 {float(unmapped_income):,.0f} - 출금 {float(unmapped_expense):,.0f})"},
        {"name": "기타/잔차", "amount": float(b6_residual),
         "detail": "버킷 간 오차 또는 미식별 항목"},
    ]

    return {
        "year": year,
        "month": month,
        "entity_id": entity_id,
        "forecast_closing": float(adjusted_forecast),
        "actual_closing": float(actual_closing),
        "total_diff": float(total_diff),
        "buckets": buckets,
        "data_quality": {
            "unmapped_count": int(unmapped_count),
            "missing_snapshots": int(missing_snapshots),
            "missing_card_settings": int(missing_card_settings),
            "unresolved_forecasts": int(unresolved_forecasts),
            "high_unexplained_variance": high_unexplained,
        },
    }


def generate_daily_schedule(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
) -> dict:
    """일별 잔고 시뮬레이션 생성 (TENSION-2: 백엔드에서 계산)."""
    forecast_data = get_forecast_cashflow(conn, entity_id, year, month)
    cards = get_active_card_settings(conn, entity_id)
    items = forecast_data["items"]
    days_in_month = calendar.monthrange(year, month)[1]

    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12

    # 날짜별 이벤트 매핑
    day_events: dict[int, list[dict]] = defaultdict(list)

    # 1. expected_day 지정 bank 항목 — P1-5 clamp_day_to_month 사용
    for item in items:
        if item.get("payment_method", "bank") == "bank" and item.get("expected_day"):
            day = clamp_day_to_month(item["expected_day"], year, month)
            day_events[day].append({
                "name": item["category"],
                "amount": item["forecast_amount"],
                "type": item["type"],
            })

    # 2. 카드 결제일 (card_settings 기반) — P1-5 clamp_day_to_month 사용
    for card in cards:
        prev_card = get_card_total_net(
            conn, entity_id, prev_year, prev_month, source_type=card["source_type"],
        )
        day = clamp_day_to_month(card["payment_day"], year, month)
        if prev_card > 0:
            day_events[day].append({
                "name": f"{card['card_name']} 결제",
                "amount": float(prev_card),
                "type": "out",
            })

    # 3. 날짜 없는 bank 항목: 균등 분배
    undated_out = sum(
        item["forecast_amount"] for item in items
        if item.get("payment_method", "bank") == "bank"
        and not item.get("expected_day")
        and item["type"] == "out"
    )
    undated_in = sum(
        item["forecast_amount"] for item in items
        if item.get("payment_method", "bank") == "bank"
        and not item.get("expected_day")
        and item["type"] == "in"
    )
    daily_undated_out = undated_out / days_in_month if days_in_month else 0
    daily_undated_in = undated_in / days_in_month if days_in_month else 0

    # 일별 잔고 + 경고
    balance = forecast_data["opening_balance"]
    points = [{"day": 0, "balance": round(balance), "events": []}]  # 기초잔고
    alerts = []
    min_balance_threshold = 0

    for d in range(1, days_in_month + 1):
        day_change = sum(
            -e["amount"] if e["type"] == "out" else e["amount"]
            for e in day_events.get(d, [])
        ) - daily_undated_out + daily_undated_in
        balance += day_change

        if balance < min_balance_threshold and not alerts:
            alerts.append({
                "day": d,
                "deficit": round(abs(balance)),
                "message": f"{d}일부터 잔고 부족 예상",
            })

        points.append({
            "day": d,
            "balance": round(balance),
            "events": day_events.get(d, []),
        })

    # Worst-case 시뮬레이션: 비정기 지출 1일, 비정기 수입 월말
    worst_day_events: dict[int, list[dict]] = defaultdict(list)

    # expected_day 있는 항목 + 카드 결제 (기본과 동일)
    for d_key, evts in day_events.items():
        worst_day_events[d_key].extend(evts)

    # 비정기 undated: 지출→1일, 수입→월말
    for item in items:
        if (item.get("payment_method", "bank") == "bank"
            and not item.get("expected_day")
            and not item.get("is_recurring", False)):
            target_day = days_in_month if item["type"] == "in" else 1
            worst_day_events[target_day].append({
                "name": item["category"],
                "amount": item["forecast_amount"],
                "type": item["type"],
            })

    # worst-case용 균등분배: 정기(recurring) undated만 (비정기는 이미 날짜 집중 배치)
    worst_undated_out = sum(
        item["forecast_amount"] for item in items
        if item.get("payment_method", "bank") == "bank"
        and not item.get("expected_day")
        and item["type"] == "out"
        and item.get("is_recurring", False)
    )
    worst_undated_in = sum(
        item["forecast_amount"] for item in items
        if item.get("payment_method", "bank") == "bank"
        and not item.get("expected_day")
        and item["type"] == "in"
        and item.get("is_recurring", False)
    )
    worst_daily_out = worst_undated_out / days_in_month if days_in_month else 0
    worst_daily_in = worst_undated_in / days_in_month if days_in_month else 0

    worst_balance = forecast_data["opening_balance"]
    worst_points = [{"day": 0, "balance": round(worst_balance)}]  # 기초잔고 (동일 시작점)
    for d in range(1, days_in_month + 1):
        day_change = sum(
            -e["amount"] if e["type"] == "out" else e["amount"]
            for e in worst_day_events.get(d, [])
        ) - worst_daily_out + worst_daily_in
        worst_balance += day_change
        worst_points.append({
            "day": d,
            "balance": round(worst_balance),
        })

    return {
        "year": year,
        "month": month,
        "entity_id": entity_id,
        "opening_balance": forecast_data["opening_balance"],
        "points": points,
        "alerts": alerts,
        "worst_case_points": worst_points,
        "card_settings": [
            {
                "source_type": c["source_type"],
                "card_name": c["card_name"],
                "payment_day": c["payment_day"],
            }
            for c in cards
        ],
        "min_balance_threshold": min_balance_threshold,
    }

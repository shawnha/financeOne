"""환율 서비스 — 기말/평균/역사적 환율 조회

공휴일 fallback: 직전 영업일 환율 사용 (7일 이내).
"""

from datetime import date, timedelta
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection


class ExchangeRateNotFoundError(Exception):
    pass


def get_closing_rate(
    conn: PgConnection,
    from_currency: str,
    to_currency: str,
    as_of_date: date,
) -> Decimal:
    """기말환율: as_of_date 또는 직전 영업일 환율 (7일 이내 fallback).

    역환율 자동 계산: from/to 못 찾으면 to/from 환율의 역수 반환.
    """
    if from_currency == to_currency:
        return Decimal("1")

    cur = conn.cursor()
    cur.execute(
        """
        SELECT rate, date FROM exchange_rates
        WHERE from_currency = %s AND to_currency = %s AND date <= %s
        ORDER BY date DESC LIMIT 1
        """,
        [from_currency, to_currency, as_of_date],
    )
    row = cur.fetchone()

    if not row:
        # 역방향 환율 fallback: to/from 의 1/rate
        cur.execute(
            """
            SELECT rate, date FROM exchange_rates
            WHERE from_currency = %s AND to_currency = %s AND date <= %s
            ORDER BY date DESC LIMIT 1
            """,
            [to_currency, from_currency, as_of_date],
        )
        inv_row = cur.fetchone()
        cur.close()
        if not inv_row:
            raise ExchangeRateNotFoundError(
                f"No exchange rate found for {from_currency}/{to_currency} on or before {as_of_date}"
            )
        inv_rate, inv_date = inv_row
        if (as_of_date - inv_date).days > 7:
            raise ExchangeRateNotFoundError(
                f"Exchange rate for {to_currency}/{from_currency} (inverse) is stale: "
                f"latest is {inv_date}, requested {as_of_date} (>7 days)"
            )
        return (Decimal("1") / Decimal(str(inv_rate))).quantize(Decimal("0.00000001"))

    cur.close()
    rate, rate_date = row
    if (as_of_date - rate_date).days > 7:
        raise ExchangeRateNotFoundError(
            f"Exchange rate for {from_currency}/{to_currency} is stale: "
            f"latest is {rate_date}, requested {as_of_date} (>7 days)"
        )

    return Decimal(str(rate))


def get_average_rate(
    conn: PgConnection,
    from_currency: str,
    to_currency: str,
    start_date: date,
    end_date: date,
) -> Decimal:
    """월평균환율: 기간 내 일별 환율 평균. 없으면 기말환율 fallback."""
    if from_currency == to_currency:
        return Decimal("1")

    cur = conn.cursor()
    cur.execute(
        """
        SELECT AVG(rate) FROM exchange_rates
        WHERE from_currency = %s AND to_currency = %s
          AND date >= %s AND date <= %s
        """,
        [from_currency, to_currency, start_date, end_date],
    )
    row = cur.fetchone()

    if row and row[0] is not None:
        cur.close()
        return Decimal(str(row[0])).quantize(Decimal("0.0001"))

    # 역방향 평균 fallback: to/from 의 1/avg
    cur.execute(
        """
        SELECT AVG(rate) FROM exchange_rates
        WHERE from_currency = %s AND to_currency = %s
          AND date >= %s AND date <= %s
        """,
        [to_currency, from_currency, start_date, end_date],
    )
    inv_row = cur.fetchone()
    cur.close()
    if inv_row and inv_row[0] is not None:
        return (Decimal("1") / Decimal(str(inv_row[0]))).quantize(Decimal("0.00000001"))

    # 최종 fallback: 기말환율
    return get_closing_rate(conn, from_currency, to_currency, end_date)


def get_historical_rate(
    conn: PgConnection,
    from_currency: str,
    to_currency: str,
    event_date: date,
) -> Decimal:
    """역사적환율: 특정 날짜의 환율. 자본 항목용 — 가용 환율 중 가장 가까운 것 사용 (180일 stale 허용)."""
    if from_currency == to_currency:
        return Decimal("1")

    cur = conn.cursor()
    # 1) event_date 이전/당일 환율 조회
    cur.execute(
        """
        SELECT rate, date FROM exchange_rates
        WHERE from_currency = %s AND to_currency = %s AND date <= %s
        ORDER BY date DESC LIMIT 1
        """,
        [from_currency, to_currency, event_date],
    )
    row = cur.fetchone()

    inverse = False
    if not row:
        cur.execute(
            """
            SELECT rate, date FROM exchange_rates
            WHERE from_currency = %s AND to_currency = %s AND date <= %s
            ORDER BY date DESC LIMIT 1
            """,
            [to_currency, from_currency, event_date],
        )
        row = cur.fetchone()
        inverse = True

    if not row:
        # 2) event_date 이후 환율 (가까운 미래) — 자본 발행일이 환율 시작일보다 앞일 때
        cur.execute(
            """
            SELECT rate, date FROM exchange_rates
            WHERE from_currency = %s AND to_currency = %s AND date > %s
            ORDER BY date ASC LIMIT 1
            """,
            [from_currency, to_currency, event_date],
        )
        row = cur.fetchone()
        if row:
            # 정방향 미래 매칭 — inverse fallback 흔적 reset
            inverse = False
        else:
            cur.execute(
                """
                SELECT rate, date FROM exchange_rates
                WHERE from_currency = %s AND to_currency = %s AND date > %s
                ORDER BY date ASC LIMIT 1
                """,
                [to_currency, from_currency, event_date],
            )
            row = cur.fetchone()
            inverse = True if row else inverse

    cur.close()
    if not row:
        raise ExchangeRateNotFoundError(
            f"No exchange rate available at all for {from_currency}/{to_currency} (event {event_date})"
        )

    rate = Decimal(str(row[0]))
    if inverse:
        rate = (Decimal("1") / rate).quantize(Decimal("0.00000001"))
    return rate

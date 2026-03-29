"""수출입은행 Open API 환율 수집기

API 문서: https://www.koreaexim.go.kr/ir/HPHKIR020M01?apino=2
- 영업일에만 데이터 제공 (주말/공휴일 → 빈 응답)
- deal_bas_r: 매매기준율 (기준 환율)
- 하루 1000회 제한
"""

import logging
import os
from datetime import date, timedelta
from decimal import Decimal

import httpx
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

KOREAEXIM_URL = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"
TARGET_CURRENCIES = {"USD", "EUR"}


class KoreaeximApiError(Exception):
    pass


def parse_koreaexim_response(data: list[dict], rate_date: date) -> list[dict]:
    """API 응답에서 USD/KRW, EUR/KRW 환율만 추출."""
    rates = []
    for item in data:
        if item.get("result") != 1:
            continue
        cur_unit = item.get("cur_unit", "")
        if cur_unit not in TARGET_CURRENCIES:
            continue
        raw_rate = item.get("deal_bas_r", "0").replace(",", "")
        if not raw_rate or raw_rate == "0":
            continue
        rates.append({
            "date": rate_date,
            "from_currency": cur_unit,
            "to_currency": "KRW",
            "rate": Decimal(raw_rate),
            "source": "koreaexim",
        })
    return rates


def save_rates_to_db(conn: PgConnection, rates: list[dict]) -> int:
    """환율 데이터를 exchange_rates 테이블에 UPSERT."""
    if not rates:
        return 0
    cur = conn.cursor()
    for r in rates:
        cur.execute(
            """
            INSERT INTO exchange_rates (date, from_currency, to_currency, rate, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (date, from_currency, to_currency)
            DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source
            """,
            [r["date"], r["from_currency"], r["to_currency"], r["rate"], r["source"]],
        )
    conn.commit()
    cur.close()
    return len(rates)


def fetch_exchange_rates(
    conn: PgConnection,
    start_date: date,
    end_date: date,
    api_key: str | None = None,
) -> dict:
    """start_date ~ end_date 범위의 환율을 수출입은행 API에서 가져와 DB에 저장.

    Returns: {"fetched_dates": int, "saved_rates": int, "skipped_dates": int}
    """
    key = api_key or os.environ.get("KOREAEXIM_API_KEY", "")
    if not key:
        raise KoreaeximApiError("KOREAEXIM_API_KEY not set")

    total_saved = 0
    skipped = 0
    current = start_date
    fetched_dates = 0

    while current <= end_date:
        fetched_dates += 1
        search_date = current.strftime("%Y%m%d")
        resp = httpx.get(
            KOREAEXIM_URL,
            params={"authkey": key, "searchdate": search_date, "data": "AP01"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            raise KoreaeximApiError(
                f"API returned {resp.status_code} for {search_date}: {resp.text}"
            )

        data = resp.json()
        if not data:
            # 주말/공휴일 — 데이터 없음
            logger.info("No exchange rate data for %s (holiday/weekend)", search_date)
            skipped += 1
            current += timedelta(days=1)
            continue

        rates = parse_koreaexim_response(data, current)
        saved = save_rates_to_db(conn, rates)
        total_saved += saved
        logger.info("Saved %d rates for %s", saved, search_date)

        current += timedelta(days=1)

    return {
        "fetched_dates": fetched_dates,
        "saved_rates": total_saved,
        "skipped_dates": skipped,
    }

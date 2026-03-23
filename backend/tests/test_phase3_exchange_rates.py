"""Phase 3 환율 서비스 테스트"""

import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import MagicMock

from backend.services.exchange_rate_service import (
    get_closing_rate,
    get_average_rate,
    get_historical_rate,
    ExchangeRateNotFoundError,
)


class TestClosingRate:
    def test_exact_date(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = (Decimal("0.00075"), date(2026, 3, 31))

        rate = get_closing_rate(conn, "KRW", "USD", date(2026, 3, 31))
        assert rate == Decimal("0.00075")

    def test_holiday_fallback(self):
        """공휴일: 직전 영업일 환율 사용"""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        # 3/31 공휴일 → 3/29 금요일 환율 반환
        cur.fetchone.return_value = (Decimal("0.00076"), date(2026, 3, 29))

        rate = get_closing_rate(conn, "KRW", "USD", date(2026, 3, 31))
        assert rate == Decimal("0.00076")

    def test_stale_rate_raises(self):
        """7일 초과 → 에러"""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = (Decimal("0.00074"), date(2026, 3, 20))

        with pytest.raises(ExchangeRateNotFoundError, match="stale"):
            get_closing_rate(conn, "KRW", "USD", date(2026, 3, 31))

    def test_no_rate_raises(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = None

        with pytest.raises(ExchangeRateNotFoundError):
            get_closing_rate(conn, "KRW", "USD", date(2026, 3, 31))

    def test_same_currency_returns_one(self):
        conn = MagicMock()
        rate = get_closing_rate(conn, "USD", "USD", date(2026, 3, 31))
        assert rate == Decimal("1")


class TestAverageRate:
    def test_average_calculation(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = (Decimal("0.000755"),)

        rate = get_average_rate(conn, "KRW", "USD", date(2026, 1, 1), date(2026, 3, 31))
        assert rate == Decimal("0.0008")  # quantized to 4 decimals

    def test_empty_period_falls_back_to_closing(self):
        """기간 내 환율 없음 → 기말환율 fallback"""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        call_count = [0]
        def fetchone_se():
            call_count[0] += 1
            if call_count[0] == 1:
                return (None,)  # AVG returns NULL
            return (Decimal("0.00075"), date(2026, 3, 31))  # closing rate fallback

        cur.fetchone = fetchone_se
        rate = get_average_rate(conn, "KRW", "USD", date(2026, 1, 1), date(2026, 3, 31))
        assert rate == Decimal("0.00075")

    def test_same_currency(self):
        conn = MagicMock()
        rate = get_average_rate(conn, "KRW", "KRW", date(2026, 1, 1), date(2026, 3, 31))
        assert rate == Decimal("1")


class TestHistoricalRate:
    def test_delegates_to_closing(self):
        """역사적환율 = 해당 날짜의 closing rate"""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = (Decimal("0.00080"), date(2023, 1, 1))

        rate = get_historical_rate(conn, "KRW", "USD", date(2023, 1, 1))
        assert rate == Decimal("0.00080")

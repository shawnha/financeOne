"""수출입은행 API 환율 fetcher 테스트"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.services.exchange_rate_fetcher import (
    fetch_exchange_rates,
    parse_koreaexim_response,
    save_rates_to_db,
    KoreaeximApiError,
)


# 수출입은행 API 실제 응답 형태
SAMPLE_API_RESPONSE = [
    {
        "result": 1,
        "cur_unit": "USD",
        "cur_nm": "미 달러",
        "ttb": "1,448.48",
        "tts": "1,477.91",
        "deal_bas_r": "1,463.2",
        "bkpr": "1,463",
        "yy_efee_r": "0",
        "ten_dd_efee_r": "0",
        "kftc_deal_bas_r": "1,463.2",
        "kftc_bkpr": "1,463",
    },
    {
        "result": 1,
        "cur_unit": "EUR",
        "cur_nm": "유로",
        "ttb": "1,574.51",
        "tts": "1,606.48",
        "deal_bas_r": "1,590.5",
        "bkpr": "1,590",
        "kftc_deal_bas_r": "1,590.5",
        "kftc_bkpr": "1,590",
    },
    {
        "result": 1,
        "cur_unit": "JPY(100)",
        "cur_nm": "일본 엔",
        "deal_bas_r": "978.12",
    },
]


class TestParseKoreaeximResponse:
    def test_extracts_usd_and_eur(self):
        rates = parse_koreaexim_response(SAMPLE_API_RESPONSE, date(2026, 3, 28))
        assert len(rates) == 2
        usd = next(r for r in rates if r["from_currency"] == "USD")
        assert usd["to_currency"] == "KRW"
        assert usd["rate"] == Decimal("1463.2")
        assert usd["date"] == date(2026, 3, 28)

    def test_eur_rate(self):
        rates = parse_koreaexim_response(SAMPLE_API_RESPONSE, date(2026, 3, 28))
        eur = next(r for r in rates if r["from_currency"] == "EUR")
        assert eur["rate"] == Decimal("1590.5")

    def test_ignores_other_currencies(self):
        rates = parse_koreaexim_response(SAMPLE_API_RESPONSE, date(2026, 3, 28))
        cur_units = [r["from_currency"] for r in rates]
        assert "JPY(100)" not in cur_units
        assert "JPY" not in cur_units

    def test_empty_response(self):
        rates = parse_koreaexim_response([], date(2026, 3, 28))
        assert rates == []

    def test_api_error_result_code(self):
        """result != 1 이면 해당 항목 스킵"""
        error_response = [{"result": 2, "cur_unit": "USD", "deal_bas_r": "1,463.2"}]
        rates = parse_koreaexim_response(error_response, date(2026, 3, 28))
        assert rates == []


class TestSaveRatesToDb:
    def test_upserts_rates(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        rates = [
            {"date": date(2026, 3, 28), "from_currency": "USD", "to_currency": "KRW",
             "rate": Decimal("1463.2"), "source": "koreaexim"},
        ]
        count = save_rates_to_db(conn, rates)
        assert count == 1
        cur.execute.assert_called_once()
        conn.commit.assert_called_once()

    def test_empty_rates_no_commit(self):
        conn = MagicMock()
        count = save_rates_to_db(conn, [])
        assert count == 0
        conn.commit.assert_not_called()


class TestFetchExchangeRates:
    @patch("backend.services.exchange_rate_fetcher.httpx.get")
    def test_single_date(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_API_RESPONSE
        mock_get.return_value = mock_resp

        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        result = fetch_exchange_rates(
            conn, date(2026, 3, 28), date(2026, 3, 28), api_key="test-key"
        )
        assert result["fetched_dates"] == 1
        assert result["saved_rates"] == 2  # USD + EUR

    @patch("backend.services.exchange_rate_fetcher.httpx.get")
    def test_date_range(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_API_RESPONSE
        mock_get.return_value = mock_resp

        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        result = fetch_exchange_rates(
            conn, date(2026, 3, 27), date(2026, 3, 28), api_key="test-key"
        )
        assert result["fetched_dates"] == 2
        assert mock_get.call_count == 2

    @patch("backend.services.exchange_rate_fetcher.httpx.get")
    def test_api_failure_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        conn = MagicMock()
        with pytest.raises(KoreaeximApiError, match="500"):
            fetch_exchange_rates(
                conn, date(2026, 3, 28), date(2026, 3, 28), api_key="test-key"
            )

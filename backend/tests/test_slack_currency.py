"""Slack 메시지 환율 변환 테스트"""

import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from datetime import date


class TestConvertToKrw:
    def test_usd_to_krw(self):
        from backend.services.slack.message_parser import convert_to_krw
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = (Decimal("1400.00"), date(2026, 1, 15))
        result = convert_to_krw(11.0, "USD", date(2026, 1, 15), mock_conn)
        assert result == 15400.0

    def test_krw_passthrough(self):
        from backend.services.slack.message_parser import convert_to_krw
        result = convert_to_krw(35000, "KRW", date(2026, 1, 15), MagicMock())
        assert result == 35000

    def test_no_rate_returns_original(self):
        from backend.services.slack.message_parser import convert_to_krw
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = None
        result = convert_to_krw(11.0, "USD", date(2026, 1, 15), mock_conn)
        assert result == 11.0

    def test_none_amount(self):
        from backend.services.slack.message_parser import convert_to_krw
        result = convert_to_krw(None, "USD", date(2026, 1, 15), MagicMock())
        assert result is None

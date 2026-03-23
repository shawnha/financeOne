"""Phase 3 연결재무제표 테스트 — GAAP 변환, CTA, 연결 BS 항등식"""

import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import MagicMock, patch

from backend.services.gaap_conversion_service import convert_kgaap_to_usgaap
from backend.services.cta_service import translate_entity_to_usd


class TestGAAPConversion:
    def test_mapped_account_converts(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        # gaap_mapping 반환
        cur.fetchall.return_value = [
            (1, "1000", "Cash and Cash Equivalents", "Assets"),
        ]

        kgaap_balances = [
            {"account_id": 1, "code": "10100", "name": "현금", "category": "자산",
             "subcategory": "유동자산", "normal_side": "debit",
             "debit_total": 1000000, "credit_total": 0, "balance": 1000000},
        ]

        result = convert_kgaap_to_usgaap(conn, kgaap_balances)
        assert len(result) == 1
        assert result[0]["us_gaap_code"] == "1000"
        assert result[0]["is_mapped"] is True

    def test_unmapped_account_flagged(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchall.return_value = []  # 매핑 없음

        kgaap_balances = [
            {"account_id": 99, "code": "99999", "name": "Unknown", "category": "자산",
             "subcategory": "유동자산", "normal_side": "debit",
             "debit_total": 100, "credit_total": 0, "balance": 100},
        ]

        result = convert_kgaap_to_usgaap(conn, kgaap_balances)
        assert result[0]["is_mapped"] is False
        assert result[0]["us_gaap_code"] == "99999"  # K-GAAP 코드 유지


class TestCTACalculation:
    @patch("backend.services.cta_service.get_closing_rate")
    @patch("backend.services.cta_service.get_average_rate")
    @patch("backend.services.cta_service.get_historical_rate")
    @patch("backend.services.cta_service.convert_kgaap_to_usgaap")
    @patch("backend.services.cta_service.get_all_account_balances")
    def test_cta_basic(self, mock_balances, mock_gaap, mock_hist, mock_avg, mock_close):
        """CTA = 자산(기말) - 부채(기말) - 자본(역사적) - 순이익(평균)"""
        # 환율
        mock_close.return_value = Decimal("0.001")   # 1 KRW = 0.001 USD
        mock_avg.return_value = Decimal("0.00095")
        mock_hist.return_value = Decimal("0.0008")

        # 잔액 (KRW)
        all_balances = [
            {"account_id": 1, "code": "10100", "name": "현금", "category": "자산",
             "balance": 100000000},  # 1억 KRW
            {"account_id": 2, "code": "20100", "name": "매입채무", "category": "부채",
             "balance": 40000000},  # 4천만 KRW
            {"account_id": 3, "code": "30100", "name": "자본금", "category": "자본",
             "balance": 50000000},  # 5천만 KRW
        ]
        period_balances = [
            {"account_id": 4, "code": "40100", "name": "매출", "category": "수익",
             "balance": 20000000},  # 2천만 KRW
            {"account_id": 5, "code": "50200", "name": "급여", "category": "비용",
             "balance": 10000000},  # 1천만 KRW
        ]
        mock_balances.side_effect = [all_balances, period_balances]

        # GAAP 변환 (코드만 변경, 금액 동일)
        def gaap_convert(conn, bals):
            return [{
                **b,
                "us_gaap_code": b["code"],
                "us_gaap_name": b["name"],
                "us_gaap_category": {
                    "자산": "Assets", "부채": "Liabilities", "자본": "Equity",
                    "수익": "Revenue", "비용": "Expenses",
                }.get(b["category"], b["category"]),
                "is_mapped": True,
            } for b in bals]
        mock_gaap.side_effect = gaap_convert

        conn = MagicMock()
        result = translate_entity_to_usd(conn, entity_id=2, fiscal_year=2026,
                                          start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))

        # 자산: 1억 × 0.001 = 100,000 USD
        # 부채: 4천만 × 0.001 = 40,000 USD
        # 자본: 5천만 × 0.0008 = 40,000 USD
        # 순이익: (2천만 - 1천만) × 0.00095 = 9,500 USD
        # CTA = 100,000 - 40,000 - 40,000 - 9,500 = 10,500 USD

        assert result["summary"]["total_assets_usd"] == 100000.0
        assert result["summary"]["total_liabilities_usd"] == 40000.0
        assert result["summary"]["total_equity_usd"] == 40000.0
        assert result["summary"]["net_income_usd"] == 9500.0
        assert result["cta_amount"] == 10500.0

    @patch("backend.services.cta_service.get_closing_rate")
    @patch("backend.services.cta_service.get_average_rate")
    @patch("backend.services.cta_service.get_historical_rate")
    @patch("backend.services.cta_service.convert_kgaap_to_usgaap")
    @patch("backend.services.cta_service.get_all_account_balances")
    def test_cta_zero_when_no_balances(self, mock_balances, mock_gaap, mock_hist, mock_avg, mock_close):
        """잔액 없으면 CTA = 0"""
        mock_close.return_value = Decimal("0.001")
        mock_avg.return_value = Decimal("0.001")
        mock_hist.return_value = Decimal("0.001")
        mock_balances.side_effect = [[], []]
        mock_gaap.side_effect = lambda conn, bals: bals

        conn = MagicMock()
        result = translate_entity_to_usd(conn, entity_id=2, fiscal_year=2026,
                                          start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        assert result["cta_amount"] == 0.0

    @patch("backend.services.cta_service.get_closing_rate")
    @patch("backend.services.cta_service.get_average_rate")
    @patch("backend.services.cta_service.get_historical_rate")
    @patch("backend.services.cta_service.convert_kgaap_to_usgaap")
    @patch("backend.services.cta_service.get_all_account_balances")
    def test_rates_correct_per_category(self, mock_balances, mock_gaap, mock_hist, mock_avg, mock_close):
        """자산=기말, 부채=기말, 자본=역사적, 수익/비용=평균"""
        mock_close.return_value = Decimal("0.001")
        mock_avg.return_value = Decimal("0.002")
        mock_hist.return_value = Decimal("0.003")

        all_balances = [
            {"account_id": 1, "code": "10100", "name": "현금", "category": "자산", "balance": 1000},
            {"account_id": 2, "code": "20100", "name": "매입채무", "category": "부채", "balance": 500},
            {"account_id": 3, "code": "30100", "name": "자본금", "category": "자본", "balance": 300},
        ]
        period_balances = [
            {"account_id": 4, "code": "40100", "name": "매출", "category": "수익", "balance": 200},
        ]
        mock_balances.side_effect = [all_balances, period_balances]

        def gaap_convert(conn, bals):
            cat_map = {"자산": "Assets", "부채": "Liabilities", "자본": "Equity", "수익": "Revenue"}
            return [{**b, "us_gaap_code": b["code"], "us_gaap_name": b["name"],
                      "us_gaap_category": cat_map.get(b["category"], b["category"]),
                      "is_mapped": True} for b in bals]
        mock_gaap.side_effect = gaap_convert

        conn = MagicMock()
        result = translate_entity_to_usd(conn, entity_id=2, fiscal_year=2026,
                                          start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))

        # 자산: 1000 × 0.001 = 1.00 (기말환율)
        assert result["summary"]["total_assets_usd"] == 1.0
        # 부채: 500 × 0.001 = 0.50 (기말환율)
        assert result["summary"]["total_liabilities_usd"] == 0.5
        # 자본: 300 × 0.003 = 0.90 (역사적환율)
        assert result["summary"]["total_equity_usd"] == 0.9
        # 순이익: 200 × 0.002 = 0.40 (평균환율)
        assert result["summary"]["net_income_usd"] == 0.4

        assert result["rates_used"]["closing"] == 0.001
        assert result["rates_used"]["average"] == 0.002
        assert result["rates_used"]["historical"] == 0.003

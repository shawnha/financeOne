"""Phase 2 재무제표 생성 테스트 — 항등식 검증"""

import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import MagicMock, patch

from backend.services.statement_generator import (
    generate_balance_sheet,
    generate_income_statement,
    generate_cash_flow_statement,
    generate_trial_balance,
    generate_deficit_treatment,
)


def _mock_insert_line_item(cur, stmt_id, item):
    """_insert_line_item을 모킹하여 실제 DB 없이 테스트."""
    pass


class TestBalanceSheet:
    @patch("backend.services.statements.helpers._insert_line_item", _mock_insert_line_item)
    @patch("backend.services.statements.balance_sheet.get_all_account_balances")
    def test_assets_equals_liabilities_plus_equity(self, mock_balances):
        """재무상태표 항등식: 자산 = 부채 + 자본"""
        # 설정: 자산 100만, 부채 60만, 자본 40만
        # 모든 기간 잔액 (to_date 호출)
        all_balances = [
            {"account_id": 1, "code": "10100", "name": "현금", "category": "자산",
             "subcategory": "유동자산", "normal_side": "debit",
             "debit_total": 1000000, "credit_total": 0, "balance": 1000000},
            {"account_id": 2, "code": "20100", "name": "매입채무", "category": "부채",
             "subcategory": "유동부채", "normal_side": "credit",
             "debit_total": 0, "credit_total": 600000, "balance": 600000},
            {"account_id": 3, "code": "30100", "name": "자본금", "category": "자본",
             "subcategory": "자본금", "normal_side": "credit",
             "debit_total": 0, "credit_total": 400000, "balance": 400000},
        ]
        # 기간 잔액 (수익/비용 없음 → 당기순이익 0)
        period_balances = []

        mock_balances.side_effect = [all_balances, period_balances]

        conn = MagicMock()
        cur = MagicMock()

        result = generate_balance_sheet(
            conn, cur, stmt_id=1, entity_id=1, fiscal_year=2026,
            as_of_date=date(2026, 12, 31), start_date=date(2026, 1, 1),
        )

        assert result["is_balanced"] is True
        assert result["total_assets"] == 1000000
        assert result["total_liabilities"] == 600000
        assert result["total_equity"] == 400000

    @patch("backend.services.statements.helpers._insert_line_item", _mock_insert_line_item)
    @patch("backend.services.statements.balance_sheet.get_all_account_balances")
    def test_net_income_flows_to_retained_earnings(self, mock_balances):
        """당기순이익이 이익잉여금에 반영되어 균형 유지"""
        # 자산 150만, 부채 50만, 자본금 50만, 이익잉여금 0
        # 수익 80만, 비용 30만 → 당기순이익 50만
        # 자본 = 자본금 50 + 이익잉여금(0+50) = 100 → 자산 150 = 부채 50 + 자본 100
        all_balances = [
            {"account_id": 1, "code": "10100", "name": "현금", "category": "자산",
             "subcategory": "유동자산", "normal_side": "debit",
             "debit_total": 1500000, "credit_total": 0, "balance": 1500000},
            {"account_id": 2, "code": "20100", "name": "매입채무", "category": "부채",
             "subcategory": "유동부채", "normal_side": "credit",
             "debit_total": 0, "credit_total": 500000, "balance": 500000},
            {"account_id": 3, "code": "30100", "name": "자본금", "category": "자본",
             "subcategory": "자본금", "normal_side": "credit",
             "debit_total": 0, "credit_total": 500000, "balance": 500000},
            {"account_id": 4, "code": "30300", "name": "이익잉여금", "category": "자본",
             "subcategory": "이익잉여금", "normal_side": "credit",
             "debit_total": 0, "credit_total": 0, "balance": 0},
        ]
        period_balances = [
            {"account_id": 5, "code": "40100", "name": "매출", "category": "수익",
             "subcategory": "영업수익", "normal_side": "credit",
             "debit_total": 0, "credit_total": 800000, "balance": 800000},
            {"account_id": 6, "code": "50200", "name": "급여", "category": "비용",
             "subcategory": "판매비와관리비", "normal_side": "debit",
             "debit_total": 300000, "credit_total": 0, "balance": 300000},
        ]

        mock_balances.side_effect = [all_balances, period_balances]

        conn = MagicMock()
        cur = MagicMock()

        result = generate_balance_sheet(
            conn, cur, stmt_id=1, entity_id=1, fiscal_year=2026,
            as_of_date=date(2026, 12, 31), start_date=date(2026, 1, 1),
        )

        assert result["net_income"] == 500000
        assert result["is_balanced"] is True
        # 자본 총계 = 자본금 50만 + 이익잉여금(0+50만) = 100만
        assert result["total_equity"] == 1000000

    @patch("backend.services.statements.helpers._insert_line_item", _mock_insert_line_item)
    @patch("backend.services.statements.balance_sheet.get_all_account_balances")
    def test_empty_period_returns_zeros(self, mock_balances):
        """0건 기간 → 빈 재무제표 (0원)"""
        mock_balances.side_effect = [[], []]

        conn = MagicMock()
        cur = MagicMock()

        result = generate_balance_sheet(
            conn, cur, stmt_id=1, entity_id=1, fiscal_year=2026,
            as_of_date=date(2026, 12, 31), start_date=date(2026, 1, 1),
        )

        assert result["total_assets"] == 0
        assert result["total_liabilities"] == 0
        assert result["is_balanced"] is True


class TestIncomeStatement:
    @patch("backend.services.statements.helpers._insert_line_item", _mock_insert_line_item)
    @patch("backend.services.statements.income_statement.get_all_account_balances")
    def test_revenue_minus_expense_equals_net_income(self, mock_balances):
        mock_balances.return_value = [
            {"account_id": 1, "code": "40100", "name": "매출", "category": "수익",
             "subcategory": "영업수익", "normal_side": "credit",
             "debit_total": 0, "credit_total": 5000000, "balance": 5000000},
            {"account_id": 2, "code": "50200", "name": "급여", "category": "비용",
             "subcategory": "판매비와관리비", "normal_side": "debit",
             "debit_total": 3000000, "credit_total": 0, "balance": 3000000},
        ]

        conn = MagicMock()
        cur = MagicMock()

        result = generate_income_statement(
            conn, cur, stmt_id=1, entity_id=1,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )

        assert result["total_revenue"] == 5000000
        assert result["net_income"] == 2000000


class TestCashFlowStatement:
    @patch("backend.services.statements.helpers._insert_line_item", _mock_insert_line_item)
    def test_ending_equals_opening_plus_net(self):
        """기말 = 기초 + 순현금흐름, 독립 검증 포함"""
        conn = MagicMock()
        cur = MagicMock()

        # conn.cursor() 호출마다 새 cursor mock 반환 (inner_cur, inner_cur2)
        cursors = []
        call_count = [0]

        def make_cursor():
            inner_cur = MagicMock()
            fetch_count = [0]

            def fetchone_se():
                fetch_count[0] += 1
                idx = len(cursors)
                if idx == 1:
                    # first cursor: opening, inflows, outflows
                    if fetch_count[0] == 1:
                        return (Decimal("500000"),)  # opening cash
                    elif fetch_count[0] == 2:
                        return (Decimal("300000"),)  # cash inflows
                    elif fetch_count[0] == 3:
                        return (Decimal("100000"),)  # cash outflows
                elif idx == 2:
                    # second cursor: independent ending balance
                    return (Decimal("700000"),)  # actual ending = 500k + 300k - 100k
                return (Decimal("0"),)

            inner_cur.fetchone = fetchone_se
            cursors.append(inner_cur)
            return inner_cur

        conn.cursor.side_effect = make_cursor

        result = generate_cash_flow_statement(
            conn, cur, stmt_id=1, entity_id=1,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )

        assert result["opening_cash"] == 500000
        assert result["net_cash"] == 200000  # 300k - 100k
        assert result["ending_cash"] == 700000  # 500k + 200k
        assert result["loop_valid"] is True


class TestTrialBalance:
    @patch("backend.services.statements.helpers._insert_line_item", _mock_insert_line_item)
    @patch("backend.services.statements.trial_balance.get_all_account_balances")
    def test_debits_equal_credits(self, mock_balances):
        mock_balances.return_value = [
            {"account_id": 1, "code": "10100", "name": "현금", "category": "자산",
             "subcategory": "유동자산", "normal_side": "debit",
             "debit_total": 1000000, "credit_total": 500000, "balance": 500000},
            {"account_id": 2, "code": "20100", "name": "매입채무", "category": "부채",
             "subcategory": "유동부채", "normal_side": "credit",
             "debit_total": 200000, "credit_total": 500000, "balance": 300000},
            {"account_id": 3, "code": "40100", "name": "매출", "category": "수익",
             "subcategory": "영업수익", "normal_side": "credit",
             "debit_total": 0, "credit_total": 200000, "balance": 200000},
        ]

        conn = MagicMock()
        cur = MagicMock()

        result = generate_trial_balance(
            conn, cur, stmt_id=1, entity_id=1,
            as_of_date=date(2026, 12, 31),
        )

        assert result["total_debit"] == 1200000
        assert result["total_credit"] == 1200000
        assert result["is_balanced"] is True


class TestDeficitTreatment:
    @patch("backend.services.statements.helpers._insert_line_item", _mock_insert_line_item)
    @patch("backend.services.statements.deficit.get_all_account_balances")
    def test_deficit_detected(self, mock_balances):
        """이익잉여금 음수 시 결손금 감지"""
        # 전체 기간 잔액
        all_balances = [
            {"account_id": 1, "code": "30300", "name": "이익잉여금", "category": "자본",
             "subcategory": "이익잉여금", "normal_side": "credit",
             "debit_total": 500000, "credit_total": 0, "balance": -500000},
        ]
        # 당기
        period_balances = [
            {"account_id": 2, "code": "50200", "name": "급여", "category": "비용",
             "subcategory": "판매비와관리비", "normal_side": "debit",
             "debit_total": 200000, "credit_total": 0, "balance": 200000},
        ]

        mock_balances.side_effect = [all_balances, period_balances]

        conn = MagicMock()
        cur = MagicMock()

        result = generate_deficit_treatment(
            conn, cur, stmt_id=1, entity_id=1, fiscal_year=2026,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )

        assert result["is_deficit"] is True
        assert result["ending_retained"] == -700000  # -500000 + (-200000)

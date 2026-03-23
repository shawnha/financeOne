"""Phase 2 복식부기 엔진 테스트 — 순수 단위 테스트 (DB 없이)"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from datetime import date

from backend.services.bookkeeping_engine import (
    _quantize,
    create_journal_entry,
    create_journal_from_transaction,
    validate_trial_balance,
)


class TestQuantize:
    def test_rounds_half_up(self):
        assert _quantize(100.555) == Decimal("100.56")

    def test_rounds_two_decimals(self):
        assert _quantize(1000) == Decimal("1000.00")

    def test_handles_string(self):
        assert _quantize("99.999") == Decimal("100.00")

    def test_handles_large_amount(self):
        assert _quantize(1_000_000_000.12) == Decimal("1000000000.12")


class TestCreateJournalEntry:
    def _make_conn(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = [1]  # journal_entry_id = 1
        return conn, cur

    def test_balanced_entry_succeeds(self):
        conn, cur = self._make_conn()
        lines = [
            {"standard_account_id": 1, "debit_amount": 100, "credit_amount": 0},
            {"standard_account_id": 2, "debit_amount": 0, "credit_amount": 100},
        ]
        je_id = create_journal_entry(conn, entity_id=1, lines=lines, entry_date=date(2026, 1, 1))
        assert je_id == 1
        assert cur.execute.call_count == 3  # 1 header + 2 lines

    def test_imbalanced_entry_raises(self):
        conn, cur = self._make_conn()
        lines = [
            {"standard_account_id": 1, "debit_amount": 100, "credit_amount": 0},
            {"standard_account_id": 2, "debit_amount": 0, "credit_amount": 99},
        ]
        with pytest.raises(ValueError, match="imbalanced"):
            create_journal_entry(conn, entity_id=1, lines=lines, entry_date=date(2026, 1, 1))

    def test_empty_lines_raises(self):
        conn, _ = self._make_conn()
        with pytest.raises(ValueError, match="at least one line"):
            create_journal_entry(conn, entity_id=1, lines=[], entry_date=date(2026, 1, 1))

    def test_zero_total_raises(self):
        conn, _ = self._make_conn()
        lines = [
            {"standard_account_id": 1, "debit_amount": 0, "credit_amount": 0},
        ]
        # zero debit and credit → total is zero
        with pytest.raises(ValueError):
            create_journal_entry(conn, entity_id=1, lines=lines, entry_date=date(2026, 1, 1))

    def test_compound_entry_three_lines(self):
        """VAT 포함 거래: 비용 90 + 부가세 10 = 현금 100"""
        conn, cur = self._make_conn()
        lines = [
            {"standard_account_id": 10, "debit_amount": 90, "credit_amount": 0},  # expense
            {"standard_account_id": 11, "debit_amount": 10, "credit_amount": 0},  # VAT receivable
            {"standard_account_id": 1, "debit_amount": 0, "credit_amount": 100},  # cash
        ]
        je_id = create_journal_entry(conn, entity_id=1, lines=lines, entry_date=date(2026, 1, 1))
        assert je_id == 1

    def test_decimal_precision(self):
        """소수점 반올림 후 균형 확인 (원화에서는 드물지만 USD에서 발생)"""
        conn, cur = self._make_conn()
        lines = [
            {"standard_account_id": 1, "debit_amount": "33.33", "credit_amount": 0},
            {"standard_account_id": 2, "debit_amount": "33.33", "credit_amount": 0},
            {"standard_account_id": 3, "debit_amount": "33.34", "credit_amount": 0},
            {"standard_account_id": 4, "debit_amount": 0, "credit_amount": "100.00"},
        ]
        je_id = create_journal_entry(conn, entity_id=1, lines=lines, entry_date=date(2026, 1, 1))
        assert je_id == 1


class TestCreateJournalFromTransaction:
    def _make_conn_with_tx(self, tx_type="out", is_confirmed=True, std_account_id=10):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        # First call: SELECT transaction
        # Second call: SELECT existing journal
        # Third call: SELECT cash account
        # Fourth call: INSERT journal_entries
        call_count = [0]

        def side_effect(*args, **kwargs):
            pass

        def fetchone_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                # transaction row
                return (1, 1, date(2026, 1, 15), Decimal("50000"), tx_type,
                        "Test purchase", "Vendor", std_account_id, is_confirmed)
            elif call_count[0] == 2:
                return None  # no existing journal
            elif call_count[0] == 3:
                return (1,)  # cash account id
            elif call_count[0] == 4:
                return (99,)  # journal entry id
            return None

        cur.fetchone = fetchone_side_effect
        return conn, cur

    def test_expense_creates_correct_journal(self):
        conn, cur = self._make_conn_with_tx(tx_type="out")
        je_id = create_journal_from_transaction(conn, transaction_id=1)
        assert je_id == 99

    def test_income_creates_correct_journal(self):
        conn, cur = self._make_conn_with_tx(tx_type="in")
        je_id = create_journal_from_transaction(conn, transaction_id=1)
        assert je_id == 99

    def test_unconfirmed_raises(self):
        conn, cur = self._make_conn_with_tx(is_confirmed=False)
        with pytest.raises(ValueError, match="not confirmed"):
            create_journal_from_transaction(conn, transaction_id=1)

    def test_unmapped_raises(self):
        conn, cur = self._make_conn_with_tx(std_account_id=None)
        with pytest.raises(ValueError, match="no standard_account_id"):
            create_journal_from_transaction(conn, transaction_id=1)

    def test_not_found_raises(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = None
        with pytest.raises(ValueError, match="not found"):
            create_journal_from_transaction(conn, transaction_id=999)


class TestValidateTrialBalance:
    def test_balanced(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = (Decimal("100000"), Decimal("100000"))

        result = validate_trial_balance(conn, entity_id=1)
        assert result["is_balanced"] is True
        assert result["difference"] == 0.0

    def test_imbalanced(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = (Decimal("100000"), Decimal("99999"))

        result = validate_trial_balance(conn, entity_id=1)
        assert result["is_balanced"] is False
        assert result["difference"] == 1.0

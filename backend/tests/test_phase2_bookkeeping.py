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
    def _make_conn_with_tx(
        self,
        tx_type="out",
        is_confirmed=True,
        std_account_id=10,
        source_type="woori_bank",
        counterparty="Vendor",
        ap_lookup_needed=False,
    ):
        """fetchone 순서 (현재 함수 구현):
        1) transaction SELECT (10 fields incl source_type)
        2) existing journal_entries SELECT
        3) cash account SELECT
        4) (선택) accounts_payable SELECT — 카드 source 또는 카드대금 결제
        5) INSERT journal_entries returning id
        """
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        responses = [
            (1, 1, date(2026, 1, 15), Decimal("50000"), tx_type,
             "Test purchase", counterparty, std_account_id, is_confirmed, source_type),
            None,  # no existing journal
            (1,),  # cash account id
        ]
        if ap_lookup_needed:
            responses.append((291,))  # ap account id
        responses.append((99,))  # journal entry id

        idx = [0]

        def fetchone_side_effect():
            i = idx[0]
            idx[0] += 1
            if i < len(responses):
                return responses[i]
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


class TestAccrualBranches:
    """P3-1 발생주의 분개 분기 검증.

    카드 사용 → (차) 비용 / (대) 미지급비용
    카드 환불 → (차) 미지급비용 / (대) 비용
    은행→카드사 결제 → (차) 미지급비용 / (대) 현금
    그 외 은행 거래 → 기존 (차) 비용 / (대) 현금
    """

    def _make_conn(self, tx_type, source_type, counterparty, ap_lookup):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        responses = [
            (1, 1, date(2026, 1, 15), Decimal("50000"), tx_type,
             "desc", counterparty, 10, True, source_type),
            None,
            (1,),
        ]
        if ap_lookup:
            responses.append((291,))
        responses.append((99,))
        idx = [0]
        def fetchone_side_effect():
            i = idx[0]; idx[0] += 1
            return responses[i] if i < len(responses) else None
        cur.fetchone = fetchone_side_effect

        # 호출된 INSERT 분개 lines 캡처용 (cur.execute 는 MagicMock — call_args_list 로 사후 분석)
        captured = []
        return conn, cur, captured

    @staticmethod
    def _capture_lines(cur):
        """cur.execute 의 모든 호출 중 journal_entry_lines INSERT 만 추출."""
        lines = []
        for call in cur.execute.call_args_list:
            args = call.args
            if not args:
                continue
            sql = args[0]
            if "journal_entry_lines" in str(sql).lower() and len(args) > 1:
                lines.append(args[1])
        return lines

    def test_card_purchase_credits_accounts_payable(self):
        """카드 사용(out) → (차)std=10 / (대)미지급비용=291."""
        conn, cur, captured = self._make_conn(
            tx_type="out", source_type="codef_lotte_card",
            counterparty="Anthropic", ap_lookup=True,
        )
        je_id = create_journal_from_transaction(conn, transaction_id=1)
        assert je_id == 99
        captured = self._capture_lines(cur)
        assert len(captured) == 2
        debit_line, credit_line = captured[0], captured[1]
        assert debit_line[1] == 10  # 차변 std
        assert credit_line[1] == 291  # 대변 미지급비용

    def test_card_refund_reverses(self):
        """카드 취소/환불(in) → (차)미지급비용=291 / (대)std=10."""
        conn, cur, _ = self._make_conn(
            tx_type="in", source_type="codef_lotte_card",
            counterparty="Refund", ap_lookup=True,
        )
        create_journal_from_transaction(conn, transaction_id=1)
        captured = self._capture_lines(cur)
        assert captured[0][1] == 291  # 차변 미지급비용
        assert captured[1][1] == 10   # 대변 std

    def test_bank_card_payment_clears_payable(self):
        """은행에서 카드사로 출금 → (차)미지급비용=291 / (대)현금=1."""
        conn, cur, _ = self._make_conn(
            tx_type="out", source_type="woori_bank",
            counterparty="롯데카드(주)", ap_lookup=True,
        )
        create_journal_from_transaction(conn, transaction_id=1)
        captured = self._capture_lines(cur)
        assert captured[0][1] == 291  # 차변 미지급비용
        assert captured[1][1] == 1    # 대변 현금

    def test_bank_normal_expense_legacy_branch(self):
        """일반 은행 출금 (카드사 X) → 기존 (차)std=10 / (대)현금=1 유지."""
        conn, cur, _ = self._make_conn(
            tx_type="out", source_type="woori_bank",
            counterparty="스타벅스", ap_lookup=False,
        )
        create_journal_from_transaction(conn, transaction_id=1)
        captured = self._capture_lines(cur)
        assert captured[0][1] == 10  # 차변 std
        assert captured[1][1] == 1   # 대변 현금

    def test_is_card_payment_helper(self):
        from backend.services.bookkeeping_engine import _is_card_payment
        assert _is_card_payment("롯데카드(주)") is True
        assert _is_card_payment("우리카드") is True
        assert _is_card_payment("KB국민카드") is True
        assert _is_card_payment("스타벅스") is False
        assert _is_card_payment(None) is False
        assert _is_card_payment("") is False


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

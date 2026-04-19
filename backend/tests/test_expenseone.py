"""ExpenseOne 연동 단위 테스트 — duplicate detection, category fallback, date parsing.

Focus: 순수 로직만 단위 테스트. HTTP/DB 의존은 stub/mock.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from backend.services.integrations.expenseone import (
    ExpenseOneError,
    _category_fallback,
    _parse_date,
    _upsert_expense,
    PRESET_CATEGORY_HINTS,
)


# ── _parse_date ──────────────────────────────────────────


class TestParseDate:
    def test_date_string(self):
        assert _parse_date("2026-04-15") == "2026-04-15"

    def test_iso_timestamp_z(self):
        assert _parse_date("2026-04-15T09:30:00Z") == "2026-04-15"

    def test_iso_timestamp_offset(self):
        assert _parse_date("2026-04-15T09:30:00+09:00") == "2026-04-15"

    def test_empty(self):
        assert _parse_date("") is None

    def test_invalid(self):
        assert _parse_date("not-a-date") is None

    def test_none_safe(self):
        assert _parse_date(None) is None  # type: ignore[arg-type]


# ── _category_fallback ───────────────────────────────────


class TestCategoryFallback:
    def _make_name_map(self) -> dict:
        return {
            "odd": (100, 10),
            "마트/약국": (200, 20),
            "복리후생비": (300, 30),
        }

    def test_preset_odd_hints_match(self):
        cur = MagicMock()
        result = _category_fallback(cur, 2, "ODD", self._make_name_map())
        assert result is not None
        assert result["internal_account_id"] == 100
        assert result["match_type"] == "expenseone_category"

    def test_preset_mart_pharmacy(self):
        cur = MagicMock()
        result = _category_fallback(cur, 2, "마트/약국", self._make_name_map())
        assert result is not None
        assert result["internal_account_id"] == 200

    def test_direct_category_name_match(self):
        cur = MagicMock()
        result = _category_fallback(cur, 2, "복리후생비", self._make_name_map())
        assert result is not None
        assert result["internal_account_id"] == 300

    def test_ilike_fallback_via_db(self):
        """이름 정확 매칭 실패 시 ILIKE 쿼리로 폴백."""
        cur = MagicMock()
        cur.fetchone.return_value = (500, 50)
        result = _category_fallback(cur, 2, "알수없는카테고리", {})
        assert result is not None
        assert result["internal_account_id"] == 500
        assert result["match_type"] == "expenseone_category"

    def test_no_match(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = _category_fallback(cur, 2, "랜덤", {})
        assert result is None

    def test_preset_other_returns_none_without_db_match(self):
        """OTHER 프리셋은 힌트가 비어있음 → DB ILIKE로만 매칭 시도."""
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = _category_fallback(cur, 2, "OTHER", self._make_name_map())
        assert result is None


# ── _upsert_expense duplicate/fuzzy logic ────────────────


class TestUpsertExpense:
    def _sample_corporate_card(self) -> dict:
        """DB row 딕셔너리 (snake_case, expenseone 스키마 형식)."""
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "type": "CORPORATE_CARD",
            "status": "APPROVED",
            "title": "쿠팡 구매",
            "description": "사무용품",
            "amount": 52000,
            "category": "ODD",
            "transaction_date": "2026-04-15",
            "merchant_name": "쿠팡",
            "card_last_four": "1234",
            "is_urgent": False,
            "is_pre_paid": False,
            "submitter_name": "김철수",
            "submitter_email": "kim@hanah1.com",
        }

    def test_expense_id_exact_match_returns_duplicate(self):
        """Level 1: expense_id 이미 있으면 duplicate."""
        cur = MagicMock()
        cur.fetchone.side_effect = [(1,)]
        result = _upsert_expense(cur, 2, self._sample_corporate_card(), {})
        assert result == "duplicate"

    def test_fuzzy_match_enriches_existing(self):
        """Level 2: 날짜+금액+merchant ILIKE 매칭되면 enrich."""
        cur = MagicMock()
        cur.fetchone.side_effect = [None, (99,)]
        result = _upsert_expense(cur, 2, self._sample_corporate_card(), {})
        assert result == "enriched"
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("UPDATE transactions" in sql for sql in calls)

    def test_new_expense_with_category_match(self):
        """중복/fuzzy 없음 + category ODD 매칭 → inserted."""
        cur = MagicMock()
        cur.fetchone.side_effect = [None] * 10
        result = _upsert_expense(
            cur, 2, self._sample_corporate_card(), {"odd": (100, 10)}
        )
        assert result == "inserted"

    def test_invalid_date_raises(self):
        cur = MagicMock()
        exp = self._sample_corporate_card()
        exp["transaction_date"] = "not-a-date"
        exp["approved_at"] = "also-bad"
        with pytest.raises(ExpenseOneError):
            _upsert_expense(cur, 2, exp, {})

    def test_zero_amount_raises(self):
        cur = MagicMock()
        exp = self._sample_corporate_card()
        exp["amount"] = 0
        with pytest.raises(ExpenseOneError):
            _upsert_expense(cur, 2, exp, {})

    def test_deposit_request_type_uses_account_holder(self):
        """DEPOSIT_REQUEST는 counterparty로 account_holder를 쓴다."""
        cur = MagicMock()
        cur.fetchone.side_effect = [None] * 10
        exp = {
            "id": "00000000-0000-0000-0000-000000000002",
            "type": "DEPOSIT_REQUEST",
            "status": "APPROVED",
            "title": "외주비 지급",
            "amount": 1000000,
            "category": "기타",
            "transaction_date": "2026-04-14",
            "bank_name": "국민은행",
            "account_holder": "홍길동",
            "is_urgent": False,
            "is_pre_paid": True,
            "pre_paid_percentage": 50,
            "submitter_name": "박영희",
        }
        _upsert_expense(cur, 2, exp, {})
        insert_call = next(
            c for c in cur.execute.call_args_list
            if "INSERT INTO transactions" in c.args[0]
        )
        params = insert_call.args[1]
        assert params[4] == "홍길동"  # counterparty
        assert params[5] == "expenseone_deposit"  # source_type
        note_idx = next(i for i, p in enumerate(params) if isinstance(p, str) and "선지급" in p)
        assert "50%" in params[note_idx]


# ── PRESET_CATEGORY_HINTS 검증 ───────────────────────────


def test_preset_hints_structure():
    """프리셋 카테고리 힌트에 필수 키 존재."""
    assert "ODD" in PRESET_CATEGORY_HINTS
    assert "MART_PHARMACY" in PRESET_CATEGORY_HINTS
    assert "OTHER" in PRESET_CATEGORY_HINTS
    # OTHER는 빈 튜플 (fallback 힌트 없음)
    assert PRESET_CATEGORY_HINTS["OTHER"] == ()

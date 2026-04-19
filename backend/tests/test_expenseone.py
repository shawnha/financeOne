"""ExpenseOne 연동 단위 테스트 — duplicate detection, category fallback, date parsing.

Focus: 순수 로직만 단위 테스트. HTTP/DB 의존은 stub/mock.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from backend.services.integrations.expenseone import (
    ExpenseOneClient,
    ExpenseOneError,
    _category_fallback,
    _parse_date,
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


# ── ExpenseOneClient init ────────────────────────────────


class TestClientInit:
    def test_missing_url_raises(self):
        with pytest.raises(ExpenseOneError):
            ExpenseOneClient("", "key")

    def test_missing_key_raises(self):
        with pytest.raises(ExpenseOneError):
            ExpenseOneClient("https://x.supabase.co", "")

    def test_trailing_slash_stripped(self):
        client = ExpenseOneClient("https://x.supabase.co/", "key")
        assert client.base_url == "https://x.supabase.co/rest/v1"
        assert client.headers["apikey"] == "key"
        assert client.headers["Authorization"] == "Bearer key"
        client.close()


# ── _upsert_expense duplicate/fuzzy logic ────────────────


class TestUpsertExpense:
    def _make_client(self) -> ExpenseOneClient:
        return ExpenseOneClient("https://x.supabase.co", "key")

    def _sample_corporate_card(self) -> dict:
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "type": "CORPORATE_CARD",
            "status": "APPROVED",
            "title": "쿠팡 구매",
            "description": "사무용품",
            "amount": 52000,
            "category": "ODD",
            "transactionDate": "2026-04-15",
            "merchantName": "쿠팡",
            "cardLastFour": "1234",
            "isUrgent": False,
            "isPrePaid": False,
            "submitter": {"id": "u1", "name": "김철수", "email": "kim@hanah1.com"},
        }

    def test_expense_id_exact_match_returns_duplicate(self):
        """Level 1: expense_id 이미 있으면 duplicate."""
        client = self._make_client()
        cur = MagicMock()
        cur.fetchone.side_effect = [(1,)]  # expense_id 매칭 row 존재
        try:
            result = client._upsert_expense(cur, 2, self._sample_corporate_card(), {})
            assert result == "duplicate"
        finally:
            client.close()

    def test_fuzzy_match_enriches_existing(self):
        """Level 2: 날짜+금액+merchant ILIKE 매칭되면 enrich."""
        client = self._make_client()
        cur = MagicMock()
        # 1st fetchone: expense_id 없음 → None
        # 2nd fetchone: fuzzy match 기존 거래 id=99
        cur.fetchone.side_effect = [None, (99,)]
        try:
            result = client._upsert_expense(cur, 2, self._sample_corporate_card(), {})
            assert result == "enriched"
            # UPDATE 가 호출됐는지 확인
            calls = [c.args[0] for c in cur.execute.call_args_list]
            assert any("UPDATE transactions" in sql for sql in calls)
        finally:
            client.close()

    def test_new_expense_with_category_match(self):
        """중복/fuzzy 없음 + category ODD 매칭 → inserted."""
        client = self._make_client()
        cur = MagicMock()
        # expense_id(None), fuzzy(None), mapping cascade (exact×2, similar×1, keyword×1) 모두 None
        cur.fetchone.side_effect = [None] * 10
        try:
            result = client._upsert_expense(
                cur,
                2,
                self._sample_corporate_card(),
                {"odd": (100, 10)},
            )
            # mapping_service cascade 실패 → category fallback ODD → internal_account_id=100
            assert result == "inserted"
        finally:
            client.close()

    def test_invalid_date_raises(self):
        client = self._make_client()
        cur = MagicMock()
        exp = self._sample_corporate_card()
        exp["transactionDate"] = "not-a-date"
        exp["approvedAt"] = "also-bad"
        try:
            with pytest.raises(ExpenseOneError):
                client._upsert_expense(cur, 2, exp, {})
        finally:
            client.close()

    def test_zero_amount_raises(self):
        client = self._make_client()
        cur = MagicMock()
        exp = self._sample_corporate_card()
        exp["amount"] = 0
        try:
            with pytest.raises(ExpenseOneError):
                client._upsert_expense(cur, 2, exp, {})
        finally:
            client.close()

    def test_deposit_request_type_uses_account_holder(self):
        """DEPOSIT_REQUEST는 counterparty로 accountHolder를 쓴다."""
        client = self._make_client()
        cur = MagicMock()
        cur.fetchone.side_effect = [None] * 10
        exp = {
            "id": "00000000-0000-0000-0000-000000000002",
            "type": "DEPOSIT_REQUEST",
            "status": "APPROVED",
            "title": "외주비 지급",
            "amount": 1000000,
            "category": "기타",
            "transactionDate": "2026-04-14",
            "bankName": "국민은행",
            "accountHolder": "홍길동",
            "accountNumber": "111-222-333",
            "isUrgent": False,
            "isPrePaid": True,
            "prePaidPercentage": 50,
            "submitter": {"name": "박영희"},
        }
        try:
            client._upsert_expense(cur, 2, exp, {})
            # INSERT 호출에서 counterparty=홍길동이 들어갔는지 확인
            insert_call = next(
                c for c in cur.execute.call_args_list
                if "INSERT INTO transactions" in c.args[0]
            )
            params = insert_call.args[1]
            # 파라미터 순서: entity_id, date, amount, desc, counterparty, source_type, ...
            assert params[4] == "홍길동"  # counterparty
            assert params[5] == "expenseone_deposit"  # source_type
            # note에 선지급 정보 포함
            note_idx = next(i for i, p in enumerate(params) if isinstance(p, str) and "선지급" in p)
            assert "50%" in params[note_idx]
        finally:
            client.close()


# ── PRESET_CATEGORY_HINTS 검증 ───────────────────────────


def test_preset_hints_structure():
    """프리셋 카테고리 힌트에 필수 키 존재."""
    assert "ODD" in PRESET_CATEGORY_HINTS
    assert "MART_PHARMACY" in PRESET_CATEGORY_HINTS
    assert "OTHER" in PRESET_CATEGORY_HINTS
    # OTHER는 빈 튜플 (fallback 힌트 없음)
    assert PRESET_CATEGORY_HINTS["OTHER"] == ()

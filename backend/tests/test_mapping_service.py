"""mapping_service 테스트 — 5단계 캐스케이드 auto_map + learn"""

import pytest
from unittest.mock import MagicMock, patch


def _mock_cursor(fetchone_result=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_result
    return cur


# ── exact_match ───────────────────────────────────────────────


class TestExactMatch:
    def test_returns_mapping_when_rule_exists(self):
        from backend.services.mapping_service import exact_match
        cur = _mock_cursor(fetchone_result=(10, 20, 0.9))
        result = exact_match(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR")
        assert result == {"internal_account_id": 10, "standard_account_id": 20, "confidence": 0.9, "match_type": "exact"}

    def test_returns_none_when_no_rule(self):
        from backend.services.mapping_service import exact_match
        cur = _mock_cursor(fetchone_result=None)
        result = exact_match(cur, entity_id=2, counterparty="새로운거래처")
        assert result is None

    def test_returns_none_when_counterparty_is_none(self):
        from backend.services.mapping_service import exact_match
        cur = MagicMock()
        result = exact_match(cur, entity_id=2, counterparty=None)
        assert result is None
        cur.execute.assert_not_called()


# ── similar_match ─────────────────────────────────────────────


class TestSimilarMatch:
    def test_returns_match_above_threshold(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        cur.fetchone.return_value = (10, 20, 0.85, "OPENAI *CHATGPT SUB")
        result = similar_match(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", description=None)
        assert result is not None
        assert result["internal_account_id"] == 10
        assert result["match_type"] == "similar"

    def test_returns_none_below_threshold(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = similar_match(cur, entity_id=2, counterparty="완전다른거래처", description=None)
        assert result is None

    def test_returns_none_when_counterparty_empty(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        result = similar_match(cur, entity_id=2, counterparty=None, description=None)
        assert result is None
        cur.execute.assert_not_called()

    def test_combines_counterparty_and_description(self):
        from backend.services.mapping_service import similar_match
        cur = MagicMock()
        cur.fetchone.return_value = (10, 20, 0.72, "배달의민족")
        result = similar_match(cur, entity_id=2, counterparty="배민", description="배달의민족 결제")
        assert result is not None


# ── keyword_match ─────────────────────────────────────────────


class TestKeywordMatch:
    def test_returns_match_when_keyword_found_in_description(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        cur.fetchone.side_effect = [(10, 0.75), (20,)]
        result = keyword_match(cur, entity_id=2, counterparty=None, description="회식비 결제")
        assert result is not None
        assert result["internal_account_id"] == 10
        assert result["match_type"] == "keyword"

    def test_returns_none_when_no_keyword_matches(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = keyword_match(cur, entity_id=2, counterparty=None, description="특이한 거래")
        assert result is None

    def test_returns_none_when_no_description(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        result = keyword_match(cur, entity_id=2, counterparty=None, description=None)
        assert result is None
        cur.execute.assert_not_called()

    def test_searches_counterparty_too(self):
        from backend.services.mapping_service import keyword_match
        cur = MagicMock()
        cur.fetchone.side_effect = [(10, 0.75), (20,)]
        result = keyword_match(cur, entity_id=2, counterparty="택시비", description=None)
        assert result is not None


# ── ai_match ──────────────────────────────────────────────────


class TestAIMatch:
    def test_returns_match_from_ai(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        cur.fetchall.return_value = [
            (10, "급여", "인건비"),
            (11, "임차료", "고정비"),
            (12, "복리후생비", "인건비"),
        ]
        # fetchone calls: std_account lookup, learn_mapping_rule lookups
        cur.fetchone.side_effect = [
            (30,),   # standard_account_id for account 12
            None,    # learn: no existing rule
            (30,),   # learn: standard_account_id lookup
        ]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"internal_account_id": 12, "reasoning": "회식은 복리후생비"}')]
        with patch("backend.services.mapping_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response
            result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is not None
        assert result["internal_account_id"] == 12
        assert result["match_type"] == "ai"

    def test_returns_none_on_api_error(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        cur.fetchall.return_value = [(10, "급여", "인건비")]
        with patch("backend.services.mapping_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = Exception("API error")
            result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is None

    def test_returns_none_when_no_accounts(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        cur.fetchall.return_value = []
        result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is None

    def test_returns_none_when_ai_returns_invalid_account(self):
        from backend.services.mapping_service import ai_match
        cur = MagicMock()
        cur.fetchall.return_value = [(10, "급여", "인건비")]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"internal_account_id": 999, "reasoning": "추측"}')]
        with patch("backend.services.mapping_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response
            result = ai_match(cur, entity_id=2, counterparty="BBQ치킨", description="회식 결제")
        assert result is None


# ── cascade (auto_map_transaction) ────────────────────────────


class TestCascade:
    def test_exact_match_takes_priority(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        # exact_match query returns a hit
        cur.fetchone.return_value = (10, 20, 0.9)
        result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI", description="구독")
        assert result is not None
        assert result["match_type"] == "exact"

    def test_falls_through_to_similar(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,                              # exact match miss
            (10, 20, 0.75, "OPENAI CHATGPT"),  # similar match hit
        ]
        result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI CHAT", description=None)
        assert result is not None
        assert result["match_type"] == "similar"

    def test_falls_through_to_keyword(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        cur.fetchone.side_effect = [
            # exact_match skipped (counterparty=None)
            None,         # similar miss
            (10, 0.75),   # keyword hit
            (20,),        # standard_account_id lookup
        ]
        result = auto_map_transaction(cur, entity_id=2, counterparty=None, description="회식비 결제")
        assert result is not None
        assert result["match_type"] == "keyword"

    def test_returns_none_when_all_miss(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        result = auto_map_transaction(cur, entity_id=2, counterparty="???", description="???")
        assert result is None

    def test_returns_none_when_no_input(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        result = auto_map_transaction(cur, entity_id=2, counterparty=None, description=None)
        assert result is None
        cur.execute.assert_not_called()


# ── auto_map_transaction (backward compat) ────────────────────


class TestAutoMap:
    def test_returns_mapping_when_rule_exists(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = _mock_cursor(fetchone_result=(10, 20, 0.9))
        result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR")
        assert result["internal_account_id"] == 10
        assert result["standard_account_id"] == 20
        assert result["confidence"] == 0.9

    def test_returns_none_when_no_rule(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = _mock_cursor(fetchone_result=None)
        cur.fetchall.return_value = []
        result = auto_map_transaction(cur, entity_id=2, counterparty="새로운거래처")
        assert result is None

    def test_returns_none_when_counterparty_is_none(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        result = auto_map_transaction(cur, entity_id=2, counterparty=None)
        assert result is None
        cur.execute.assert_not_called()


# ── learn_mapping_rule ────────────────────────────────────────


class TestLearnRule:
    def test_inserts_new_rule(self):
        from backend.services.mapping_service import learn_mapping_rule
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,        # existing rule lookup
            (100,),      # standard_account_id from internal_accounts
        ]
        learn_mapping_rule(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)
        calls = [str(c) for c in cur.execute.call_args_list]
        assert any("INSERT INTO mapping_rules" in c for c in calls)

    def test_updates_existing_same_account(self):
        from backend.services.mapping_service import learn_mapping_rule
        cur = MagicMock()
        cur.fetchone.return_value = (1, 10, 0.85, 3)  # id, internal_account_id, confidence, hit_count
        learn_mapping_rule(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)
        calls = [str(c) for c in cur.execute.call_args_list]
        assert any("hit_count" in c and "UPDATE" in c for c in calls)

    def test_replaces_existing_different_account(self):
        from backend.services.mapping_service import learn_mapping_rule
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (1, 99, 0.9, 5),  # existing rule points to account 99
            (200,),            # standard_account_id for new internal_account 10
        ]
        learn_mapping_rule(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)
        calls = [str(c) for c in cur.execute.call_args_list]
        assert any("internal_account_id" in c and "UPDATE" in c for c in calls)

    def test_skips_when_counterparty_is_none(self):
        from backend.services.mapping_service import learn_mapping_rule
        cur = MagicMock()
        learn_mapping_rule(cur, entity_id=2, counterparty=None, internal_account_id=10)
        cur.execute.assert_not_called()


class TestAutoMapAndLearnFlow:
    def test_learn_then_auto_map(self):
        from backend.services.mapping_service import auto_map_transaction, learn_mapping_rule
        learn_cur = MagicMock()
        learn_cur.fetchone.side_effect = [
            None,    # no existing rule
            (20,),   # standard_account_id for internal_account 10
        ]
        learn_mapping_rule(learn_cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)
        insert_calls = [c for c in learn_cur.execute.call_args_list if "INSERT INTO mapping_rules" in str(c)]
        assert len(insert_calls) == 1

        map_cur = _mock_cursor(fetchone_result=(10, 20, 0.8))
        result = auto_map_transaction(map_cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR")
        assert result is not None
        assert result["internal_account_id"] == 10

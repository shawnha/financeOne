"""mapping_service 테스트 — auto_map + learn"""

import pytest
from unittest.mock import MagicMock


def _mock_cursor(fetchone_result=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_result
    return cur


class TestAutoMap:
    def test_returns_mapping_when_rule_exists(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = _mock_cursor(fetchone_result=(10, 20, 0.9))
        result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR")
        assert result == {"internal_account_id": 10, "standard_account_id": 20, "confidence": 0.9}

    def test_returns_none_when_no_rule(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = _mock_cursor(fetchone_result=None)
        result = auto_map_transaction(cur, entity_id=2, counterparty="새로운거래처")
        assert result is None

    def test_returns_none_when_counterparty_is_none(self):
        from backend.services.mapping_service import auto_map_transaction
        cur = MagicMock()
        result = auto_map_transaction(cur, entity_id=2, counterparty=None)
        assert result is None
        cur.execute.assert_not_called()


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

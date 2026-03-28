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

"""Phase 3 내부거래 감지/상계 테스트"""

import pytest
from unittest.mock import MagicMock, call
from datetime import date

from backend.services.intercompany_service import confirm_pair


class TestConfirmPair:
    def test_confirm_sets_intercompany_flags(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = (10, 20)  # transaction_a_id, transaction_b_id

        result = confirm_pair(conn, pair_id=1)
        assert result["confirmed"] is True

        # 3 SQL 실행: SELECT pair, UPDATE pair, UPDATE tx_a, UPDATE tx_b
        assert cur.execute.call_count == 4

    def test_confirm_not_found_raises(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = None

        with pytest.raises(ValueError, match="not found"):
            confirm_pair(conn, pair_id=999)

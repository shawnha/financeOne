"""slack_status 판정 + 그룹 매칭 완료 조건 테스트"""

import pytest
from backend.services.slack.thread_analyzer import resolve_slack_status


class TestResolveSlackStatus:
    def test_card_payment_always_done(self):
        result = resolve_slack_status("card_payment", False, {})
        assert result["slack_status"] == "done"

    def test_deposit_request_with_reaction(self):
        result = resolve_slack_status("deposit_request", True, {})
        assert result["slack_status"] == "done"

    def test_deposit_request_with_thread_done(self):
        result = resolve_slack_status("deposit_request", False, {"deposit_done": True})
        assert result["slack_status"] == "done"

    def test_deposit_request_no_signal(self):
        result = resolve_slack_status("deposit_request", False, {})
        assert result["slack_status"] == "pending"

    def test_cancelled_overrides_all(self):
        result = resolve_slack_status("card_payment", True, {"cancelled": True})
        assert result["slack_status"] == "cancelled"
        assert result["is_cancelled"] is True

    def test_expense_share_with_reaction(self):
        result = resolve_slack_status("expense_share", True, {})
        assert result["slack_status"] == "done"

    def test_other_no_signal(self):
        result = resolve_slack_status("other", False, {})
        assert result["slack_status"] == "pending"

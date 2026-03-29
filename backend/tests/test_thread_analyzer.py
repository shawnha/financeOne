"""thread_analyzer 테스트 — 쓰레드 이벤트 감지"""

import pytest


class TestDetectDepositDone:
    def test_deposit_complete(self):
        from backend.services.slack.thread_analyzer import detect_deposit_done
        assert detect_deposit_done("입금완료") is True

    def test_transfer_complete(self):
        from backend.services.slack.thread_analyzer import detect_deposit_done
        assert detect_deposit_done("아까 바로이체완료했습니다!") is True

    def test_normal_reply(self):
        from backend.services.slack.thread_analyzer import detect_deposit_done
        assert detect_deposit_done("넵 확인했습니다") is False


class TestDetectCancel:
    def test_cancel(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("해당건은 반품하였습니다.") is True

    def test_refund(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("환불 완료되었습니다!") is True

    def test_direction_change_refund(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("방향성 변경으로 환불처리되었습니다.") is True

    def test_normal_reply(self):
        from backend.services.slack.thread_analyzer import detect_cancel
        assert detect_cancel("넵 확인했습니다") is False


class TestDetectAmountChange:
    def test_new_amount_in_reply(self):
        from backend.services.slack.thread_analyzer import detect_amount_change
        result = detect_amount_change("금액 변경: 총 92,400원 (VAT 포함)", original_amount=84000)
        assert result == 92400

    def test_same_amount(self):
        from backend.services.slack.thread_analyzer import detect_amount_change
        result = detect_amount_change("확인했습니다 35,000원", original_amount=35000)
        assert result is None

    def test_no_amount(self):
        from backend.services.slack.thread_analyzer import detect_amount_change
        result = detect_amount_change("넵 확인했습니다", original_amount=35000)
        assert result is None


class TestAnalyzeThread:
    def test_full_thread_deposit(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        replies = [
            {"text": "인보이스 보내드렸습니다", "user": "U001", "ts": "1770000001.000"},
            {"text": "입금완료", "user": "U002", "ts": "1770000002.000"},
        ]
        result = analyze_thread(replies, original_amount=100000)
        assert result["deposit_done"] is True
        assert result["cancelled"] is False

    def test_full_thread_cancel(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        replies = [
            {"text": "해당건은 반품하였습니다.", "user": "U001", "ts": "1770000001.000"},
        ]
        result = analyze_thread(replies, original_amount=100000)
        assert result["cancelled"] is True

    def test_full_thread_amount_change(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        replies = [
            {"text": "금액 정정: 총 92,400원입니다", "user": "U001", "ts": "1770000001.000"},
        ]
        result = analyze_thread(replies, original_amount=84000)
        assert result["new_amount"] == 92400

    def test_empty_thread(self):
        from backend.services.slack.thread_analyzer import analyze_thread
        result = analyze_thread([], original_amount=100000)
        assert result["deposit_done"] is False
        assert result["cancelled"] is False
        assert result["new_amount"] is None

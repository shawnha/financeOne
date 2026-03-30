"""structured_parser 단위 테스트 — Claude API mock으로 검증."""

import json
import pytest
from unittest.mock import patch, MagicMock

from backend.services.slack.structured_parser import parse_structured, SYSTEM_PROMPT, build_user_prompt


# ── build_user_prompt 테스트 ──────────────────────────────

class TestBuildUserPrompt:
    def test_message_only(self):
        result = build_user_prompt("[ODD] 택시비 35,000원 결제완료", thread_replies=None)
        assert "[메시지 본문]" in result
        assert "택시비 35,000원" in result
        assert "[쓰레드 댓글]" not in result

    def test_with_thread_replies(self):
        replies = json.dumps([
            {"ts": "1", "user": "U1", "text": "입금완료"},
        ], ensure_ascii=False)
        result = build_user_prompt("[HAK] 입금요청 500,000원", thread_replies=replies)
        assert "[쓰레드 댓글]" in result
        assert "입금완료" in result

    def test_empty_text(self):
        result = build_user_prompt("", thread_replies=None)
        assert "[메시지 본문]" in result


# ── parse_structured 테스트 (Claude API mocked) ──────────

MOCK_RESPONSE = {
    "summary": "ODD 촬영 택시비",
    "vendor": "카카오택시",
    "project": "ODD",
    "category": "교통",
    "items": [{"description": "택시비", "amount": 35000, "currency": "KRW"}],
    "total_amount": 35000,
    "currency": "KRW",
    "vat": {"type": "none", "vat_amount": None, "supply_amount": None},
    "withholding_tax": {"applies": False, "rate": None, "amount": None, "net_amount": None},
    "payment_terms": {"type": "full", "ratio": None, "related_context": None},
    "tax_invoice": False,
    "date_mentioned": None,
    "urgency": None,
    "confidence": 0.95,
}


def _mock_anthropic_response(content_json: dict):
    """Anthropic SDK 응답 mock 생성."""
    mock_block = MagicMock()
    mock_block.text = json.dumps(content_json, ensure_ascii=False)
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage.input_tokens = 500
    mock_response.usage.output_tokens = 200
    return mock_response


class TestParseStructured:
    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_basic_parse(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.return_value = _mock_anthropic_response(MOCK_RESPONSE)

        result = parse_structured("[ODD] 택시비 35,000원 결제완료", thread_replies=None)

        assert result is not None
        assert result["summary"] == "ODD 촬영 택시비"
        assert result["vendor"] == "카카오택시"
        assert result["project"] == "ODD"
        assert result["total_amount"] == 35000
        assert result["confidence"] == 0.95

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_api_failure_returns_none(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.side_effect = Exception("API error")

        result = parse_structured("[ODD] 택시비 35,000원", thread_replies=None)

        assert result is None

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_invalid_json_returns_none(self, MockAnthropic):
        client = MockAnthropic.return_value
        mock_block = MagicMock()
        mock_block.text = "not valid json {{"
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        client.messages.create.return_value = mock_response

        result = parse_structured("[ODD] 택시비 35,000원", thread_replies=None)

        assert result is None

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_with_thread_replies(self, MockAnthropic):
        client = MockAnthropic.return_value
        response_with_deposit = {**MOCK_RESPONSE, "summary": "ODD 택시비 - 입금완료"}
        client.messages.create.return_value = _mock_anthropic_response(response_with_deposit)

        replies = json.dumps([{"ts": "1", "user": "U1", "text": "입금완료"}], ensure_ascii=False)
        result = parse_structured("[ODD] 택시비 35,000원", thread_replies=replies)

        assert result is not None
        assert "입금완료" in result["summary"]

    @patch("backend.services.slack.structured_parser.anthropic.Anthropic")
    def test_skip_other_type(self, MockAnthropic):
        """message_type이 other이고 금액 없으면 호출하지 않음."""
        result = parse_structured("", thread_replies=None, skip=True)

        assert result is None
        MockAnthropic.return_value.messages.create.assert_not_called()


class TestSystemPrompt:
    def test_system_prompt_exists(self):
        assert len(SYSTEM_PROMPT) > 100
        assert "JSON" in SYSTEM_PROMPT
        assert "VAT" in SYSTEM_PROMPT

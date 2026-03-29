"""message_parser 테스트 — 유형 분류 + 금액/VAT/태그/sub_amounts 파싱"""

import pytest


class TestClassify:
    def test_card_payment_korean(self):
        from backend.services.slack.message_parser import classify
        assert classify("[ODD] 카카오택시 35,000원 - 개인법카 결제완료") == "card_payment"

    def test_card_payment_purchase(self):
        from backend.services.slack.message_parser import classify
        assert classify("[마트약국 제작물 결제] - 개인 법카 구매완료") == "card_payment"

    def test_deposit_request(self):
        from backend.services.slack.message_parser import classify
        assert classify("[ODD] 스튜디오 대관비용 입금요청") == "deposit_request"

    def test_deposit_request_needed(self):
        from backend.services.slack.message_parser import classify
        assert classify("[마트약국 쇼카드 발주] 입금 필요") == "deposit_request"

    def test_tax_invoice(self):
        from backend.services.slack.message_parser import classify
        assert classify("[한아원명함] - 세금계산서 발행 완료") == "tax_invoice"

    def test_expense_share_with_amount(self):
        from backend.services.slack.message_parser import classify
        assert classify("크롤러 PC용 주변기기 구매 - 16000원") == "expense_share"

    def test_other_no_amount_no_keyword(self):
        from backend.services.slack.message_parser import classify
        assert classify("다들 주말 잘보내고계신가요~?") == "other"

    def test_bot_message(self):
        from backend.services.slack.message_parser import classify
        assert classify("ExpenseOne 봇 연결 테스트입니다.") == "other"


class TestExtractAmount:
    def test_krw_comma(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("카카오택시 35,000원")
        assert result == {"amount": 35000, "currency": "KRW"}

    def test_krw_no_comma(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("다이소 16000원")
        assert result == {"amount": 16000, "currency": "KRW"}

    def test_krw_man(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("퀵비용 3만원")
        assert result == {"amount": 30000, "currency": "KRW"}

    def test_usd_dollar_sign(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("클로드 $11")
        assert result == {"amount": 11.0, "currency": "USD"}

    def test_usd_us_dollar(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("법무법인 US$882")
        assert result == {"amount": 882.0, "currency": "USD"}

    def test_usd_bul(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("힉스필드 158불")
        assert result == {"amount": 158.0, "currency": "USD"}

    def test_usd_with_cents(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("Target $98.78 결제")
        assert result == {"amount": 98.78, "currency": "USD"}

    def test_no_amount(self):
        from backend.services.slack.message_parser import extract_amount
        result = extract_amount("서류 공유해주세요")
        assert result is None


class TestExtractVat:
    def test_vat_included(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("92,400원 (VAT 포함)") == "included"

    def test_vat_plus(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("851,400원(vat+)") == "included"

    def test_vat_excluded(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("64,000원(VAT 제외)") == "excluded"

    def test_vat_minus(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("60,000원(vat-)") == "excluded"

    def test_vat_separate(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("314,000원 + 부가세 별도") == "excluded"

    def test_no_vat(self):
        from backend.services.slack.message_parser import extract_vat
        assert extract_vat("카카오택시 35,000원") == "none"


class TestExtractTag:
    def test_project_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("[ODD] 카카오택시 35,000원") == "ODD"

    def test_korean_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("[마트약국] 쇼카드 발주") == "마트약국"

    def test_multi_word_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("[AI 웹 제작을 위한 API 비용]") == "AI 웹 제작을 위한 API 비용"

    def test_no_tag(self):
        from backend.services.slack.message_parser import extract_tag
        assert extract_tag("카카오택시 35,000원") is None


class TestExtractSubAmounts:
    def test_multi_line_items(self):
        from backend.services.slack.message_parser import extract_sub_amounts
        text = """[ODD] 스티커 + 포장
• 스티커 851,400원
• 포장 286,100원
합계 1,137,500원"""
        result = extract_sub_amounts(text)
        assert len(result) == 2
        assert result[0]["amount"] == 851400
        assert result[1]["amount"] == 286100

    def test_single_amount_no_sub(self):
        from backend.services.slack.message_parser import extract_sub_amounts
        text = "카카오택시 35,000원"
        result = extract_sub_amounts(text)
        assert result == []


class TestWithholding:
    def test_withholding_detected(self):
        from backend.services.slack.message_parser import detect_withholding
        assert detect_withholding("500,000원 (3.3% 제외 해야합니다)") is True

    def test_no_withholding(self):
        from backend.services.slack.message_parser import detect_withholding
        assert detect_withholding("카카오택시 35,000원") is False

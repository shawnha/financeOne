"""Phase 1 parser unit tests — no database required.

Covers:
  - Detection (detect) for all three parsers
  - Parsing output structure and field types
  - Check-card deduplication flag
  - Auto-detect registry
"""

import datetime
from pathlib import Path

import pytest

from backend.services.parsers import ParsedTransaction, detect_parser
from backend.services.parsers.lotte_card import LotteCardParser
from backend.services.parsers.woori_card import WooriCardParser
from backend.services.parsers.woori_bank import WooriBankParser

RANDOM_BYTES = b"\x00\x01\x02\xff\xfe\xfd random noise that is not a valid file"

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "transaction_sample"


# ── Test 1: Lotte Card detection ──────────────────────────────────────────


class TestLotteCardDetect:
    def test_detects_valid_xls(self, lotte_card_bytes: bytes):
        parser = LotteCardParser()
        assert parser.detect(lotte_card_bytes, "롯데카드_1월.xls") is True

    def test_rejects_random_bytes(self):
        parser = LotteCardParser()
        assert parser.detect(RANDOM_BYTES, "garbage.xls") is False


# ── Test 2: Woori Card detection ──────────────────────────────────────────


class TestWooriCardDetect:
    def test_detects_valid_xls(self, woori_card_bytes: bytes):
        parser = WooriCardParser()
        assert parser.detect(woori_card_bytes, "우리카드_1월.xls") is True

    def test_rejects_random_bytes(self):
        parser = WooriCardParser()
        assert parser.detect(RANDOM_BYTES, "garbage.xls") is False


# ── Test 3: Woori Bank detection ──────────────────────────────────────────


class TestWooriBankDetect:
    def test_detects_valid_xlsx(self, woori_bank_bytes: bytes):
        parser = WooriBankParser()
        assert parser.detect(woori_bank_bytes, "우리은행 거래내역_1월.xlsx") is True

    def test_rejects_random_bytes(self):
        parser = WooriBankParser()
        assert parser.detect(RANDOM_BYTES, "garbage.xlsx") is False


# ── Test 4: Lotte Card parse transactions ─────────────────────────────────


class TestLotteCardParse:
    def test_parse_returns_transactions(self, lotte_card_bytes: bytes):
        parser = LotteCardParser()
        txns = parser.parse(lotte_card_bytes, "롯데카드_1월.xls")

        assert len(txns) > 0, "Parser must return at least one transaction"

        for tx in txns:
            assert isinstance(tx.date, datetime.date)
            assert tx.amount > 0
            assert tx.source_type == "lotte_card"
            assert tx.type in ("out", "in")  # "in" for 취소 환불

        # Most rows should have a non-empty counterparty
        with_counterparty = [tx for tx in txns if tx.counterparty]
        assert len(with_counterparty) >= len(txns) * 0.8, (
            "At least 80% of transactions should have a counterparty"
        )


# ── Test 5: Woori Bank has income and expense ─────────────────────────────


class TestWooriBankParse:
    def test_has_income_and_expense(self, woori_bank_bytes: bytes):
        parser = WooriBankParser()
        txns = parser.parse(woori_bank_bytes, "우리은행 거래내역_1월.xlsx")

        assert len(txns) > 0, "Parser must return at least one transaction"

        types_found = {tx.type for tx in txns}
        assert "in" in types_found, "Expected at least one income (type='in') transaction"
        assert "out" in types_found, "Expected at least one expense (type='out') transaction"

        for tx in txns:
            assert isinstance(tx.amount, float) or isinstance(tx.amount, int)
            assert tx.amount > 0
            assert tx.source_type == "woori_bank"


# ── Test 6: Woori Card check-card dedup flag ──────────────────────────────


class TestWooriCardCheckCard:
    def test_check_card_dedup_flag(self, woori_card_bytes: bytes):
        parser = WooriCardParser()
        txns = parser.parse(woori_card_bytes, "우리카드_1월.xls")

        assert len(txns) > 0, "Parser must return at least one transaction"

        check_card_txns = [tx for tx in txns if tx.is_check_card is True]
        assert len(check_card_txns) >= 1, (
            "Expected at least one transaction with is_check_card=True (체크계좌)"
        )


# ── Test 7: Parser registry auto-detect ───────────────────────────────────


class TestParserRegistry:
    def test_detects_lotte_card(self, lotte_card_bytes: bytes):
        parser = detect_parser(lotte_card_bytes, "롯데카드_1월.xls")
        assert parser is not None
        assert isinstance(parser, LotteCardParser)

    def test_detects_woori_card(self, woori_card_bytes: bytes):
        parser = detect_parser(woori_card_bytes, "우리카드_1월.xls")
        assert parser is not None
        assert isinstance(parser, WooriCardParser)

    def test_detects_woori_bank(self, woori_bank_bytes: bytes):
        parser = detect_parser(woori_bank_bytes, "우리은행 거래내역_1월.xlsx")
        assert parser is not None
        assert isinstance(parser, WooriBankParser)

    def test_returns_none_for_unknown(self):
        result = detect_parser(RANDOM_BYTES, "unknown_file.pdf")
        assert result is None


# ── Test 8: ParsedTransaction field types ─────────────────────────────────


class TestParsedTransactionFields:
    def test_all_required_fields(self, lotte_card_bytes: bytes):
        parser = LotteCardParser()
        txns = parser.parse(lotte_card_bytes, "롯데카드_1월.xls")

        assert len(txns) > 0
        tx = txns[0]

        # Type checks
        assert isinstance(tx.date, datetime.date), f"date should be datetime.date, got {type(tx.date)}"
        assert isinstance(tx.amount, (int, float)), f"amount should be numeric, got {type(tx.amount)}"
        assert tx.amount > 0, "amount must be positive"
        assert isinstance(tx.currency, str), f"currency should be str, got {type(tx.currency)}"
        assert isinstance(tx.type, str), f"type should be str, got {type(tx.type)}"
        assert tx.type in ("in", "out"), f"type must be 'in' or 'out', got '{tx.type}'"
        assert isinstance(tx.description, str), f"description should be str, got {type(tx.description)}"
        assert isinstance(tx.counterparty, str), f"counterparty should be str, got {type(tx.counterparty)}"
        assert isinstance(tx.source_type, str), f"source_type should be str, got {type(tx.source_type)}"

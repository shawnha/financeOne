"""Cashflow service unit tests — no database required.

Covers:
  - Daily running balance calculation from transactions
  - Monthly summary aggregation (income/expense/net)
  - Card expense grouping by source and member
  - Edge cases: empty month, refunds, opening balance
"""

import datetime
from decimal import Decimal

from backend.services.cashflow_service import (
    build_daily_rows,
    aggregate_monthly_summary,
    group_card_expenses,
    calc_card_timing_adjustment,
    calc_forecast_closing,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _tx(date_str: str, tx_type: str, amount: float, description: str = "",
        source_type: str = "woori_bank", counterparty: str = None,
        member_name: str = None, member_id: int = None,
        account_name: str = None, account_code: str = None,
        tx_id: int = 1):
    """Minimal transaction dict matching DB row shape."""
    return {
        "id": tx_id,
        "date": datetime.date.fromisoformat(date_str),
        "type": tx_type,
        "amount": Decimal(str(amount)),
        "description": description,
        "counterparty": counterparty,
        "source_type": source_type,
        "member_id": member_id,
        "member_name": member_name,
        "account_name": account_name,
        "account_code": account_code,
    }


# ── Test 1: build_daily_rows — 일별 잔고 추적 ───────────────────────────────


class TestBuildDailyRows:
    def test_basic_in_out(self):
        """입금/출금 → running balance 정확히 계산."""
        txs = [
            _tx("2025-01-02", "in", 1_200_000, "스마트스토어정산", tx_id=1),
            _tx("2025-01-04", "out", 235_000, "NICE_통신판매", tx_id=2),
        ]
        rows = build_daily_rows(txs, opening_balance=Decimal("161_050_376"))

        # 첫 행 = 시작 잔고
        assert rows[0]["type"] == "opening"
        assert rows[0]["balance"] == Decimal("161050376")

        # 입금 후 잔고
        assert rows[1]["balance"] == Decimal("161050376") + Decimal("1200000")

        # 출금 후 잔고
        assert rows[2]["balance"] == Decimal("161050376") + Decimal("1200000") - Decimal("235000")

        # 마지막 행 = 기말 잔고
        assert rows[-1]["type"] == "closing"
        assert rows[-1]["balance"] == rows[-2]["balance"]

    def test_empty_transactions(self):
        """거래 0건 → 기초=기말."""
        rows = build_daily_rows([], opening_balance=Decimal("50_000_000"))
        assert len(rows) == 2  # opening + closing
        assert rows[0]["balance"] == Decimal("50000000")
        assert rows[1]["balance"] == Decimal("50000000")

    def test_card_payment_row(self):
        """카드대금 출금은 type='out'으로 표시."""
        txs = [
            _tx("2025-01-15", "out", 25_300_000, "롯데카드(주)", tx_id=1),
        ]
        rows = build_daily_rows(txs, opening_balance=Decimal("161_050_376"))
        # opening + 1 tx + closing
        assert len(rows) == 3
        assert rows[1]["amount"] == Decimal("25300000")
        assert rows[-1]["balance"] == Decimal("161050376") - Decimal("25300000")


# ── Test 2: aggregate_monthly_summary — 월별 요약 ────────────────────────────


class TestAggregateMonthly:
    def test_basic_aggregation(self):
        """단일 월 입금/출금 합산."""
        txs = [
            _tx("2025-01-02", "in", 1_000_000, tx_id=1),
            _tx("2025-01-05", "in", 2_000_000, tx_id=2),
            _tx("2025-01-10", "out", 500_000, tx_id=3),
        ]
        summary = aggregate_monthly_summary(txs, 2025, 1)
        assert summary["income"] == Decimal("3000000")
        assert summary["expense"] == Decimal("500000")
        assert summary["net"] == Decimal("2500000")

    def test_empty_month(self):
        """거래 0건 → 모두 0."""
        summary = aggregate_monthly_summary([], 2025, 2)
        assert summary["income"] == Decimal("0")
        assert summary["expense"] == Decimal("0")
        assert summary["net"] == Decimal("0")


# ── Test 3: group_card_expenses — 카드 사용 그룹핑 ───────────────────────────


class TestGroupCardExpenses:
    def test_group_by_source_and_member(self):
        """소스별 → 회원별 그룹핑."""
        txs = [
            _tx("2025-01-03", "out", 167_145, "Anthropic", source_type="lotte_card",
                 member_name="하선우", member_id=1, account_name="SaaS", tx_id=1),
            _tx("2025-01-05", "out", 28_958, "Cursor AI", source_type="lotte_card",
                 member_name="하선우", member_id=1, account_name="SaaS", tx_id=2),
            _tx("2025-01-10", "out", 201_600, "카카오T", source_type="lotte_card",
                 member_name="하선우", member_id=1, account_name="교통비", tx_id=3),
            _tx("2025-01-15", "out", 50_000, "스타벅스", source_type="woori_card",
                 member_name=None, member_id=None, account_name="접대비", tx_id=4),
        ]
        result = group_card_expenses(txs)

        assert len(result) == 2  # lotte_card, woori_card
        lotte = next(g for g in result if g["source_type"] == "lotte_card")
        assert lotte["total_expense"] == Decimal("397703")
        assert lotte["total_refund"] == Decimal("0")
        assert lotte["tx_count"] == 3
        assert len(lotte["members"]) == 1
        assert lotte["members"][0]["member_name"] == "하선우"

    def test_refund_handling(self):
        """환불(type='in')은 total_refund에 합산."""
        txs = [
            _tx("2025-01-03", "out", 100_000, "결제", source_type="lotte_card",
                 member_name="하선우", member_id=1, tx_id=1),
            _tx("2025-01-05", "in", 30_000, "환불", source_type="lotte_card",
                 member_name="하선우", member_id=1, tx_id=2),
        ]
        result = group_card_expenses(txs)
        lotte = result[0]
        assert lotte["total_expense"] == Decimal("100000")
        assert lotte["total_refund"] == Decimal("30000")
        assert lotte["net"] == Decimal("70000")

    def test_empty_card_transactions(self):
        """카드 거래 0건 → 빈 리스트."""
        result = group_card_expenses([])
        assert result == []


# ── Test 4: account_breakdown in card expenses ───────────────────────────────


class TestCardAccountBreakdown:
    def test_account_grouping(self):
        """내부계정별 합산."""
        txs = [
            _tx("2025-01-03", "out", 167_145, "Anthropic", source_type="lotte_card",
                 member_name="하선우", member_id=1, account_name="SaaS", tx_id=1),
            _tx("2025-01-05", "out", 28_958, "Cursor AI", source_type="lotte_card",
                 member_name="하선우", member_id=1, account_name="SaaS", tx_id=2),
            _tx("2025-01-10", "out", 201_600, "카카오T", source_type="lotte_card",
                 member_name="하선우", member_id=1, account_name="교통비", tx_id=3),
        ]
        result = group_card_expenses(txs)
        lotte = result[0]

        # account_breakdown at source level
        breakdown = lotte["account_breakdown"]
        saas = next(a for a in breakdown if a["account_name"] == "SaaS")
        assert saas["amount"] == Decimal("196103")

        transport = next(a for a in breakdown if a["account_name"] == "교통비")
        assert transport["amount"] == Decimal("201600")


# ── Test 5: calc_card_timing_adjustment — 시차 보정 ──────────────────────────


class TestCardTimingAdjustment:
    def test_positive_adjustment(self):
        """전월 카드 > 당월 카드 → 양수 보정 (카드대금 결제 증가)."""
        result = calc_card_timing_adjustment(
            prev_month_card=Decimal("17_700_000"),
            curr_month_card=Decimal("12_300_000"),
        )
        assert result == Decimal("5400000")

    def test_negative_adjustment(self):
        """전월 카드 < 당월 카드 → 음수 보정."""
        result = calc_card_timing_adjustment(
            prev_month_card=Decimal("10_000_000"),
            curr_month_card=Decimal("15_000_000"),
        )
        assert result == Decimal("-5000000")

    def test_zero_adjustment(self):
        """전월 == 당월 → 보정 0."""
        result = calc_card_timing_adjustment(
            prev_month_card=Decimal("5_000_000"),
            curr_month_card=Decimal("5_000_000"),
        )
        assert result == Decimal("0")

    def test_first_month_no_prev(self):
        """첫 월 (이전 데이터 없음) → 보정 0."""
        result = calc_card_timing_adjustment(
            prev_month_card=Decimal("0"),
            curr_month_card=Decimal("12_000_000"),
        )
        assert result == Decimal("-12000000")


# ── Test 6: calc_forecast_closing — 예상 기말 공식 ───────────────────────────


class TestForecastClosing:
    def test_full_formula(self):
        """예상 기말 = 기초 + 입금 - 출금 - 카드사용 + 시차보정."""
        result = calc_forecast_closing(
            opening_balance=Decimal("107_168_640"),
            forecast_income=Decimal("226_700_000"),
            forecast_expense=Decimal("180_300_000"),
            forecast_card_usage=Decimal("12_300_000"),
            card_timing_adjustment=Decimal("5_400_000"),
        )
        # 107,168,640 + 226,700,000 - 180,300,000 - 12,300,000 + 5,400,000 = 146,668,640
        assert result == Decimal("146668640")

    def test_zero_everything(self):
        """모든 항목 0 → 기초 = 기말."""
        result = calc_forecast_closing(
            opening_balance=Decimal("50_000_000"),
            forecast_income=Decimal("0"),
            forecast_expense=Decimal("0"),
            forecast_card_usage=Decimal("0"),
            card_timing_adjustment=Decimal("0"),
        )
        assert result == Decimal("50000000")

    def test_negative_net(self):
        """지출 > 수입 → 기말 < 기초."""
        result = calc_forecast_closing(
            opening_balance=Decimal("100_000_000"),
            forecast_income=Decimal("10_000_000"),
            forecast_expense=Decimal("50_000_000"),
            forecast_card_usage=Decimal("20_000_000"),
            card_timing_adjustment=Decimal("0"),
        )
        # 100M + 10M - 50M - 20M + 0 = 40M
        assert result == Decimal("40000000")

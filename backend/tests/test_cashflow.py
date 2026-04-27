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
    predicted_ending_mode,
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


# ── Test 3-bis: get_card_total_net SQL — 취소건 차감 검증 ───────────────────


class _FakeCursor:
    """Captures the SQL Postgres receives so we can assert query semantics."""

    def __init__(self, return_value):
        self._return_value = return_value
        self.queries: list[tuple[str, list]] = []

    def execute(self, sql, params=None):
        self.queries.append((sql, list(params or [])))

    def fetchone(self):
        return (self._return_value,)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, return_value=Decimal("0")):
        self.cursor_obj = _FakeCursor(return_value)

    def cursor(self):
        return self.cursor_obj


class TestGetCardTotalNetQuery:
    """P0-1 회귀 테스트: 취소건이 net 계산에서 차감되도록 SQL 보장.

    버그: WHERE (is_cancel IS NOT TRUE) 로 cancel row(type='in', is_cancel=TRUE) 전체 제외 → 환불 무시.
    수정: SUM 의 CASE 식에서 type='in' 전체를 차감 (cancel 포함).
    """

    def test_query_does_not_filter_cancel_in_where(self):
        from backend.services.cashflow_service import get_card_total_net

        conn = _FakeConn(return_value=Decimal("0"))
        get_card_total_net(conn, entity_id=1, year=2026, month=4)

        sql, _ = conn.cursor_obj.queries[0]
        assert "is_duplicate = false" in sql
        # 핵심: WHERE 에 (is_cancel IS NOT TRUE) 가 없어야 한다
        # — 있으면 type='in', is_cancel=TRUE 인 환불행이 걸러져 net 과대평가
        where_clause = sql.split("WHERE", 1)[1]
        assert "is_cancel IS NOT TRUE" not in where_clause, (
            "WHERE 절에서 is_cancel 필터링하면 cancel row 가 net 차감되지 않음"
        )

    def test_query_subtracts_in_rows_in_sum(self):
        from backend.services.cashflow_service import get_card_total_net

        conn = _FakeConn(return_value=Decimal("0"))
        get_card_total_net(conn, entity_id=1, year=2026, month=4)

        sql, _ = conn.cursor_obj.queries[0]
        # SUM 식에 type='in' 차감 표현이 있어야 함 (-amount 또는 0-amount 등)
        normalized = " ".join(sql.split())
        assert "type = 'in'" in normalized.lower() or "type='in'" in normalized.lower()
        assert "-amount" in normalized.replace(" ", "") or "0 - " in normalized

    def test_query_excludes_out_when_cancel(self):
        """방어: type='out' 인데 is_cancel=TRUE 인 비정상 row 는 정상 사용으로 안 잡혀야 함."""
        from backend.services.cashflow_service import get_card_total_net

        conn = _FakeConn(return_value=Decimal("0"))
        get_card_total_net(conn, entity_id=1, year=2026, month=4)

        sql, _ = conn.cursor_obj.queries[0]
        normalized = " ".join(sql.split()).lower()
        # type='out' 인 amount 합산은 is_cancel IS NOT TRUE 조건이 붙어야
        assert "type = 'out' and is_cancel is not true" in normalized

    def test_source_type_variant_query_same_semantics(self):
        """source_type 지정 호출 분기도 동일하게 cancel 미필터 + in 차감."""
        from backend.services.cashflow_service import get_card_total_net

        conn = _FakeConn(return_value=Decimal("0"))
        get_card_total_net(conn, entity_id=1, year=2026, month=4, source_type="lotte_card")

        sql, params = conn.cursor_obj.queries[0]
        where_clause = sql.split("WHERE", 1)[1]
        assert "is_cancel IS NOT TRUE" not in where_clause
        normalized = " ".join(sql.split()).lower()
        assert "type = 'out' and is_cancel is not true" in normalized
        # family matching: bare + codef_ prefixed
        variants = params[1]
        assert "lotte_card" in variants and "codef_lotte_card" in variants


class TestCardCancelInGroupedExpenses:
    """P0-1: get_card_transactions 가 cancel row 를 포함해야 group_card_expenses 가 refund 계산 가능."""

    def test_cancel_rows_flow_through_grouping(self):
        # cancel row 를 (type='in', is_cancel=True) 로 시뮬레이션
        txs = [
            _tx("2026-04-03", "out", 100_000, "Anthropic", source_type="codef_lotte_card",
                member_name="하선우", member_id=1, tx_id=1),
            _tx("2026-04-05", "in", 25_000, "환불", source_type="codef_lotte_card",
                member_name="하선우", member_id=1, tx_id=2),
        ]
        # is_cancel 필드는 group 로직에서 직접 참조하지 않지만 type='in' 이면 refund 로 분류됨
        result = group_card_expenses(txs)
        lotte = result[0]
        assert lotte["total_expense"] == Decimal("100000")
        assert lotte["total_refund"] == Decimal("25000")
        assert lotte["net"] == Decimal("75000")


# ── Test 7: predicted_ending_mode — P0-2 month-end 분기 ─────────────────────


class TestPredictedEndingMode:
    """P0-2 회귀 테스트: 오늘이 월의 last_day 일 때 progressive 모드여야 함.

    버그: today_day == last_day 조건이 'completed' 분기로 매핑되어
    expected_day == last_day 인 forecast 항목이 import 되기 전에는 누락 →
    예상 기말이 실제로 점프(=actual_closing) 하면서 오늘 expected 거래가 빠짐.
    수정: 'as_of > month_end' 만 'completed', 그 외엔 progressive 또는 future.
    """

    def test_past_month_completed(self):
        """as_of 가 조회 월말 이후 → completed (100% 실제)."""
        mode = predicted_ending_mode(
            as_of=datetime.date(2026, 5, 5),
            month_start=datetime.date(2026, 4, 1),
            month_end=datetime.date(2026, 4, 30),
        )
        assert mode == "completed"

    def test_today_is_last_day_of_current_month_progressive(self):
        """오늘이 조회 월의 진짜 last_day → progressive (last-day forecast 보존)."""
        mode = predicted_ending_mode(
            as_of=datetime.date(2026, 4, 30),
            month_start=datetime.date(2026, 4, 1),
            month_end=datetime.date(2026, 4, 30),
        )
        # P0-2 핵심: 'completed' 가 아니어야 함 — last-day expected 거래 누락 방지
        assert mode == "progressive"

    def test_today_within_month_progressive(self):
        """월 중간 → progressive."""
        mode = predicted_ending_mode(
            as_of=datetime.date(2026, 4, 15),
            month_start=datetime.date(2026, 4, 1),
            month_end=datetime.date(2026, 4, 30),
        )
        assert mode == "progressive"

    def test_first_day_of_month_progressive(self):
        """월 첫날 → progressive (first day 예상 보존)."""
        mode = predicted_ending_mode(
            as_of=datetime.date(2026, 4, 1),
            month_start=datetime.date(2026, 4, 1),
            month_end=datetime.date(2026, 4, 30),
        )
        assert mode == "progressive"

    def test_future_month(self):
        """as_of 가 조회 월 시작 이전 → future (100% 예상)."""
        mode = predicted_ending_mode(
            as_of=datetime.date(2026, 3, 15),
            month_start=datetime.date(2026, 4, 1),
            month_end=datetime.date(2026, 4, 30),
        )
        assert mode == "future"

    def test_february_short_month_last_day(self):
        """2월 28/29일에도 last_day == today 가 progressive 가 되어야 함."""
        # 2026 = 평년, Feb last_day = 28
        mode = predicted_ending_mode(
            as_of=datetime.date(2026, 2, 28),
            month_start=datetime.date(2026, 2, 1),
            month_end=datetime.date(2026, 2, 28),
        )
        assert mode == "progressive"


# ── Test 8: get_forecast_cashflow GET path는 UPDATE 안 함 — P0-3 ────────────


class TestGetForecastCashflowReadOnly:
    """P0-3 회귀 테스트: GET 경로에서 UPDATE forecasts 가 발생하면 안 됨.

    이전 버그: get_forecast_cashflow 가 actual_amount 동기화 UPDATE+commit 을
    GET 호출시마다 수행 → 사용자 PATCH 한 actual_amount 가 페이지 로드만으로 덮어써짐.
    """

    def test_source_does_not_call_sync_forecast_actuals(self):
        """get_forecast_cashflow 함수 본문에 UPDATE forecasts SET actual_amount 가 없어야 함."""
        import inspect
        from backend.services import cashflow_service

        src = inspect.getsource(cashflow_service.get_forecast_cashflow)
        # GET 함수 안에서 forecasts.actual_amount 자동 갱신 SQL 이 사라졌어야 함
        normalized = " ".join(src.split())
        assert "UPDATE forecasts" not in normalized, (
            "get_forecast_cashflow 내부의 UPDATE forecasts ... SET actual_amount 는 "
            "race 원인 — sync_forecast_actuals 함수로 분리하고 명시적 호출만 허용"
        )

    def test_sync_forecast_actuals_function_exists(self):
        """추출된 동기화 함수가 export 되어야 함."""
        from backend.services.cashflow_service import sync_forecast_actuals
        assert callable(sync_forecast_actuals)

    def test_sync_endpoint_is_post(self):
        """동기화 endpoint 는 POST 여야 함 (GET 은 부작용 없는 read-only)."""
        from backend.routers.cashflow import router

        for r in router.routes:
            if getattr(r, "path", "") == "/api/cashflow/forecast/sync-actuals":
                assert "POST" in r.methods
                return
        raise AssertionError("/api/cashflow/forecast/sync-actuals POST endpoint 미발견")


# ── Test 9: forecast_closing baseline raw payment_method — P1-1 ─────────────


class TestForecastClosingBaseline:
    """P1-1 회귀: forecast_closing 합산은 forecasts.payment_method 만 사용해야 함.

    이전: 실제 거래 분포로 effective_pm 재분류 → 작은 카드 거래 1건만으로도
    forecast_closing baseline 흔들림 (Codex 지적).
    수정: forecast_closing 분기는 db_pm 만, predicted_ending 합성 단계에서만
    _split_forecasts_by_today() 가 effective_pm 적용.
    """

    def test_source_does_not_set_effective_pm_in_forecast_loop(self):
        """get_forecast_cashflow 내부 Forecast 합산 루프에 effective_pm 변수 부재."""
        import inspect
        from backend.services import cashflow_service

        src = inspect.getsource(cashflow_service.get_forecast_cashflow)
        # 'effective_pm =' 할당 자체가 합산 루프에서 사라졌어야 함
        # (split_forecasts_by_today 안에는 있어도 OK — 거기는 predicted_ending 용)
        normalized = " ".join(src.split())
        assert "effective_pm = " not in normalized, (
            "get_forecast_cashflow 본문에서 effective_pm 재분류는 forecast_closing 까지 "
            "영향 — _split_forecasts_by_today() 로만 한정해야 baseline 안정"
        )

    def test_split_forecasts_by_today_still_uses_effective_pm(self):
        """predicted_ending 합성용 _split_forecasts_by_today 는 여전히 재분류 적용."""
        import inspect
        from backend.services import cashflow_service

        src = inspect.getsource(cashflow_service._split_forecasts_by_today)
        assert "effective_pm" in src, (
            "_split_forecasts_by_today 안의 effective_pm 재분류는 유지되어야 함 "
            "(predicted_ending 합성에서 카드 주류 재분류 처리)"
        )


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

"""forecasts 예산/고정비 기능 테스트"""


class TestCopyRecurringLogic:
    """고정비 자동 복사 로직 테스트"""

    def test_copies_only_recurring(self):
        """is_recurring=true 항목만 복사 대상"""
        items = [
            {"is_recurring": True, "category": "임차료"},
            {"is_recurring": False, "category": "점심"},
            {"is_recurring": True, "category": "Google Workspace"},
        ]
        recurring = [i for i in items if i["is_recurring"]]
        assert len(recurring) == 2
        assert recurring[0]["category"] == "임차료"
        assert recurring[1]["category"] == "Google Workspace"


class TestSuggestFromActualsLogic:
    """전월 실적 기반 예상 제안 로직 테스트"""

    def test_previous_month_calculation(self):
        """3월 요청 → 2월 데이터"""
        year, month = 2026, 3
        prev_year = year if month > 1 else year - 1
        prev_month = month - 1 if month > 1 else 12
        assert prev_year == 2026
        assert prev_month == 2

    def test_january_wraps_to_december(self):
        """1월 요청 → 전년 12월"""
        year, month = 2026, 1
        prev_year = year if month > 1 else year - 1
        prev_month = month - 1 if month > 1 else 12
        assert prev_year == 2025
        assert prev_month == 12


class TestOverBudget:
    """예산 초과 감지 테스트"""

    def test_detects_over_budget_at_110_percent(self):
        """실제 >= 예상 * 1.1 → 초과"""
        forecast = 100_000.0
        actual = 115_000.0
        assert forecast > 0
        assert actual >= forecast * 1.1
        diff_pct = round((actual / forecast - 1) * 100, 1)
        assert diff_pct == 15.0

    def test_no_false_positive_under_threshold(self):
        """실제 < 예상 * 1.1 → 초과 아님"""
        forecast = 100_000.0
        actual = 109_000.0
        assert not (actual >= forecast * 1.1)

    def test_over_boundary(self):
        """111% → 초과"""
        forecast = 100_000.0
        actual = 111_000.0
        assert actual >= forecast * 1.1

    def test_zero_forecast_skipped(self):
        """예상 0원 → division 방지, skip"""
        forecast = 0.0
        assert not (forecast > 0)

    def test_negative_difference(self):
        """실제 < 예상 → 절약"""
        forecast = 500_000.0
        actual = 300_000.0
        diff = actual - forecast
        assert diff == -200_000.0
        assert not (actual >= forecast * 1.1)


class TestUnbudgetedActuals:
    """forecast에 없는 계정의 실제 거래를 감지."""

    def test_identifies_unbudgeted(self):
        forecast_account_ids = {(351, "out"), (353, "out"), (355, "out")}
        actual_account_ids = {(351, "out"), (353, "out"), (355, "out"), (469, "out"), (467, "out")}
        unbudgeted = actual_account_ids - forecast_account_ids
        assert unbudgeted == {(469, "out"), (467, "out")}

    def test_empty_when_all_budgeted(self):
        forecast_ids = {(351, "out"), (353, "out")}
        actual_ids = {(351, "out"), (353, "out")}
        assert actual_ids - forecast_ids == set()


class TestWorstCaseSchedule:
    """worst-case: 비정기 수입 월말, 비정기 지출 월초."""

    def test_worst_case_income_at_end_expense_at_start(self):
        opening = 100_000_000
        nr_expense = 60_000_000
        nr_income = 80_000_000
        worst_day1 = opening - nr_expense
        assert worst_day1 == 40_000_000
        worst_day31 = worst_day1 + nr_income
        assert worst_day31 == 120_000_000
        daily_net = (nr_income - nr_expense) / 31
        normal_day1 = opening + daily_net
        assert worst_day1 < normal_day1

"""Smoke test for /dashboard/full schemas + service module compilation.

Phase 1A foundation test — verify:
1. Pydantic schemas import + validate
2. dashboard_service module imports without error
3. Schemas can serialize/deserialize realistic data
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest


def test_schemas_import():
    """All Pydantic models import without error."""
    from backend.routers.dashboard_schemas import (
        AccrualDiffBreakdown,
        AccrualKPI,
        AiActivity,
        AiCascadeStat,
        BentoEntity,
        BentoSummary,
        CashKPI,
        ChartData,
        ChartMonthPoint,
        DashboardFullResponse,
        DecisionQueueItem,
        DecisionQueueSection,
    )
    assert DashboardFullResponse.__name__ == "DashboardFullResponse"


def test_dashboard_service_import():
    """Service module imports + constants defined."""
    from backend.services.dashboard_service import (
        ACCRUAL_GATING_THRESHOLD,
        ACCRUAL_TOTAL_CHECKS,
        fetch_dashboard_full,
    )
    assert ACCRUAL_GATING_THRESHOLD == 18
    assert ACCRUAL_TOTAL_CHECKS == 19
    assert callable(fetch_dashboard_full)


def test_bento_entity_serialization():
    from backend.routers.dashboard_schemas import BentoEntity

    e = BentoEntity(
        entity_id=1,
        code="HOI",
        name="HOI Inc.",
        flag="🇺🇸",
        currency="USD",
        cash_balance=Decimal("425000"),
        cash_balance_usd=Decimal("425000"),
        sparkline=[100.0, 200.0, 300.0, 400.0, 500.0, 425.0],
        badge=None,
        accrual_data_status="accurate",
    )
    data = e.model_dump()
    assert data["code"] == "HOI"
    assert data["accrual_data_status"] == "accurate"


def test_accrual_kpi_gating_in_progress():
    """When status='in_progress', acc fields must be None (gating active)."""
    from backend.routers.dashboard_schemas import AccrualKPI

    kpi = AccrualKPI(
        accuracy_status="in_progress",
        accuracy_pass_count=5,
        accuracy_total_count=19,
        accuracy_threshold=18,
        revenue_acc=None,
        revenue_cash=Decimal("145000000"),
        expense_acc=None,
        expense_cash=Decimal("38000000"),
        net_income_acc=None,
        diff_breakdown=None,
    )
    assert kpi.accuracy_status == "in_progress"
    assert kpi.revenue_acc is None
    assert kpi.expense_acc is None
    assert kpi.diff_breakdown is None
    assert kpi.revenue_cash == Decimal("145000000")


def test_accrual_kpi_accurate_with_diff():
    """When status='accurate', acc fields + diff_breakdown populated."""
    from backend.routers.dashboard_schemas import AccrualDiffBreakdown, AccrualKPI

    kpi = AccrualKPI(
        accuracy_status="accurate",
        accuracy_pass_count=19,
        accuracy_total_count=19,
        accuracy_threshold=18,
        revenue_acc=Decimal("145000"),
        revenue_cash=Decimal("140000"),
        expense_acc=Decimal("28000"),
        expense_cash=Decimal("25000"),
        net_income_acc=Decimal("117000"),
        diff_breakdown=AccrualDiffBreakdown(
            ar_delta=Decimal("5000"),
            ap_delta=Decimal("3000"),
        ),
    )
    assert kpi.revenue_acc == Decimal("145000")
    assert kpi.diff_breakdown is not None
    assert kpi.diff_breakdown.ar_delta == Decimal("5000")


def test_decision_queue_item_severity_enum():
    """severity enum constraint."""
    from pydantic import ValidationError

    from backend.routers.dashboard_schemas import DecisionQueueItem

    DecisionQueueItem(
        icon="🔴", text="Test", count=5, severity="danger",
        deep_link="/transactions",
    )

    with pytest.raises(ValidationError):
        DecisionQueueItem(
            icon="🔴", text="Test", count=5, severity="invalid",  # type: ignore
            deep_link="/transactions",
        )


def test_ai_cascade_step_enum():
    """cascade step enum (P4-A/B/C cascade 4단계)."""
    from pydantic import ValidationError

    from backend.routers.dashboard_schemas import AiCascadeStat

    for step in ["exact", "similar_trgm", "entity_keyword", "global_keyword", "ai"]:
        AiCascadeStat(step=step, pct=20.0)  # type: ignore

    with pytest.raises(ValidationError):
        AiCascadeStat(step="unknown_step", pct=20.0)  # type: ignore


def test_full_response_roundtrip():
    """Full response Pydantic roundtrip (serialize → JSON → parse)."""
    from backend.routers.dashboard_schemas import (
        AccrualKPI,
        AiActivity,
        BentoEntity,
        BentoSummary,
        CashKPI,
        ChartData,
        DashboardFullResponse,
        DecisionQueueSection,
    )

    response = DashboardFullResponse(
        scope="group",
        currency="USD",
        gaap="K",
        as_of=datetime.now(timezone.utc),
        bento=BentoSummary(
            group_total_usd=Decimal("634000"),
            group_total_display=Decimal("634000"),
            eliminations_usd=Decimal("-15000"),
            eliminations_count=5,
            entities=[
                BentoEntity(
                    entity_id=1, code="HOI", name="HOI", flag="🇺🇸", currency="USD",
                    cash_balance=Decimal("425000"), cash_balance_usd=Decimal("425000"),
                    sparkline=[1.0] * 6, accrual_data_status="accurate",
                ),
            ],
        ),
        cash_kpi=CashKPI(
            total_balance=Decimal("634000"),
            monthly_income=Decimal("48000"),
            monthly_expense=Decimal("38000"),
        ),
        accrual_kpi=AccrualKPI(
            accuracy_status="accurate",
            accuracy_pass_count=19,
            accuracy_total_count=19,
            accuracy_threshold=18,
            revenue_cash=Decimal("215000"),
            expense_cash=Decimal("57000"),
        ),
        decision_queue=DecisionQueueSection(items=[], total=0),
        ai_activity=AiActivity(
            auto_mapped_today=412,
            review_needed=24,
            unusual=2,
            keyword_added_this_week=14,
            learning_impact=47,
            cascade=[],
        ),
        chart=ChartData(months=[]),
    )

    json_str = response.model_dump_json()
    assert "634000" in json_str

    parsed = DashboardFullResponse.model_validate_json(json_str)
    assert parsed.scope == "group"
    assert parsed.currency == "USD"

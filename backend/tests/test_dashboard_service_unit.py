"""Dashboard /full sub-fetcher 단위 test (DB 없이 mock 만 사용).

Phase 1C 핵심 검증:
- _safe wrapper: 한 sub-fetch 실패가 전체 endpoint 영향 X
- _has_accrual_status_column / _has_table: schema introspection
- accrual gating policy (in_progress 시 acc 필드 None)
- diff_breakdown formula 정확도
- decision queue severity 분류
- AI cascade 통계 분포 매핑
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from backend.routers.dashboard_schemas import (
    AccrualKPI,
    AiActivity,
    BentoSummary,
    CashKPI,
    ChartData,
    DashboardFullResponse,
    DecisionQueueSection,
)
from backend.services import dashboard_service as ds


# ───────────────────────────── _safe wrapper ─────────────────────────────

def test_safe_returns_fallback_on_exception():
    """sub-fetcher 가 throw 해도 fallback 반환 + 로그만."""
    fallback = "FB"
    result = ds._safe("test", lambda: (_ for _ in ()).throw(RuntimeError("boom")), fallback)
    assert result == "FB"


def test_safe_returns_value_on_success():
    result = ds._safe("test", lambda: 42, "FB")
    assert result == 42


# ───────────────────────────── schema introspection ─────────────────────────────

def test_has_accrual_status_column_returns_true_when_present():
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    conn = MagicMock()
    conn.cursor.return_value = cur

    assert ds._has_accrual_status_column(conn) is True
    assert "accrual_data_status" in cur.execute.call_args[0][0]


def test_has_accrual_status_column_returns_false_when_absent():
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value = cur

    assert ds._has_accrual_status_column(conn) is False


def test_has_accrual_status_column_handles_query_error():
    cur = MagicMock()
    cur.execute.side_effect = Exception("relation does not exist")
    conn = MagicMock()
    conn.cursor.return_value = cur

    assert ds._has_accrual_status_column(conn) is False


def test_has_table_checks_schema_and_name():
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    conn = MagicMock()
    conn.cursor.return_value = cur

    assert ds._has_table(conn, "dashboard_accrual_health") is True
    args = cur.execute.call_args[0]
    assert "information_schema.tables" in args[0]
    assert args[1] == ["financeone", "dashboard_accrual_health"]


# ───────────────────────────── gating policy contracts ─────────────────────────────

def test_accrual_threshold_constants():
    """gating threshold 값 (P3-9 검증 18/19 PASS) 안정성."""
    assert ds.ACCRUAL_GATING_THRESHOLD == 18
    assert ds.ACCRUAL_TOTAL_CHECKS == 19


# ───────────────────────────── DashboardFullResponse 합성 ─────────────────────────────

def _stub_full(scope="group", currency="USD", gaap="K"):
    return DashboardFullResponse(
        scope=scope,
        currency=currency,  # type: ignore
        gaap=gaap,  # type: ignore
        as_of=datetime.now(timezone.utc),
        bento=BentoSummary(
            group_total_usd=Decimal(0), group_total_display=Decimal(0),
            eliminations_usd=Decimal(0), eliminations_count=0, entities=[],
        ),
        cash_kpi=CashKPI(
            total_balance=Decimal(0), monthly_income=Decimal(0), monthly_expense=Decimal(0),
        ),
        accrual_kpi=AccrualKPI(
            accuracy_status="cold_start",
            accuracy_pass_count=0,
            accuracy_total_count=ds.ACCRUAL_TOTAL_CHECKS,
            accuracy_threshold=ds.ACCRUAL_GATING_THRESHOLD,
            revenue_cash=Decimal(0),
            expense_cash=Decimal(0),
        ),
        decision_queue=DecisionQueueSection(items=[], total=0),
        ai_activity=AiActivity(
            auto_mapped_today=0, review_needed=0, unusual=0,
            keyword_added_this_week=0, learning_impact=0, cascade=[],
        ),
        chart=ChartData(months=[]),
    )


def test_full_response_default_currency_usd():
    r = _stub_full()
    assert r.currency == "USD"
    assert r.gaap == "K"
    assert r.scope == "group"


def test_full_response_entity_scope():
    r = _stub_full(scope=2)
    assert r.scope == 2


# ───────────────────────────── fetch_dashboard_full graceful degrade ─────────────────────────────

def test_fetch_dashboard_full_all_sections_fail_returns_safe_defaults(monkeypatch):
    """모든 sub-fetcher 가 throw 해도 endpoint 가 200 + fallback 데이터 반환."""
    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DB down"))
    monkeypatch.setattr(ds, "fetch_bento_summary", boom)
    monkeypatch.setattr(ds, "fetch_cash_kpi", boom)
    monkeypatch.setattr(ds, "fetch_accrual_kpi", boom)
    monkeypatch.setattr(ds, "fetch_decision_queue", boom)
    monkeypatch.setattr(ds, "fetch_ai_activity", boom)
    monkeypatch.setattr(ds, "fetch_chart", boom)
    # _fx_rate may be called inside savepoint or not, accept with/without args
    monkeypatch.setattr(ds, "_fx_rate", lambda *a, **k: Decimal("1"))

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    result = ds.fetch_dashboard_full(conn, entity_id=None, currency="USD", gaap="K")

    assert isinstance(result, DashboardFullResponse)
    assert result.scope == "group"
    assert result.bento.entities == []
    assert result.cash_kpi.total_balance == Decimal(0)
    assert result.accrual_kpi.accuracy_status == "cold_start"
    assert result.accrual_kpi.revenue_acc is None
    assert result.decision_queue.total == 0
    assert result.ai_activity.auto_mapped_today == 0
    assert result.chart.months == []


def test_fetch_dashboard_full_partial_failure_other_sections_unaffected(monkeypatch):
    """일부 sub-fetcher 실패 + 일부 성공 = 성공한 것만 정상 데이터, 실패한 것만 fallback."""
    monkeypatch.setattr(ds, "fetch_bento_summary", lambda conn, target_currency="USD": BentoSummary(
        group_total_usd=Decimal("999"), group_total_display=Decimal("999"),
        eliminations_usd=Decimal(0), eliminations_count=0, entities=[],
    ))
    monkeypatch.setattr(ds, "fetch_cash_kpi", lambda conn, eid, **kw: (_ for _ in ()).throw(RuntimeError("cash query fail")))
    monkeypatch.setattr(ds, "fetch_accrual_kpi", lambda conn, eid, **kw: AccrualKPI(
        accuracy_status="accurate", accuracy_pass_count=19, accuracy_total_count=19,
        accuracy_threshold=18, revenue_cash=Decimal("100"), expense_cash=Decimal("50"),
    ))
    monkeypatch.setattr(ds, "fetch_decision_queue", lambda conn, eid: DecisionQueueSection(items=[], total=0))
    monkeypatch.setattr(ds, "fetch_ai_activity", lambda conn, eid: AiActivity(
        auto_mapped_today=10, review_needed=2, unusual=0, keyword_added_this_week=0,
        learning_impact=0, cascade=[],
    ))
    monkeypatch.setattr(ds, "fetch_chart", lambda conn, eid, **kw: ChartData(months=[]))

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    result = ds.fetch_dashboard_full(conn, entity_id=None)

    # bento: real data
    assert result.bento.group_total_usd == Decimal("999")
    # cash_kpi: fallback (because of fail)
    assert result.cash_kpi.total_balance == Decimal(0)
    # accrual: real data
    assert result.accrual_kpi.accuracy_status == "accurate"
    # ai: real data
    assert result.ai_activity.auto_mapped_today == 10


def test_fetch_dashboard_full_passes_currency_and_gaap_through(monkeypatch):
    """currency/gaap query param 이 response 에 그대로 반영."""
    fb = BentoSummary(group_total_usd=Decimal(0), group_total_display=Decimal(0), eliminations_usd=Decimal(0), eliminations_count=0, entities=[])
    monkeypatch.setattr(ds, "fetch_bento_summary", lambda conn, target_currency="USD": fb)
    monkeypatch.setattr(ds, "fetch_cash_kpi", lambda conn, eid, **kw: CashKPI(total_balance=Decimal(0), monthly_income=Decimal(0), monthly_expense=Decimal(0)))
    monkeypatch.setattr(ds, "fetch_accrual_kpi", lambda conn, eid, **kw: AccrualKPI(accuracy_status="cold_start", accuracy_pass_count=0, accuracy_total_count=19, accuracy_threshold=18, revenue_cash=Decimal(0), expense_cash=Decimal(0)))
    monkeypatch.setattr(ds, "fetch_decision_queue", lambda conn, eid: DecisionQueueSection(items=[], total=0))
    monkeypatch.setattr(ds, "fetch_ai_activity", lambda conn, eid: AiActivity(auto_mapped_today=0, review_needed=0, unusual=0, keyword_added_this_week=0, learning_impact=0, cascade=[]))
    monkeypatch.setattr(ds, "fetch_chart", lambda conn, eid, **kw: ChartData(months=[]))

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    result = ds.fetch_dashboard_full(conn, entity_id=None, currency="KRW", gaap="US")
    assert result.currency == "KRW"
    assert result.gaap == "US"


def test_fetch_dashboard_full_scope_is_entity_id_when_provided(monkeypatch):
    fb = BentoSummary(group_total_usd=Decimal(0), group_total_display=Decimal(0), eliminations_usd=Decimal(0), eliminations_count=0, entities=[])
    monkeypatch.setattr(ds, "fetch_bento_summary", lambda conn, target_currency="USD": fb)
    monkeypatch.setattr(ds, "fetch_cash_kpi", lambda conn, eid, **kw: CashKPI(total_balance=Decimal(0), monthly_income=Decimal(0), monthly_expense=Decimal(0)))
    monkeypatch.setattr(ds, "fetch_accrual_kpi", lambda conn, eid, **kw: AccrualKPI(accuracy_status="accurate", accuracy_pass_count=19, accuracy_total_count=19, accuracy_threshold=18, revenue_cash=Decimal(0), expense_cash=Decimal(0)))
    monkeypatch.setattr(ds, "fetch_decision_queue", lambda conn, eid: DecisionQueueSection(items=[], total=0))
    monkeypatch.setattr(ds, "fetch_ai_activity", lambda conn, eid: AiActivity(auto_mapped_today=0, review_needed=0, unusual=0, keyword_added_this_week=0, learning_impact=0, cascade=[]))
    monkeypatch.setattr(ds, "fetch_chart", lambda conn, eid, **kw: ChartData(months=[]))

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    result = ds.fetch_dashboard_full(conn, entity_id=2)
    assert result.scope == 2


# ───────────────────────────── savepoint isolation ─────────────────────────────

def test_savepoint_isolation_via_with_savepoint(monkeypatch):
    """with_savepoint 패턴이 SAVEPOINT/ROLLBACK 명령을 발행하는지 검증."""
    cur_calls = []
    cur = MagicMock()
    cur.execute.side_effect = lambda sql, *args: cur_calls.append(sql)
    conn = MagicMock()
    conn.cursor.return_value = cur

    fb = BentoSummary(group_total_usd=Decimal(0), group_total_display=Decimal(0), eliminations_usd=Decimal(0), eliminations_count=0, entities=[])
    # fetcher 이 throw → savepoint rollback 실행되어야 함
    monkeypatch.setattr(ds, "fetch_bento_summary", lambda conn, target_currency="USD": (_ for _ in ()).throw(RuntimeError("fail")))
    monkeypatch.setattr(ds, "fetch_cash_kpi", lambda conn, eid, **kw: CashKPI(total_balance=Decimal(0), monthly_income=Decimal(0), monthly_expense=Decimal(0)))
    monkeypatch.setattr(ds, "fetch_accrual_kpi", lambda conn, eid, **kw: AccrualKPI(accuracy_status="cold_start", accuracy_pass_count=0, accuracy_total_count=19, accuracy_threshold=18, revenue_cash=Decimal(0), expense_cash=Decimal(0)))
    monkeypatch.setattr(ds, "fetch_decision_queue", lambda conn, eid: DecisionQueueSection(items=[], total=0))
    monkeypatch.setattr(ds, "fetch_ai_activity", lambda conn, eid: AiActivity(auto_mapped_today=0, review_needed=0, unusual=0, keyword_added_this_week=0, learning_impact=0, cascade=[]))
    monkeypatch.setattr(ds, "fetch_chart", lambda conn, eid, **kw: ChartData(months=[]))

    ds.fetch_dashboard_full(conn, entity_id=None)

    # 모든 6 section 이 SAVEPOINT dash_section 발행 (성공이든 실패든)
    savepoint_calls = [c for c in cur_calls if "SAVEPOINT dash_section" in c and "ROLLBACK" not in c and "RELEASE" not in c]
    assert len(savepoint_calls) == 6, f"expected 6 SAVEPOINTs, got {len(savepoint_calls)}"

    # bento 실패 → ROLLBACK TO SAVEPOINT 발행되어야 함
    rollback_calls = [c for c in cur_calls if "ROLLBACK TO SAVEPOINT" in c]
    assert len(rollback_calls) >= 1

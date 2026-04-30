"""Dashboard /full + /accrual endpoint schemas.

Design doc: ~/.gstack/projects/shawnha-financeOne/admin-main-design-20260430-215309.md
plan-eng-review A1 (batch endpoint) + A2 (per-entity gating) + A6 (server diff explainer).
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Bento Entity ──────────────────────────────────────────

class BentoEntity(BaseModel):
    entity_id: int
    code: str                          # 'HOI', 'HOK', 'HOR', 'HOW'
    name: str                          # display name
    flag: str                          # emoji flag
    currency: str                      # native currency 'USD' | 'KRW'
    cash_balance: Decimal              # native currency amount
    cash_balance_usd: Decimal          # USD-equivalent for Group sort/sum
    sparkline: List[float]             # 6 monthly cash balances (most recent last)
    badge: Optional[str] = None        # e.g., '미확정 12'
    accrual_data_status: Literal['accurate', 'in_progress', 'cold_start']


class BentoSummary(BaseModel):
    group_total_usd: Decimal
    group_total_display: Decimal              # 사용자 선택 currency 로 환산된 값
    eliminations_usd: Decimal
    eliminations_count: int
    entities: List[BentoEntity]


# ── Cash KPI (always available) ────────────────────────────

class CashKPI(BaseModel):
    total_balance: Decimal
    monthly_income: Decimal
    monthly_expense: Decimal
    income_change_pct: Optional[float] = None
    expense_change_pct: Optional[float] = None
    runway_months: Optional[float] = None


# ── Accrual KPI (gated) ────────────────────────────────────

class AccrualDiffBreakdown(BaseModel):
    """Reconciliation: acc_revenue - cash_revenue = ΔAR + Δdeferred - bad_debt
    Same pattern for expense: acc_expense - cash_expense = ΔAP + ΔAccrued - returns
    """
    ar_delta: Decimal = Decimal(0)               # 외상매출금 증가분
    deferred_revenue_delta: Decimal = Decimal(0) # 선수금 증가분
    bad_debt_writeoff: Decimal = Decimal(0)
    ap_delta: Decimal = Decimal(0)               # 외상매입금 증가분
    accrued_expense_delta: Decimal = Decimal(0)  # 미지급비용 증가분
    purchase_returns: Decimal = Decimal(0)


class AccrualKPI(BaseModel):
    """Per-entity accrual gating (plan-eng-review A2).

    accuracy_status='in_progress' 시 모든 _acc 필드 = None (UI placeholder).
    accuracy_status='accurate' or 'cold_start' 시 정상 값.
    """
    accuracy_status: Literal['accurate', 'in_progress', 'cold_start']
    accuracy_pass_count: int                     # e.g., 5
    accuracy_total_count: int                    # 19
    accuracy_threshold: int                      # 18 (gating cutoff)
    accuracy_last_run: Optional[datetime] = None

    revenue_acc: Optional[Decimal] = None        # null if gating active
    revenue_cash: Decimal
    expense_acc: Optional[Decimal] = None
    expense_cash: Decimal
    net_income_acc: Optional[Decimal] = None
    diff_breakdown: Optional[AccrualDiffBreakdown] = None


# ── Decision Queue ─────────────────────────────────────────

class DecisionQueueItem(BaseModel):
    icon: str                                    # 🔴 / 🟡 / 📨 / ⚖️ / 📊
    text: str
    count: int
    severity: Literal['danger', 'warn', 'info']
    deep_link: str                               # /transactions?... or other route


class DecisionQueueSection(BaseModel):
    items: List[DecisionQueueItem]
    total: int


# ── AI Activity ────────────────────────────────────────────

class AiCascadeStat(BaseModel):
    step: Literal['exact', 'similar_trgm', 'entity_keyword', 'global_keyword', 'ai']
    pct: float                                   # 0-100


class AiActivity(BaseModel):
    auto_mapped_today: int                       # confidence ≥ 0.98
    review_needed: int                           # 0.70 ≤ confidence < 0.98
    unusual: int                                 # outliers (3σ / new vendor / duplicate)
    keyword_added_this_week: int                 # learning signal
    learning_impact: int                         # estimated future auto-map count
    cascade: List[AiCascadeStat]


# ── Chart (cash + accrual + forecast hook) ─────────────────

class ChartMonthPoint(BaseModel):
    month: str                                   # 'YYYY-MM'
    cash_in: Decimal                             # 통장 in
    cash_out: Decimal                            # 통장 out
    accrual_revenue: Optional[Decimal] = None    # invoice 발행 (gating 적용)
    is_forecast: bool = False                    # Phase 5+ hook (V1 = always False)


class ChartData(BaseModel):
    months: List[ChartMonthPoint]                # 최근 6 + (Phase 5+) 예상 2


# ── Full response (batch) ──────────────────────────────────

class DashboardFullResponse(BaseModel):
    """Single batch endpoint response.

    Frontend 가 6 widget data 한 번에 받아 클라이언트 1 query/click 으로 Bento 전환.
    """
    scope: Union[Literal['group'], int]          # 'group' or entity_id
    currency: Literal['USD', 'KRW']
    gaap: Literal['US', 'K']
    as_of: datetime

    bento: BentoSummary
    cash_kpi: CashKPI
    accrual_kpi: AccrualKPI                      # gating-aware
    decision_queue: DecisionQueueSection
    ai_activity: AiActivity
    chart: ChartData


# ── Health check (for /dashboard/accrual-health) ───────────

class AccrualHealthEntry(BaseModel):
    entity_id: int
    entity_code: str
    pass_count: int
    total_count: int
    status: Literal['accurate', 'in_progress', 'cold_start', 'unknown']
    last_run: Optional[datetime] = None


class AccrualHealthResponse(BaseModel):
    entries: List[AccrualHealthEntry]
    overall_status: Literal['all_accurate', 'mixed', 'all_in_progress']
    refreshed_at: datetime

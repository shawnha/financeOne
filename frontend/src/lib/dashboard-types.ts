// Mirror of backend/routers/dashboard_schemas.py — keep in sync.
// design doc: ~/.gstack/projects/shawnha-financeOne/admin-main-design-20260430-215309.md

export type AccrualStatus = "accurate" | "in_progress" | "cold_start"
export type DecisionSeverity = "danger" | "warn" | "info"
export type CascadeStep =
  | "exact"
  | "similar_trgm"
  | "entity_keyword"
  | "global_keyword"
  | "ai"
export type Currency = "USD" | "KRW"
export type Gaap = "US" | "K"
export type Scope = "group" | number

export interface BentoEntity {
  entity_id: number
  code: string
  name: string
  flag: string
  currency: string
  cash_balance: string  // Decimal serialized as string
  cash_balance_usd: string
  sparkline: number[]
  badge?: string | null
  accrual_data_status: AccrualStatus
}

export interface BentoSummary {
  group_total_usd: string
  group_total_display: string  // 사용자 선택 currency 환산
  eliminations_usd: string
  eliminations_count: number
  entities: BentoEntity[]
}

export interface CashKPI {
  total_balance: string
  monthly_income: string
  monthly_expense: string
  income_change_pct?: number | null
  expense_change_pct?: number | null
  runway_months?: number | null
}

export interface AccrualDiffBreakdown {
  ar_delta: string
  deferred_revenue_delta: string
  bad_debt_writeoff: string
  ap_delta: string
  accrued_expense_delta: string
  purchase_returns: string
}

export interface AccrualKPI {
  accuracy_status: AccrualStatus
  accuracy_pass_count: number
  accuracy_total_count: number
  accuracy_threshold: number
  accuracy_last_run?: string | null
  revenue_acc?: string | null
  revenue_cash: string
  expense_acc?: string | null
  expense_cash: string
  net_income_acc?: string | null
  diff_breakdown?: AccrualDiffBreakdown | null
}

export interface DecisionQueueItem {
  icon: string
  text: string
  count: number
  severity: DecisionSeverity
  deep_link: string
}

export interface DecisionQueueSection {
  items: DecisionQueueItem[]
  total: number
}

export interface AiCascadeStat {
  step: CascadeStep
  pct: number
}

export interface AiActivity {
  auto_mapped_today: number
  review_needed: number
  unusual: number
  keyword_added_this_week: number
  learning_impact: number
  cascade: AiCascadeStat[]
}

export interface ChartMonthPoint {
  month: string
  cash_in: string
  cash_out: string
  accrual_revenue?: string | null
  is_forecast: boolean
}

export interface ChartData {
  months: ChartMonthPoint[]
}

export interface DashboardFullResponse {
  scope: Scope
  currency: Currency
  gaap: Gaap
  as_of: string
  bento: BentoSummary
  cash_kpi: CashKPI
  accrual_kpi: AccrualKPI
  decision_queue: DecisionQueueSection
  ai_activity: AiActivity
  chart: ChartData
}

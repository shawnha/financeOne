"""Dashboard /full + /accrual data fetchers.

Per design doc + plan-eng-review:
- A1 batch endpoint (single GET /dashboard/full → 6 widget data)
- A2 per-entity accrual gating (entities.accrual_data_status)
- A3 dashboard_accrual_health view (cached verify_bs_against_ledger)
- A6 server-computed diff explainer
- A7 single SQL aggregate (no N+1)
- A8 cross-schema search_path (already set in connection.py)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Union

from psycopg2.extensions import connection as PgConnection

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

# Gating threshold (verify_bs_against_ledger PASS count cutoff)
ACCRUAL_GATING_THRESHOLD = 18
ACCRUAL_TOTAL_CHECKS = 19


# ─────────────────────────────────────────────────────────────
# Bento Summary — all entities cash balance + sparkline (single query)
# ─────────────────────────────────────────────────────────────

def _has_accrual_status_column(conn: PgConnection) -> bool:
    """Schema introspection: graceful fallback when migration not run yet."""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='financeone'
              AND table_name='entities'
              AND column_name='accrual_data_status'
            LIMIT 1
        """)
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        cur.close()


def _has_table(conn: PgConnection, table_name: str, schema: str = "financeone") -> bool:
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema=%s AND table_name=%s LIMIT 1
        """, [schema, table_name])
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        cur.close()


def fetch_bento_summary(conn: PgConnection, target_currency: str = "USD") -> BentoSummary:
    """5 entity (Group + 4) cash balance + sparkline. Single SQL aggregate.

    cash_balance = latest balance_snapshots per (entity, account_name) 합계.
    sparkline = 최근 6 monthly 잔고 추이.
    """
    cur = conn.cursor()
    has_accrual_col = _has_accrual_status_column(conn)

    # 1) entity 목록 + accrual_data_status (optional) + 현재 잔고
    accrual_select = "e.accrual_data_status" if has_accrual_col else "'cold_start' AS accrual_data_status"
    cur.execute(f"""
        SELECT
            e.id, e.code, e.name, e.currency, {accrual_select},
            COALESCE(b.cash_balance, 0) AS cash_balance
        FROM financeone.entities e
        LEFT JOIN (
            SELECT entity_id, SUM(balance) AS cash_balance
            FROM (
                SELECT DISTINCT ON (entity_id, account_name) entity_id, account_name, balance
                FROM financeone.balance_snapshots
                ORDER BY entity_id, account_name, date DESC
            ) latest
            GROUP BY entity_id
        ) b ON b.entity_id = e.id
        WHERE e.is_active IS NOT FALSE
        ORDER BY e.id
    """)
    entity_rows = cur.fetchall()

    # 2) sparkline: 6 monthly cash 잔고 (per entity, single GROUP BY)
    cur.execute("""
        SELECT
            entity_id,
            to_char(date_trunc('month', date), 'YYYY-MM') AS ym,
            SUM(CASE WHEN type='in' THEN amount ELSE -amount END) AS net
        FROM financeone.transactions
        WHERE date >= date_trunc('month', CURRENT_DATE) - interval '5 months'
          AND (is_cancel IS NOT TRUE)
        GROUP BY entity_id, date_trunc('month', date)
        ORDER BY entity_id, ym
    """)
    spark_data: dict[int, list[float]] = {}
    for entity_id, ym, net in cur.fetchall():
        spark_data.setdefault(entity_id, []).append(float(net))

    # 3) badge: 미확정 거래 수
    cur.execute("""
        SELECT entity_id, COUNT(*)
        FROM financeone.transactions
        WHERE is_confirmed = false AND (is_cancel IS NOT TRUE)
        GROUP BY entity_id
    """)
    unconfirmed: dict[int, int] = {row[0]: row[1] for row in cur.fetchall()}

    # 4) USD 환산 (Group sort/sum)
    # 단순화: HOI USD = native, KR_CORP KRW → USD via simple FX
    # TODO: production 은 exchange_rate_service 사용 (Phase 1A V2)
    KRW_TO_USD = Decimal("0.00075")  # placeholder

    entities = []
    group_total_usd = Decimal(0)
    for row in entity_rows:
        entity_id, code, name, currency, accrual_status, cash_balance = row
        cash = Decimal(cash_balance)
        cash_usd = cash if currency == "USD" else cash * KRW_TO_USD

        flag = "🇺🇸" if currency == "USD" else "🇰🇷"
        badge = f"미확정 {unconfirmed[entity_id]}" if entity_id in unconfirmed else None

        entities.append(BentoEntity(
            entity_id=entity_id,
            code=code,
            name=name,
            flag=flag,
            currency=currency,
            cash_balance=cash,
            cash_balance_usd=cash_usd,
            sparkline=spark_data.get(entity_id, [0.0] * 6),
            badge=badge,
            accrual_data_status=accrual_status,
        ))
        group_total_usd += cash_usd

    # 5) eliminations (intercompany matched count + amount)
    # TODO: intercompany_pairs.amount sum (Phase 1A V2)
    eliminations_count = 0
    eliminations_usd = Decimal(0)

    cur.close()

    return BentoSummary(
        group_total_usd=group_total_usd,
        eliminations_usd=eliminations_usd,
        eliminations_count=eliminations_count,
        entities=entities,
    )


# ─────────────────────────────────────────────────────────────
# Cash KPI — existing /dashboard pattern, adapted for batch endpoint
# ─────────────────────────────────────────────────────────────

def fetch_cash_kpi(conn: PgConnection, entity_id: Optional[int]) -> CashKPI:
    cur = conn.cursor()
    params: list = [entity_id] if entity_id else []

    # 총잔고
    cur.execute(f"""
        SELECT COALESCE(SUM(balance), 0)
        FROM financeone.balance_snapshots
        WHERE (entity_id, date, account_name) IN (
            SELECT entity_id, MAX(date), account_name
            FROM financeone.balance_snapshots
            {"WHERE entity_id = %s" if entity_id else ""}
            GROUP BY entity_id, account_name
        )
    """, params)
    total_balance = Decimal(cur.fetchone()[0])

    # 이번달 수입/지출
    cur.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN type='in' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type='out' THEN amount ELSE 0 END), 0)
        FROM financeone.transactions
        WHERE date >= date_trunc('month', CURRENT_DATE)
          AND date < date_trunc('month', CURRENT_DATE) + interval '1 month'
          AND (is_cancel IS NOT TRUE)
          {"AND entity_id = %s" if entity_id else ""}
    """, params)
    monthly_income, monthly_expense = (Decimal(v) for v in cur.fetchone())

    # 전월 (MoM)
    cur.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN type='in' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type='out' THEN amount ELSE 0 END), 0)
        FROM financeone.transactions
        WHERE date >= date_trunc('month', CURRENT_DATE) - interval '1 month'
          AND date < date_trunc('month', CURRENT_DATE)
          AND (is_cancel IS NOT TRUE)
          {"AND entity_id = %s" if entity_id else ""}
    """, params)
    prev_income, prev_expense = (Decimal(v) for v in cur.fetchone())

    def pct_change(current: Decimal, previous: Decimal) -> Optional[float]:
        if previous == 0:
            return None
        return round(float((current - previous) / previous * 100), 1)

    avg_expense = monthly_expense if monthly_expense > 0 else Decimal(1)
    runway = round(float(total_balance / avg_expense), 1) if avg_expense > 0 else None

    cur.close()

    return CashKPI(
        total_balance=total_balance,
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        income_change_pct=pct_change(monthly_income, prev_income),
        expense_change_pct=pct_change(monthly_expense, prev_expense),
        runway_months=runway,
    )


# ─────────────────────────────────────────────────────────────
# Accrual KPI — gated by entities.accrual_data_status
# ─────────────────────────────────────────────────────────────

def fetch_accrual_kpi(conn: PgConnection, entity_id: Optional[int]) -> AccrualKPI:
    """Gating policy:
    - entity_id=None (Group): accuracy_status = worst of all entities
    - 'in_progress': accrual fields = None, only revenue_cash/expense_cash
    - 'accurate' or 'cold_start': real accrual numbers
    """
    cur = conn.cursor()
    has_accrual_col = _has_accrual_status_column(conn)
    has_health_table = _has_table(conn, "dashboard_accrual_health")

    # Determine accuracy status (graceful fallback if migration not run)
    if not has_accrual_col:
        status, pass_count, total_count, last_run = ('cold_start', 0, ACCRUAL_TOTAL_CHECKS, None)
    else:
        health_join = "LEFT JOIN financeone.dashboard_accrual_health h ON h.entity_id = e.id" if has_health_table else ""
        h_pass = "COALESCE(MIN(h.pass_count), 0)" if has_health_table else "0"
        h_total = "COALESCE(MIN(h.total_count), 19)" if has_health_table else "19"
        h_last = "MAX(h.last_run)" if has_health_table else "NULL"
        h_pass_one = "COALESCE(h.pass_count, 0)" if has_health_table else "0"
        h_total_one = "COALESCE(h.total_count, 19)" if has_health_table else "19"
        h_last_one = "h.last_run" if has_health_table else "NULL"

        if entity_id is None:
            cur.execute(f"""
                SELECT
                    CASE
                        WHEN bool_or(accrual_data_status='in_progress') THEN 'in_progress'
                        WHEN bool_and(accrual_data_status='accurate') THEN 'accurate'
                        ELSE 'cold_start'
                    END,
                    {h_pass}, {h_total}, {h_last}
                FROM financeone.entities e
                {health_join}
                WHERE e.is_active IS NOT FALSE
            """)
        else:
            cur.execute(f"""
                SELECT
                    e.accrual_data_status, {h_pass_one}, {h_total_one}, {h_last_one}
                FROM financeone.entities e
                {health_join}
                WHERE e.id = %s
            """, [entity_id])

        row = cur.fetchone() or ('cold_start', 0, ACCRUAL_TOTAL_CHECKS, None)
        status, pass_count, total_count, last_run = row

    params: list = [entity_id] if entity_id else []

    # Cash side (always available)
    cur.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN type='in' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type='out' THEN amount ELSE 0 END), 0)
        FROM financeone.transactions
        WHERE date >= date_trunc('month', CURRENT_DATE)
          AND (is_cancel IS NOT TRUE)
          {"AND entity_id = %s" if entity_id else ""}
    """, params)
    revenue_cash, expense_cash = (Decimal(v) for v in cur.fetchone())

    # Accrual side (gating)
    if status == 'in_progress':
        cur.close()
        return AccrualKPI(
            accuracy_status='in_progress',
            accuracy_pass_count=pass_count,
            accuracy_total_count=total_count,
            accuracy_threshold=ACCRUAL_GATING_THRESHOLD,
            accuracy_last_run=last_run,
            revenue_acc=None,
            revenue_cash=revenue_cash,
            expense_acc=None,
            expense_cash=expense_cash,
            net_income_acc=None,
            diff_breakdown=None,
        )

    # accrual revenue / expense from journal_entries
    # 매출 = 4xxxx (수익) credit / 비용 = 5xxxx-9xxxx debit
    # 단순화: standard_accounts.category 기준
    cur.execute(f"""
        SELECT
            COALESCE(SUM(CASE
                WHEN sa.category = '수익' THEN je.credit - je.debit
                ELSE 0 END), 0) AS revenue_acc,
            COALESCE(SUM(CASE
                WHEN sa.category IN ('비용', '매출원가') THEN je.debit - je.credit
                ELSE 0 END), 0) AS expense_acc
        FROM financeone.journal_entries je
        JOIN financeone.standard_accounts sa ON sa.id = je.standard_account_id
        WHERE je.posted_at >= date_trunc('month', CURRENT_DATE)
          AND je.posted_at < date_trunc('month', CURRENT_DATE) + interval '1 month'
          {"AND je.entity_id = %s" if entity_id else ""}
    """, params)
    revenue_acc, expense_acc = (Decimal(v) for v in cur.fetchone())

    # diff breakdown (server computed)
    # ΔAR = 외상매출금 (10800) 증가분, Δdeferred = 선수금 (23xxx)
    cur.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN sa.code='10800' THEN je.debit - je.credit ELSE 0 END), 0) AS ar_delta,
            COALESCE(SUM(CASE WHEN sa.code LIKE '232%%' THEN je.credit - je.debit ELSE 0 END), 0) AS deferred_delta,
            COALESCE(SUM(CASE WHEN sa.code='25100' THEN je.credit - je.debit ELSE 0 END), 0) AS ap_delta,
            COALESCE(SUM(CASE WHEN sa.code='26200' THEN je.credit - je.debit ELSE 0 END), 0) AS accrued_delta
        FROM financeone.journal_entries je
        JOIN financeone.standard_accounts sa ON sa.id = je.standard_account_id
        WHERE je.posted_at >= date_trunc('month', CURRENT_DATE)
          AND je.posted_at < date_trunc('month', CURRENT_DATE) + interval '1 month'
          {"AND je.entity_id = %s" if entity_id else ""}
    """, params)
    ar_delta, deferred_delta, ap_delta, accrued_delta = (Decimal(v) for v in cur.fetchone())

    cur.close()

    return AccrualKPI(
        accuracy_status=status,
        accuracy_pass_count=pass_count,
        accuracy_total_count=total_count,
        accuracy_threshold=ACCRUAL_GATING_THRESHOLD,
        accuracy_last_run=last_run,
        revenue_acc=revenue_acc,
        revenue_cash=revenue_cash,
        expense_acc=expense_acc,
        expense_cash=expense_cash,
        net_income_acc=revenue_acc - expense_acc,
        diff_breakdown=AccrualDiffBreakdown(
            ar_delta=ar_delta,
            deferred_revenue_delta=deferred_delta,
            ap_delta=ap_delta,
            accrued_expense_delta=accrued_delta,
        ),
    )


# ─────────────────────────────────────────────────────────────
# Decision Queue — confidence < 0.7 + intercompany 미매칭 + 이상치 + slack 매칭
# ─────────────────────────────────────────────────────────────

def fetch_decision_queue(conn: PgConnection, entity_id: Optional[int]) -> DecisionQueueSection:
    cur = conn.cursor()
    params: list = [entity_id] if entity_id else []
    items: list[DecisionQueueItem] = []

    # 1) AI 매핑 검토 (confidence < 0.7)
    cur.execute(f"""
        SELECT COUNT(*)
        FROM financeone.transactions
        WHERE mapping_confidence IS NOT NULL
          AND mapping_confidence < 0.7
          AND is_confirmed = false
          AND (is_cancel IS NOT TRUE)
          {"AND entity_id = %s" if entity_id else ""}
    """, params)
    low_conf = cur.fetchone()[0]
    if low_conf > 0:
        eid_q = f"&entity_id={entity_id}" if entity_id else ""
        items.append(DecisionQueueItem(
            icon="🟡", text="AI 매핑 신뢰도 70% 미만 거래", count=low_conf,
            severity="warn", deep_link=f"/transactions?confidence_lt=0.7{eid_q}",
        ))

    # 2) 미확정 거래 (전체)
    cur.execute(f"""
        SELECT COUNT(*)
        FROM financeone.transactions
        WHERE is_confirmed = false AND (is_cancel IS NOT TRUE)
          {"AND entity_id = %s" if entity_id else ""}
    """, params)
    unconfirmed = cur.fetchone()[0]
    if unconfirmed > 0:
        eid_q = f"&entity=" + str(entity_id) if entity_id else ""
        items.append(DecisionQueueItem(
            icon="📋", text=f"미확정 거래", count=unconfirmed,
            severity="info", deep_link=f"/transactions?is_confirmed=false{eid_q}",
        ))

    # 3) intercompany 미매칭 (intercompany_pairs)
    try:
        cur.execute(f"""
            SELECT COUNT(*)
            FROM financeone.intercompany_pairs
            WHERE matched_at IS NULL
              {"AND (entity_a_id = %s OR entity_b_id = %s)" if entity_id else ""}
        """, [entity_id, entity_id] if entity_id else [])
        ic_unmatched = cur.fetchone()[0]
        if ic_unmatched > 0:
            items.append(DecisionQueueItem(
                icon="⚖️", text="intercompany 미매칭", count=ic_unmatched,
                severity="warn", deep_link="/intercompany",
            ))
    except Exception:
        # intercompany_pairs 테이블 부재 가능성
        pass

    # 4) ExpenseOne 미매칭 (entity_id=2 한아원코리아 only)
    if entity_id is None or entity_id == 2:
        try:
            cur.execute("""
                SELECT COUNT(*) FROM financeone.transactions
                WHERE entity_id = 2
                  AND source_type LIKE 'expenseone_%%'
                  AND internal_account_id IS NULL
            """)
            eo_unmatched = cur.fetchone()[0]
            if eo_unmatched > 0:
                items.append(DecisionQueueItem(
                    icon="📨", text="ExpenseOne 미매칭", count=eo_unmatched,
                    severity="warn",
                    deep_link="/transactions?entity=2&source_type=expenseone_card,expenseone_deposit&unconfirmed=true",
                ))
        except Exception:
            pass

    cur.close()

    return DecisionQueueSection(
        items=items,
        total=sum(item.count for item in items),
    )


# ─────────────────────────────────────────────────────────────
# AI Activity — cascade 통계 + 학습 신호
# ─────────────────────────────────────────────────────────────

def fetch_ai_activity(conn: PgConnection, entity_id: Optional[int]) -> AiActivity:
    cur = conn.cursor()
    params: list = [entity_id] if entity_id else []

    # auto_mapped_today (confidence ≥ 0.98)
    cur.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE mapping_confidence >= 0.98),
            COUNT(*) FILTER (WHERE mapping_confidence >= 0.70 AND mapping_confidence < 0.98),
            0 AS unusual
        FROM financeone.transactions
        WHERE created_at >= CURRENT_DATE
          AND mapping_confidence IS NOT NULL
          {"AND entity_id = %s" if entity_id else ""}
    """, params)
    auto_mapped, review_needed, unusual = cur.fetchone()

    # learning signal: 이번 주 keyword 추가 수
    try:
        cur.execute("""
            SELECT COUNT(*)
            FROM financeone.standard_account_keywords
            WHERE created_at >= date_trunc('week', CURRENT_DATE)
        """)
        keyword_added = cur.fetchone()[0]
    except Exception:
        keyword_added = 0

    # cascade 통계 (mapping_source 분포)
    cascade: list[AiCascadeStat] = []
    try:
        cur.execute(f"""
            SELECT
                COALESCE(mapping_source, 'unknown') AS source,
                COUNT(*) AS cnt
            FROM financeone.transactions
            WHERE mapping_source IS NOT NULL
              AND created_at >= CURRENT_DATE - interval '7 days'
              {"AND entity_id = %s" if entity_id else ""}
            GROUP BY mapping_source
        """, params)
        rows = cur.fetchall()
        total = sum(r[1] for r in rows) or 1
        for source, cnt in rows:
            # source 'rule_exact', 'similar_trgm', 'entity_keyword', 'global_keyword', 'ai'
            step_map = {
                'rule_exact': 'exact',
                'rule': 'exact',
                'similar_trgm': 'similar_trgm',
                'entity_keyword': 'entity_keyword',
                'global_keyword': 'global_keyword',
                'ai': 'ai',
            }
            step = step_map.get(source, 'ai')
            cascade.append(AiCascadeStat(step=step, pct=round(cnt / total * 100, 1)))
    except Exception:
        cascade = []

    cur.close()

    return AiActivity(
        auto_mapped_today=auto_mapped or 0,
        review_needed=review_needed or 0,
        unusual=unusual or 0,
        keyword_added_this_week=keyword_added,
        learning_impact=keyword_added * 3,  # rough heuristic: 1 keyword → 3 future auto-maps
        cascade=cascade,
    )


# ─────────────────────────────────────────────────────────────
# Chart — cash + accrual 6 monthly
# ─────────────────────────────────────────────────────────────

def fetch_chart(conn: PgConnection, entity_id: Optional[int]) -> ChartData:
    cur = conn.cursor()
    params: list = [entity_id] if entity_id else []

    cur.execute(f"""
        SELECT
            to_char(date_trunc('month', date), 'YYYY-MM') AS ym,
            COALESCE(SUM(CASE WHEN type='in' THEN amount ELSE 0 END), 0) AS cash_in,
            COALESCE(SUM(CASE WHEN type='out' THEN amount ELSE 0 END), 0) AS cash_out
        FROM financeone.transactions
        WHERE date >= date_trunc('month', CURRENT_DATE) - interval '5 months'
          AND (is_cancel IS NOT TRUE)
          {"AND entity_id = %s" if entity_id else ""}
        GROUP BY date_trunc('month', date)
        ORDER BY ym
    """, params)
    rows = cur.fetchall()

    # accrual revenue per month
    cur.execute(f"""
        SELECT
            to_char(date_trunc('month', je.posted_at), 'YYYY-MM') AS ym,
            COALESCE(SUM(CASE WHEN sa.category = '수익' THEN je.credit - je.debit ELSE 0 END), 0) AS rev
        FROM financeone.journal_entries je
        JOIN financeone.standard_accounts sa ON sa.id = je.standard_account_id
        WHERE je.posted_at >= date_trunc('month', CURRENT_DATE) - interval '5 months'
          {"AND je.entity_id = %s" if entity_id else ""}
        GROUP BY date_trunc('month', je.posted_at)
        ORDER BY ym
    """, params)
    accrual_by_month: dict[str, Decimal] = {ym: Decimal(rev) for ym, rev in cur.fetchall()}

    months = [
        ChartMonthPoint(
            month=ym,
            cash_in=Decimal(cash_in),
            cash_out=Decimal(cash_out),
            accrual_revenue=accrual_by_month.get(ym),
            is_forecast=False,
        )
        for ym, cash_in, cash_out in rows
    ]

    cur.close()

    return ChartData(months=months)


# ─────────────────────────────────────────────────────────────
# Batch endpoint — single function
# ─────────────────────────────────────────────────────────────

def _safe(label: str, fn, fallback):
    """Per-section graceful degrade: log + return fallback on error.
    Resets transaction state so subsequent queries in same connection can proceed.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        return fn()
    except Exception as e:
        logger.warning("dashboard %s failed (graceful fallback): %s", label, e)
        return fallback


def fetch_dashboard_full(
    conn: PgConnection,
    entity_id: Optional[int] = None,
    currency: str = "USD",
    gaap: str = "K",
) -> DashboardFullResponse:
    """6 widget data 한 번에 fetch (plan-eng-review A1).

    Each section runs in its own savepoint so a failed sub-query does not
    abort the whole transaction. Missing schema (migration not run) =
    safe defaults instead of 500.
    """
    scope: Union[str, int] = "group" if entity_id is None else entity_id

    def with_savepoint(fn):
        # psycopg2 autocommit=False: use SAVEPOINT so one bad query doesn't poison the whole txn
        cur = conn.cursor()
        cur.execute("SAVEPOINT dash_section")
        try:
            result = fn()
            cur.execute("RELEASE SAVEPOINT dash_section")
            return result
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT dash_section")
            raise
        finally:
            cur.close()

    fallback_bento = BentoSummary(
        group_total_usd=Decimal(0), eliminations_usd=Decimal(0),
        eliminations_count=0, entities=[],
    )
    fallback_cash = CashKPI(
        total_balance=Decimal(0), monthly_income=Decimal(0), monthly_expense=Decimal(0),
    )
    fallback_accrual = AccrualKPI(
        accuracy_status='cold_start', accuracy_pass_count=0,
        accuracy_total_count=ACCRUAL_TOTAL_CHECKS, accuracy_threshold=ACCRUAL_GATING_THRESHOLD,
        revenue_cash=Decimal(0), expense_cash=Decimal(0),
    )

    return DashboardFullResponse(
        scope=scope,
        currency=currency,  # type: ignore
        gaap=gaap,  # type: ignore
        as_of=datetime.now(timezone.utc),
        bento=_safe("bento", lambda: with_savepoint(lambda: fetch_bento_summary(conn, target_currency=currency)), fallback_bento),
        cash_kpi=_safe("cash_kpi", lambda: with_savepoint(lambda: fetch_cash_kpi(conn, entity_id)), fallback_cash),
        accrual_kpi=_safe("accrual_kpi", lambda: with_savepoint(lambda: fetch_accrual_kpi(conn, entity_id)), fallback_accrual),
        decision_queue=_safe("decision_queue", lambda: with_savepoint(lambda: fetch_decision_queue(conn, entity_id)), DecisionQueueSection(items=[], total=0)),
        ai_activity=_safe("ai_activity", lambda: with_savepoint(lambda: fetch_ai_activity(conn, entity_id)), AiActivity(auto_mapped_today=0, review_needed=0, unusual=0, keyword_added_this_week=0, learning_impact=0, cascade=[])),
        chart=_safe("chart", lambda: with_savepoint(lambda: fetch_chart(conn, entity_id)), ChartData(months=[])),
    )

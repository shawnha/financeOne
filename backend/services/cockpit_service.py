# 사장님 코쿼핏 — 현금 기본 그룹/법인별 집계 + 통화환산(월말환율) + 3개월 순현금 추세
"""경영 코쿼핏 (사장님 뷰) 서비스.

현금 기본(cash-basis) + 영업 현금흐름(operating-only): transactions 통장 in/out + balance_snapshots 잔고.
- 수입/지출은 **영업만** — 차입금·대여금·가지급금·증자 등 비영업(_NON_OPERATING_CODES)은 제외(group.nonop_*로 분리 표기).
- 법인별: 자국통화(native) 값. 그룹: display_currency 로 환산 합산.
- 환율: 선택월 월말 기준 (_fx_rate, 데이터 없으면 raise — 팬텀 1:1 금지).
- 추세: 선택월 포함 최근 3개월 그룹 순현금 (각 월 월말환율로 환산).
발생(accrual) 매출/비용은 v1 미포함 — journal_entries 차오른 뒤 덧댐 (dashboard.fetch_accrual_kpi 재사용 예정).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from psycopg2.extensions import connection as PgConnection

from backend.services.dashboard_service import _fx_rate, _resolve_month

logger = logging.getLogger(__name__)


# 영업 현금흐름 산정 시 제외하는 비영업(재무·투자·자본) 표준계정 코드.
# 근거: standard_accounts.category(부채/자산/자본) + 사용자 결정 2026-06-02(옵션1 "영업 현금흐름만").
# 차입·대여·가지급·증자는 통장엔 들어오고 나가지만 매출·비용이 아니므로 영업 수입/지출에서 뺀다.
# ⚠️ revisit 예정: 미매핑 거래·회사설정계정과목(18400)·선급금(13100)·외상매출입금(운전자본 시차)·
#    법인간 운영거래(매출/매입으로 분개돼 v1 미상계)·방향 오분류(잡이익 out 등)는 아직 영업으로 포함됨.
_NON_OPERATING_CODES = (
    # 재무활동 — 차입금 (조달/상환)
    "26000", "29000", "29300", "30300",
    # 투자/대여활동 — 대여금·가지급금·임직원채권·임차보증금
    "10900", "11400", "13400", "13700", "96200",
    # 자본활동 — 자본금/증자
    "33100",
)


def _month_end_asof(month_start: date) -> date:
    """그 달의 마지막 날 (환율 as_of 용). month_start=1일 → 다음달 1일 - 1일."""
    if month_start.month == 12:
        nxt = date(month_start.year + 1, 1, 1)
    else:
        nxt = date(month_start.year, month_start.month + 1, 1)
    return nxt - timedelta(days=1)


def _months_back(month_start: date, n: int) -> date:
    """month_start 에서 n개월 전 1일."""
    y, m = month_start.year, month_start.month
    for _ in range(n):
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
    return date(y, m, 1)


def _rate_to(conn: PgConnection, src_currency: str, display: str, as_of: date) -> Decimal:
    """src → display 환율. 같으면 1. 데이터 없으면 _fx_rate 가 raise (1:1 위조 안 함)."""
    if src_currency == display:
        return Decimal("1")
    return _fx_rate(conn, src_currency, display, as_of)


def fetch_cockpit_ceo(
    conn: PgConnection,
    currency: str = "USD",
    year_month: Optional[str] = None,
) -> dict:
    """사장님 코쿼핏 데이터 (현금 기준).

    Returns dict: year_month, display_currency, fx(rate badge),
      entities[](native), group(display 환산), trend[](display 순현금 3개월).
    """
    month_start, month_end = _resolve_month(year_month)
    as_of = _month_end_asof(month_start)
    ym = f"{month_start.year:04d}-{month_start.month:02d}"

    cur = conn.cursor()

    # ── 활성 법인 (하드코딩 금지) ──
    cur.execute(
        "SELECT id, code, name, currency FROM financeone.entities "
        "WHERE is_active IS NOT FALSE ORDER BY id"
    )
    ents = cur.fetchall()  # [(id, code, name, currency), ...]

    # ── 법인별 월 영업 수입/지출 + 비영업(재무·투자) 분리 (현금, transactions.date 기준) ──
    # 비영업 = 표준계정이 _NON_OPERATING_CODES 인 거래. 미매핑(sa.code NULL)은 영업으로 집계(검토 대상).
    cur.execute(
        """
        SELECT entity_id,
               COALESCE(SUM(CASE WHEN type='in'  AND NOT is_nonop THEN amount ELSE 0 END), 0) AS op_in,
               COALESCE(SUM(CASE WHEN type='out' AND NOT is_nonop THEN amount ELSE 0 END), 0) AS op_out,
               COALESCE(SUM(CASE WHEN type='in'  AND is_nonop THEN amount ELSE 0 END), 0) AS nop_in,
               COALESCE(SUM(CASE WHEN type='out' AND is_nonop THEN amount ELSE 0 END), 0) AS nop_out
        FROM (
            SELECT t.entity_id, t.type, t.amount,
                   COALESCE(sa.code = ANY(%s), FALSE) AS is_nonop
            FROM financeone.transactions t
            LEFT JOIN financeone.standard_accounts sa ON sa.id = t.standard_account_id
            WHERE t.date >= %s AND t.date < %s AND (t.is_cancel IS NOT TRUE)
        ) x
        GROUP BY entity_id
        """,
        [list(_NON_OPERATING_CODES), month_start, month_end],
    )
    # entity_id -> (op_in, op_out, nonop_in, nonop_out)
    flow = {
        r[0]: (Decimal(r[1]), Decimal(r[2]), Decimal(r[3]), Decimal(r[4]))
        for r in cur.fetchall()
    }

    # ── 법인별 통장 잔고 (계좌별 최신 스냅샷 합) ──
    cur.execute(
        """
        SELECT entity_id, COALESCE(SUM(balance), 0) FROM (
            SELECT DISTINCT ON (entity_id, account_name) entity_id, account_name, balance
            FROM financeone.balance_snapshots
            ORDER BY entity_id, account_name, date DESC
        ) latest
        GROUP BY entity_id
        """
    )
    bal = {r[0]: Decimal(r[1]) for r in cur.fetchall()}

    # ── 통화별 → display 환율 (월말 기준, 한 번씩만) ──
    rate_cache: dict[str, Decimal] = {}
    for (_eid, _code, _name, ecur) in ents:
        if ecur not in rate_cache:
            rate_cache[ecur] = _rate_to(conn, ecur, currency, as_of)

    entity_rows = []
    g_inc = g_exp = g_bal = Decimal("0")
    g_nop_in = g_nop_out = Decimal("0")  # 그룹 비영업(재무·투자) 제외액 (display 환산, 투명표기용)
    zero4 = (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    for (eid, code, name, ecur) in ents:
        inc, exp, nop_in, nop_out = flow.get(eid, zero4)  # inc/exp = 영업만
        balance = bal.get(eid, Decimal("0"))
        net = inc - exp
        r = rate_cache[ecur]
        g_inc += inc * r
        g_exp += exp * r
        g_bal += balance * r
        g_nop_in += nop_in * r
        g_nop_out += nop_out * r
        entity_rows.append({
            "id": eid, "code": code, "name": name, "currency": ecur,
            "income": inc, "expense": exp, "net": net, "balance": balance,
        })

    g_net = g_inc - g_exp
    runway = (g_bal / -g_net) if g_net < 0 and g_bal > 0 else None

    # ── 추세: 선택월 포함 최근 3개월 그룹 순현금 (display 환산) ──
    trend_start = _months_back(month_start, 2)
    # 추세도 영업 순현금만 (비영업 제외) — 카드/표와 기준 일치.
    cur.execute(
        """
        SELECT to_char(t.date, 'YYYY-MM') AS ym, e.currency,
               COALESCE(SUM(CASE WHEN t.type='in' THEN t.amount
                                 WHEN t.type='out' THEN -t.amount ELSE 0 END), 0) AS net
        FROM financeone.transactions t
        JOIN financeone.entities e ON e.id = t.entity_id
        LEFT JOIN financeone.standard_accounts sa ON sa.id = t.standard_account_id
        WHERE t.date >= %s AND t.date < %s AND (t.is_cancel IS NOT TRUE)
          AND e.is_active IS NOT FALSE
          AND COALESCE(sa.code = ANY(%s), FALSE) IS FALSE
        GROUP BY ym, e.currency
        """,
        [trend_start, month_end, list(_NON_OPERATING_CODES)],
    )
    # ym -> {currency: net}
    by_ym: dict[str, dict[str, Decimal]] = {}
    for r in cur.fetchall():
        by_ym.setdefault(r[0], {})[r[1]] = Decimal(r[2])

    trend = []
    cursor_month = trend_start
    while cursor_month < month_end:
        tym = f"{cursor_month.year:04d}-{cursor_month.month:02d}"
        m_asof = _month_end_asof(cursor_month)
        net_disp = Decimal("0")
        for ecur, net_native in by_ym.get(tym, {}).items():
            net_disp += net_native * _rate_to(conn, ecur, currency, m_asof)
        trend.append({"month": tym, "net": net_disp})
        cursor_month = _next_month(cursor_month)

    # ── FX 뱃지 (1 USD = ? KRW) ──
    usd_krw = _fx_rate(conn, "USD", "KRW", as_of)

    cur.close()
    return {
        "year_month": ym,
        "display_currency": currency,
        "fx": {"usd_krw": usd_krw, "as_of": as_of.isoformat()},
        "entities": entity_rows,
        "group": {
            "income": g_inc, "expense": g_exp, "net": g_net,
            "balance": g_bal, "runway_months": runway,
            # 영업 수입/지출에서 제외한 비영업(재무·투자·자본) 현금흐름 — 투명표기용
            "nonop_income": g_nop_in, "nonop_expense": g_nop_out,
        },
        "trend": trend,
    }


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)

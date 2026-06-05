# 코리아·리테일 P&L 매출을 invoices(발생)에서 읽는 per-entity 분기 단위 테스트
"""_revenue_cogs_summary per-entity 매출 소스 라우팅 (매출배선 Tier 1).

- 코리아(2)·리테일(3) → invoices(direction='sales', status<>cancelled)
- 홀세일(13)         → wholesale_sales (불변, CRITICAL 회귀)
- HOI(1) 등          → transactions(subcat='매출') (불변, CRITICAL 회귀)
- 코리아 COGS 는 transactions(현금) 유지 → cogs_basis='cash'

DB 없이 mock cursor: execute() SQL 의 테이블로 canned fetchone 선택.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.services import pnl_service as pnl


class FakeCursor:
    """실행된 SQL 의 FROM 테이블로 미리 정한 fetchone() 결과를 돌려주는 mock."""

    def __init__(self, *, invoices=None, wholesale=None, tx_rev=None, tx_cogs=None):
        self._canned = {
            "invoices": invoices,
            "wholesale": wholesale,
            "tx_rev": tx_rev,
            "tx_cogs": tx_cogs,
        }
        self.executed_sql: list[str] = []
        self._next = None

    def execute(self, sql, params=None):
        self.executed_sql.append(sql)
        if "FROM wholesale_sales" in sql:
            self._next = self._canned["wholesale"]
        elif "FROM invoices" in sql:
            self._next = self._canned["invoices"]
        elif "'매출원가'" in sql:
            self._next = self._canned["tx_cogs"]
        elif "'매출'" in sql:
            self._next = self._canned["tx_rev"]
        else:
            self._next = None

    def fetchone(self):
        return self._next

    def close(self):
        pass


START, END = date(2026, 5, 1), date(2026, 6, 1)


def _all_sql(cur: FakeCursor) -> str:
    return " ".join(cur.executed_sql)


def test_korea_revenue_from_invoices():
    cur = FakeCursor(
        invoices=(Decimal("100"), Decimal("90"), 5),
        tx_rev=(Decimal("50"), Decimal("45"), 3),  # 현행 경로 — 안 읽혀야 함
        tx_cogs=(Decimal("30"), Decimal("27")),
    )
    r = pnl._revenue_cogs_summary(cur, 2, START, END)
    assert r["revenue"] == Decimal("100")
    assert r["revenue_excl_vat"] == Decimal("90")
    assert r["sales_count"] == 5
    assert r["revenue_source"] == "invoices"
    assert "FROM invoices" in _all_sql(cur)
    assert "FROM wholesale_sales" not in _all_sql(cur)


def test_korea_cogs_from_transactions_cash_basis():
    cur = FakeCursor(
        invoices=(Decimal("100"), Decimal("90"), 5),
        tx_cogs=(Decimal("30"), Decimal("27")),
    )
    r = pnl._revenue_cogs_summary(cur, 2, START, END)
    assert r["cogs"] == Decimal("30")
    assert r["cogs_basis"] == "cash"
    assert "'매출원가'" in _all_sql(cur)


def test_korea_invoices_query_filters_sales_and_cancelled():
    cur = FakeCursor(
        invoices=(Decimal("0"), Decimal("0"), 0),
        tx_cogs=(Decimal("0"), Decimal("0")),
    )
    pnl._revenue_cogs_summary(cur, 2, START, END)
    inv_sql = next(s for s in cur.executed_sql if "FROM invoices" in s)
    assert "direction = 'sales'" in inv_sql
    assert "cancelled" in inv_sql
    assert "issue_date" in inv_sql


def test_korea_empty_month_zero():
    cur = FakeCursor(
        invoices=(Decimal("0"), Decimal("0"), 0),
        tx_cogs=(Decimal("0"), Decimal("0")),
    )
    r = pnl._revenue_cogs_summary(cur, 2, START, END)
    assert r["revenue"] == Decimal("0")
    assert r["sales_count"] == 0


def test_retail_revenue_from_invoices():
    cur = FakeCursor(
        invoices=(Decimal("0"), Decimal("0"), 0),
        tx_cogs=(Decimal("0"), Decimal("0")),
    )
    r = pnl._revenue_cogs_summary(cur, 3, START, END)
    assert r["revenue_source"] == "invoices"
    assert "FROM invoices" in _all_sql(cur)


def test_wholesale_unchanged_reads_wholesale_sales():
    """CRITICAL 회귀: 홀세일(13) 은 여전히 wholesale_sales, invoices 안 읽음."""
    cur = FakeCursor(
        wholesale=(Decimal("1510"), Decimal("1373"), Decimal("1490"), Decimal("1354"), 99),
        invoices=(Decimal("999"), Decimal("999"), 1),  # 잘못 읽히면 값으로 들킴
    )
    r = pnl._revenue_cogs_summary(cur, 13, START, END)
    assert r["revenue"] == Decimal("1510")
    assert r["revenue_source"] == "wholesale_sales"
    assert "FROM wholesale_sales" in _all_sql(cur)
    assert "FROM invoices" not in _all_sql(cur)


def test_hoi_unchanged_reads_transactions():
    """CRITICAL 회귀: HOI(1) 은 여전히 transactions(subcat 매출), invoices 안 읽음."""
    cur = FakeCursor(
        tx_rev=(Decimal("0"), Decimal("0"), 0),
        tx_cogs=(Decimal("0"), Decimal("0")),
        invoices=(Decimal("999"), Decimal("999"), 1),
    )
    r = pnl._revenue_cogs_summary(cur, 1, START, END)
    assert r["revenue_source"] == "transactions"
    assert "FROM invoices" not in _all_sql(cur)
    assert "FROM wholesale_sales" not in _all_sql(cur)

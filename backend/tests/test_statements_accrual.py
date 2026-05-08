"""발생주의 재무제표 통합 테스트 — Phase A+B invariant.

설계 doc: docs/statements-accrual-plan.md §8.1

real DB 연결 — DATABASE_URL 환경변수 필요 (CI 에서는 SKIP).
"""

import os
import pytest

from datetime import date
from decimal import Decimal

# .env 로드 후 DATABASE_URL 평가
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — accrual statements require real DB"
)


@pytest.fixture
def db_conn():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv()
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    conn.commit()
    yield conn
    conn.close()


# ── Invariant 1: cash 모드 회귀 — 한아원코리아 (entity 2) ──
def test_cash_mode_unchanged(db_conn):
    """cash 모드 BS 자산총계가 변하지 않음."""
    from backend.services.statements import generate_all_statements
    result = generate_all_statements(
        conn=db_conn, entity_id=2, fiscal_year=2026,
        start_month=1, end_month=3, basis="cash",
    )
    db_conn.commit()
    bs = result["validation"]["balance_sheet"]
    assert bs["is_balanced"], f"cash mode BS should balance: {bs['difference']}"
    # 한아원코리아 1-3월 cash 자산총계 ≈ ₩452.8M (smoke test 기준)
    # 정확한 회귀 — golden value 는 변경 시 명시적 update
    assert 4.5e8 < bs["total_assets"] < 4.6e8


# ── Invariant 2: accrual net_income 일관성 ──
def test_accrual_net_income_consistency(db_conn):
    """IS_accrual.net_income == BS_accrual 의 net_income (override 일관)."""
    from backend.services.statements import generate_all_statements
    result = generate_all_statements(
        conn=db_conn, entity_id=13, fiscal_year=2026,
        start_month=1, end_month=3, basis="accrual", vat_excluded=True,
    )
    db_conn.commit()
    inc = result["validation"]["income_statement"]
    bs = result["validation"]["balance_sheet"]
    diff = abs(inc["net_income"] - bs["net_income"])
    assert diff < 1, f"IS net_income {inc['net_income']} != BS net_income {bs['net_income']}, diff={diff}"


# ── Invariant 3: 발생주의 매출 = wholesale_sales SUM ──
def test_accrual_revenue_source(db_conn):
    """발생주의 IS 의 매출 = wholesale_sales.supply_amount (VAT 제외 모드)."""
    from backend.services.statements import generate_all_statements
    cur = db_conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(COALESCE(supply_amount, total_amount/1.1)), 0)
        FROM wholesale_sales
        WHERE entity_id = 13 AND sales_date >= '2026-01-01' AND sales_date <= '2026-03-31'
        """
    )
    expected = float(cur.fetchone()[0])

    result = generate_all_statements(
        conn=db_conn, entity_id=13, fiscal_year=2026,
        start_month=1, end_month=3, basis="accrual", vat_excluded=True,
    )
    db_conn.commit()
    inc = result["validation"]["income_statement"]
    diff = abs(inc["total_revenue"] - expected)
    assert diff < 1, f"발생주의 매출 {inc['total_revenue']} != wholesale_sales {expected}"


# ── Invariant 4: BS 항등식 (자산 = 부채 + 자본, plug 후) ──
@pytest.mark.parametrize("entity_id", [13, 2, 3])
def test_accrual_bs_balanced(db_conn, entity_id):
    """발생주의 BS 항등식 — plug 자동 추가로 entity 별 모두 균형."""
    from backend.services.statements import generate_all_statements
    result = generate_all_statements(
        conn=db_conn, entity_id=entity_id, fiscal_year=2026,
        start_month=1, end_month=3, basis="accrual", vat_excluded=True,
    )
    db_conn.commit()
    bs = result["validation"]["balance_sheet"]
    assert bs["is_balanced"], (
        f"entity {entity_id} accrual BS not balanced: assets={bs['total_assets']}, "
        f"liab+equity={bs['total_liabilities'] + bs['total_equity']}, diff={bs['difference']}"
    )


# ── Invariant 5: 외상매출금 ≥ 0 ──
def test_receivables_non_negative(db_conn):
    """외상매출금 = max(매출 누계 - 회수 누계, 0). 음수 금지."""
    from backend.services.statements.balance_sheet_accrual import _fetch_extra_balances
    extras = _fetch_extra_balances(
        conn=db_conn, entity_id=13,
        as_of_date=date(2026, 3, 31),
        vat_excluded=True,
        existing_codes=set(),
    )
    receivables = next((e for e in extras if e["code"] == "10800"), None)
    if receivables:
        assert receivables["balance"] >= 0, f"외상매출금 음수 금지: {receivables['balance']}"


# ── Invariant 6: PDF 정확도 — 매출/매입/VAT 99%+ ──
def test_pdf_accuracy_revenue_cogs_vat(db_conn):
    """26년 1-3월 한아원홀세일 — PDF 가결산 자료 대비 99%+ 정확도."""
    from backend.services.statements import generate_all_statements
    result = generate_all_statements(
        conn=db_conn, entity_id=13, fiscal_year=2026,
        start_month=1, end_month=3, basis="accrual", vat_excluded=True,
    )
    db_conn.commit()
    inc = result["validation"]["income_statement"]

    pdf = {
        "revenue": 3851196762,
        "cogs": 4040378058,
        "vat_collected": 385119676,
    }
    rev_pct = abs(inc["total_revenue"] / pdf["revenue"] * 100)
    cogs_pct = abs(inc["total_cogs"] / pdf["cogs"] * 100)
    vat_pct = abs(inc["vat_collected"] / pdf["vat_collected"] * 100)

    assert 99 <= rev_pct <= 101, f"매출 정확도 {rev_pct:.2f}% — 99-101% 벗어남"
    assert 99 <= cogs_pct <= 101, f"매출원가 정확도 {cogs_pct:.2f}% — 99-101% 벗어남"
    assert 99 <= vat_pct <= 101, f"VAT 정확도 {vat_pct:.2f}% — 99-101% 벗어남"

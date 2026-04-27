"""invoice_service 단위 테스트 — DB 실제 연결 (pytest fixture 로 transaction rollback).

P2 발생주의 레이어 검증:
- create_invoice + total 자동 계산
- match_invoice_payment + status 자동 갱신 (open → partial → paid)
- direction 검증 (sales↔in, purchase↔out)
- entity 일치 검증
- cancel_invoice 시 매칭 자동 해제
- auto_match_candidates 후보 점수
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv()

from backend.services import invoice_service as svc


@pytest.fixture
def conn():
    """각 테스트마다 새 connection — 끝나면 ROLLBACK 으로 격리."""
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = c.cursor()
    cur.execute("SET search_path TO financeone, public")
    cur.close()
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def fixture_entity(conn):
    """테스트용 entity. 기존 한아원코리아(id=2) 사용."""
    return 2


@pytest.fixture
def fixture_tx(conn, fixture_entity):
    """테스트용 transaction (in 100k, 한아원코리아 임의 거래) — 매칭에 사용."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO transactions (entity_id, date, amount, currency, type,
            description, counterparty, source_type, is_confirmed, is_duplicate)
        VALUES (%s, %s, %s, 'KRW', 'in', 'TEST_INVOICE_FIXTURE', 'TestCorp', 'manual', false, false)
        RETURNING id
        """,
        [fixture_entity, date(2026, 4, 15), 100000.0],
    )
    tx_id = cur.fetchone()[0]
    cur.close()
    return tx_id


# ── create_invoice ────────────────────────────────────────────────────


class TestCreateInvoice:
    def test_total_auto_calculated(self, conn, fixture_entity):
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="TestCorp", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"), vat=Decimal("10000"),
        )
        inv = svc.get_invoice(conn, inv_id)
        assert inv is not None
        assert Decimal(str(inv["total"])) == Decimal("110000.00")
        assert inv["status"] == "open"

    def test_total_validation_fails(self, conn, fixture_entity):
        with pytest.raises(ValueError, match="total"):
            svc.create_invoice(
                conn, entity_id=fixture_entity, direction="sales",
                counterparty="X", issue_date=date(2026, 4, 1),
                amount=Decimal("100"), vat=Decimal("10"),
                total=Decimal("999"),  # 일관 안 됨
            )

    def test_invalid_direction(self, conn, fixture_entity):
        with pytest.raises(ValueError, match="direction"):
            svc.create_invoice(
                conn, entity_id=fixture_entity, direction="invalid",
                counterparty="X", issue_date=date(2026, 4, 1),
                amount=Decimal("100"),
            )


# ── match_invoice_payment ─────────────────────────────────────────────


class TestMatchInvoicePayment:
    def test_full_payment_status_paid(self, conn, fixture_entity, fixture_tx):
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="TestCorp", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"),
        )
        svc.match_invoice_payment(conn, invoice_id=inv_id, transaction_id=fixture_tx)
        inv = svc.get_invoice(conn, inv_id)
        assert inv["status"] == "paid"
        assert Decimal(str(inv["paid_amount"])) == Decimal("100000.00")
        assert Decimal(str(inv["outstanding"])) == Decimal("0.00")

    def test_partial_payment_status_partial(self, conn, fixture_entity, fixture_tx):
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="TestCorp", issue_date=date(2026, 4, 1),
            amount=Decimal("200000"),  # tx 는 100k → 부분결제
        )
        svc.match_invoice_payment(conn, invoice_id=inv_id, transaction_id=fixture_tx)
        inv = svc.get_invoice(conn, inv_id)
        assert inv["status"] == "partial"
        assert Decimal(str(inv["outstanding"])) == Decimal("100000.00")

    def test_direction_mismatch_raises(self, conn, fixture_entity, fixture_tx):
        # tx 는 type='in' (sales 와 매칭됨). purchase invoice 와는 매칭 거부.
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="purchase",
            counterparty="TestCorp", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"),
        )
        with pytest.raises(ValueError, match="direction mismatch"):
            svc.match_invoice_payment(
                conn, invoice_id=inv_id, transaction_id=fixture_tx,
            )

    def test_cancelled_invoice_rejected(self, conn, fixture_entity, fixture_tx):
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="X", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"),
        )
        svc.cancel_invoice(conn, inv_id, note="test")
        with pytest.raises(ValueError, match="cancelled"):
            svc.match_invoice_payment(
                conn, invoice_id=inv_id, transaction_id=fixture_tx,
            )

    def test_overpayment_rejected(self, conn, fixture_entity, fixture_tx):
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="X", issue_date=date(2026, 4, 1),
            amount=Decimal("50000"),  # tx 는 100k → 초과
        )
        with pytest.raises(ValueError, match="exceeds outstanding"):
            svc.match_invoice_payment(
                conn, invoice_id=inv_id, transaction_id=fixture_tx,
                amount=Decimal("100000"),
            )


# ── cancel_invoice ────────────────────────────────────────────────────


class TestCancelInvoice:
    def test_cancel_releases_payments(self, conn, fixture_entity, fixture_tx):
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="X", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"),
        )
        svc.match_invoice_payment(conn, invoice_id=inv_id, transaction_id=fixture_tx)
        svc.cancel_invoice(conn, inv_id, note="test cancel")
        inv = svc.get_invoice(conn, inv_id)
        assert inv["status"] == "cancelled"
        assert Decimal(str(inv["paid_amount"])) == Decimal("0")  # 매칭 해제됨


# ── auto_match_candidates ─────────────────────────────────────────────


class TestAccrualSummary:
    def test_monthly_split_by_direction(self, conn, fixture_entity):
        svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="A", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"), vat=Decimal("10000"),
        )
        svc.create_invoice(
            conn, entity_id=fixture_entity, direction="purchase",
            counterparty="B", issue_date=date(2026, 4, 5),
            amount=Decimal("60000"), vat=Decimal("6000"),
        )
        result = svc.accrual_monthly_summary(conn, entity_id=fixture_entity, months=24)
        # 우리 fixture 의 4월 row 검증 (다른 데이터도 섞일 수 있어 부분 검사)
        apr = next((m for m in result["months"] if m["month"] == "2026-04"), None)
        assert apr is not None
        assert apr["sales_amount"] >= 100000.0
        assert apr["sales_vat"] >= 10000.0
        assert apr["purchase_amount"] >= 60000.0

    def test_cancelled_excluded(self, conn, fixture_entity):
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="X", issue_date=date(2025, 12, 1),
            amount=Decimal("999999"),  # 식별용 큰 금액
        )
        svc.cancel_invoice(conn, inv_id, note="테스트")
        result = svc.accrual_monthly_summary(conn, entity_id=fixture_entity, months=24)
        dec = next((m for m in result["months"] if m["month"] == "2025-12"), None)
        if dec:
            # 999999 가 sales 합계에 포함되지 않아야
            assert dec["sales_amount"] < 999999.0


class TestCounterpartyBalances:
    def test_outstanding_only(self, conn, fixture_entity):
        svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="OutTestCorp_A", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"),
        )
        balances = svc.counterparty_balances(
            conn, entity_id=fixture_entity, direction="sales", only_outstanding=True,
        )
        ours = [b for b in balances if b["counterparty"] == "OutTestCorp_A"]
        assert len(ours) == 1
        assert ours[0]["outstanding"] == 100000.0

    def test_paid_excluded_when_outstanding_only(self, conn, fixture_entity, fixture_tx):
        # 100k tx 있음 (fixture). invoice 100k 매칭 → paid → outstanding=False 시 빠짐.
        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="PaidTestCorp_B", issue_date=date(2026, 4, 1),
            amount=Decimal("100000"),
        )
        svc.match_invoice_payment(conn, invoice_id=inv_id, transaction_id=fixture_tx)
        balances = svc.counterparty_balances(
            conn, entity_id=fixture_entity, direction="sales", only_outstanding=True,
        )
        ours = [b for b in balances if b["counterparty"] == "PaidTestCorp_B"]
        assert len(ours) == 0  # paid → outstanding 0 → 제외


class TestAutoMatchCandidates:
    def test_amount_match_high_score(self, conn, fixture_entity):
        # tx + invoice 둘 다 동일 counterparty + 금액 + 일자
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO transactions (entity_id, date, amount, currency, type,
                description, counterparty, source_type, is_confirmed, is_duplicate)
               VALUES (%s, %s, 50000, 'KRW', 'in', 'Auto match test', 'AutoCorp', 'manual', false, false)
               RETURNING id""",
            [fixture_entity, date(2026, 4, 20)],
        )
        tx_id = cur.fetchone()[0]
        cur.close()

        inv_id = svc.create_invoice(
            conn, entity_id=fixture_entity, direction="sales",
            counterparty="AutoCorp", issue_date=date(2026, 4, 18),
            due_date=date(2026, 4, 22), amount=Decimal("50000"),
        )

        cands = svc.auto_match_candidates(conn, entity_id=fixture_entity, days_window=7)
        # 우리 fixture 페어가 들어있어야 (다른 entity 데이터도 섞일 수 있어 정확 매칭 검사)
        ours = [c for c in cands if c["invoice_id"] == inv_id and c["transaction_id"] == tx_id]
        assert len(ours) == 1
        c = ours[0]
        assert "amount=outstanding" in c["reason"]
        assert c["score"] >= 60
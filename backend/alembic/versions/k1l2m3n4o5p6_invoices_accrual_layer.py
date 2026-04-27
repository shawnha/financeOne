"""invoices + invoice_payments — 발생주의 레이어 (P2)

세금계산서/청구서 ↔ 입출금 매칭. 발생주의 인식(invoices.issue_date) 과
현금주의 결제(transactions.date) 분리. Phase 3 연결재무제표 + K-GAAP 정확도
기초.

invoices (발생주의):
- direction: sales (매출) / purchase (매입)
- issue_date: 발생 시점 (세금계산서 발행일)
- due_date: 결제 예정일
- amount + vat = total
- status: open / partial / paid / cancelled

invoice_payments (매칭, N:N):
- invoice_id ↔ transaction_id (분할결제 + 합산결제 모두 지원)
- amount: 매칭된 금액 (부분결제 가능)
- invoice.total - SUM(payments.amount) = 미수/미지급 잔액

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-04-27
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'k1l2m3n4o5p6'
down_revision: Union[str, None] = 'j0k1l2m3n4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id                  SERIAL PRIMARY KEY,
            entity_id           INTEGER NOT NULL REFERENCES entities(id),
            direction           TEXT NOT NULL CHECK (direction IN ('sales','purchase')),
            counterparty        TEXT NOT NULL,
            counterparty_biz_no TEXT,
            issue_date          DATE NOT NULL,
            due_date            DATE,
            document_no         TEXT,
            description         TEXT,
            amount              NUMERIC(18,2) NOT NULL,
            vat                 NUMERIC(18,2) NOT NULL DEFAULT 0,
            total               NUMERIC(18,2) NOT NULL,
            currency            TEXT NOT NULL DEFAULT 'KRW',
            internal_account_id INTEGER REFERENCES internal_accounts(id),
            standard_account_id INTEGER REFERENCES standard_accounts(id),
            status              TEXT NOT NULL DEFAULT 'open'
                                CHECK (status IN ('open','partial','paid','cancelled')),
            note                TEXT,
            raw_data            JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_invoices_entity_date ON invoices (entity_id, issue_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices (entity_id, status, due_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_invoices_counterparty ON invoices (entity_id, counterparty)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS invoice_payments (
            id              SERIAL PRIMARY KEY,
            invoice_id      INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            transaction_id  INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            amount          NUMERIC(18,2) NOT NULL,
            matched_by      TEXT NOT NULL DEFAULT 'manual'
                            CHECK (matched_by IN ('manual','auto','rule')),
            note            TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (invoice_id, transaction_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_invoice_payments_invoice ON invoice_payments (invoice_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_invoice_payments_transaction ON invoice_payments (transaction_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoice_payments")
    op.execute("DROP TABLE IF EXISTS invoices")

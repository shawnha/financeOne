"""invoices.journal_entry_id + invoice_payments.journal_entry_id

P3-2: invoice 발행/매칭 시점에 journal_entry 가 자동 생성됨. 추적성을 위해
양방향 FK 설정.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-04-28
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS journal_entry_id INTEGER
        REFERENCES journal_entries(id) ON DELETE SET NULL
    """)
    op.execute("""
        ALTER TABLE invoice_payments
        ADD COLUMN IF NOT EXISTS journal_entry_id INTEGER
        REFERENCES journal_entries(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE invoice_payments DROP COLUMN IF EXISTS journal_entry_id")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS journal_entry_id")

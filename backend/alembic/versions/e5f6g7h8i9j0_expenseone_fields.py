"""Add expense_id, expense_submitted_by, expense_title to transactions (ExpenseOne 연동)

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-04-19

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE transactions ADD COLUMN IF NOT EXISTS expense_id UUID;
    """)
    op.execute("""
        ALTER TABLE transactions ADD COLUMN IF NOT EXISTS expense_submitted_by TEXT;
    """)
    op.execute("""
        ALTER TABLE transactions ADD COLUMN IF NOT EXISTS expense_title TEXT;
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_expense_id
            ON transactions(expense_id) WHERE expense_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_transactions_expense_id")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS expense_title")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS expense_submitted_by")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS expense_id")

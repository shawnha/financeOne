"""transactions.pnl_date — 발생주의 P&L 인식일 (현금주의 date 와 분리).

Use case: 월말 임대료 등 결제일과 비용 인식일이 다른 발생주의 케이스.
- transactions.date: 통장 거래일 (현금주의, cashflow 기준)
- transactions.pnl_date: P&L 비용/수익 인식일 (발생주의)
- 둘이 다르면: cashflow 는 date 기준, P&L 은 pnl_date 기준 (NULL 시 date 사용)

예: 4/2 결제된 3월분 임대료 → date='2026-04-02', pnl_date='2026-03-31'
- cashflow 일별 차트: 4/2 출금
- P&L: 3월 비용으로 인식

Revision ID: c9d0e1f2g3h4
Revises: a8b9c0d1e2f3
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c9d0e1f2g3h4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS pnl_date DATE
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_transactions_pnl_date ON transactions(pnl_date) WHERE pnl_date IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_transactions_pnl_date")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS pnl_date")

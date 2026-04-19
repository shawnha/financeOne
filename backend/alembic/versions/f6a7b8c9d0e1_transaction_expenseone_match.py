"""transaction_expenseone_match — ExpenseOne ↔ 거래 매칭 join 테이블

Slack 매칭(transaction_slack_match)과 동일 패턴.
ExpenseOne 거래는 더 이상 transactions 테이블에 INSERT 안 함 — match 통해 link.

Revision ID: f6a7b8c9d0e1
Revises: e5f6g7h8i9j0
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS transaction_expenseone_match (
          id                SERIAL PRIMARY KEY,
          transaction_id    INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
          expense_id        UUID NOT NULL,
          expense_type      TEXT NOT NULL,        -- 'CORPORATE_CARD' | 'DEPOSIT_REQUEST'
          match_confidence  NUMERIC(3,2),
          match_method      TEXT,                 -- 'auto_card_exact' | 'auto_card_fuzzy' |
                                                  -- 'auto_deposit_exact' | 'auto_deposit_fuzzy' | 'manual'
          is_manual         BOOLEAN NOT NULL DEFAULT FALSE,
          is_confirmed      BOOLEAN NOT NULL DEFAULT FALSE,
          ai_reasoning      TEXT,
          note              TEXT,
          created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_eo_match_tx
            ON transaction_expenseone_match(transaction_id);
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_eo_match_expense
            ON transaction_expenseone_match(expense_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_eo_match_type_conf
            ON transaction_expenseone_match(expense_type, is_confirmed);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_eo_match_type_conf")
    op.execute("DROP INDEX IF EXISTS uq_eo_match_expense")
    op.execute("DROP INDEX IF EXISTS idx_eo_match_tx")
    op.execute("DROP TABLE IF EXISTS transaction_expenseone_match")

"""add journal_entries and journal_entry_lines tables

Revision ID: a1b2c3d4e5f6
Revises: 7d84df7ae218
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '7d84df7ae218'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE journal_entries (
            id             SERIAL PRIMARY KEY,
            entity_id      INTEGER NOT NULL REFERENCES entities(id),
            transaction_id INTEGER REFERENCES transactions(id),
            entry_date     DATE NOT NULL,
            description    TEXT,
            is_adjusting   BOOLEAN NOT NULL DEFAULT FALSE,
            is_closing     BOOLEAN NOT NULL DEFAULT FALSE,
            status         TEXT NOT NULL DEFAULT 'posted',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX idx_je_entity_date ON journal_entries(entity_id, entry_date);
        CREATE INDEX idx_je_transaction ON journal_entries(transaction_id);

        CREATE TABLE journal_entry_lines (
            id                  SERIAL PRIMARY KEY,
            journal_entry_id    INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
            standard_account_id INTEGER NOT NULL REFERENCES standard_accounts(id),
            debit_amount        NUMERIC(18,2) NOT NULL DEFAULT 0,
            credit_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,
            description         TEXT,
            sort_order          INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT chk_debit_or_credit CHECK (
                (debit_amount > 0 AND credit_amount = 0) OR
                (debit_amount = 0 AND credit_amount > 0)
            )
        );

        CREATE INDEX idx_jel_entry ON journal_entry_lines(journal_entry_id);
        CREATE INDEX idx_jel_account ON journal_entry_lines(standard_account_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS journal_entry_lines CASCADE;")
    op.execute("DROP TABLE IF EXISTS journal_entries CASCADE;")

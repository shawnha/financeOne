"""Phase 3: consolidation support tables

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE intercompany_pairs (
            id               SERIAL PRIMARY KEY,
            entity_a_id      INTEGER NOT NULL REFERENCES entities(id),
            entity_b_id      INTEGER NOT NULL REFERENCES entities(id),
            transaction_a_id INTEGER REFERENCES transactions(id),
            transaction_b_id INTEGER REFERENCES transactions(id),
            amount           NUMERIC(18,2) NOT NULL,
            currency         TEXT NOT NULL,
            match_date       DATE NOT NULL,
            match_method     TEXT NOT NULL DEFAULT 'auto',
            is_confirmed     BOOLEAN NOT NULL DEFAULT FALSE,
            description      TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE consolidation_adjustments (
            id               SERIAL PRIMARY KEY,
            statement_id     INTEGER NOT NULL REFERENCES financial_statements(id) ON DELETE CASCADE,
            adjustment_type  TEXT NOT NULL,
            account_code     TEXT NOT NULL,
            description      TEXT,
            original_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
            adjusted_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
            source_entity_id INTEGER REFERENCES entities(id),
            exchange_rate    NUMERIC(12,4),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX idx_exchange_rates_lookup
        ON exchange_rates(from_currency, to_currency, date DESC);

        ALTER TABLE financial_statements
        ADD COLUMN IF NOT EXISTS base_currency TEXT DEFAULT 'KRW';
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE financial_statements DROP COLUMN IF EXISTS base_currency;")
    op.execute("DROP INDEX IF EXISTS idx_exchange_rates_lookup;")
    op.execute("DROP TABLE IF EXISTS consolidation_adjustments CASCADE;")
    op.execute("DROP TABLE IF EXISTS intercompany_pairs CASCADE;")

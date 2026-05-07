"""wholesale_sales / wholesale_purchases — 도매 매출·매입 마스터.

매출관리/매입관리 xlsx import 결과 저장. 제품 단위 row.
P&L 정확도 base (발생주의 매출/매출원가).

매출 row col 41/42 (매입가) 가 매출원가 단가 — COGS 계산.
거래내역 (transactions) 은 회수/지급 시점 (현금흐름) 별개.

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'v2w3x4y5z6a7'
down_revision: Union[str, None] = 'u1v2w3x4y5z6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wholesale_sales (
            id                    SERIAL PRIMARY KEY,
            entity_id             INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

            sales_date            DATE NOT NULL,
            document_date         DATE,
            document_no           TEXT,
            row_number            INTEGER,

            payee_name            TEXT NOT NULL,
            payee_code            TEXT,
            real_payee_name       TEXT,

            product_name          TEXT NOT NULL,
            product_spec          TEXT,
            manufacturer          TEXT,

            quantity              NUMERIC(18, 4) NOT NULL DEFAULT 0,
            unit_price            NUMERIC(18, 4),
            discount_pct          NUMERIC(5, 2),
            supply_amount         NUMERIC(18, 2),
            vat                   NUMERIC(18, 2),
            total_amount          NUMERIC(18, 2) NOT NULL DEFAULT 0,

            real_unit_price       NUMERIC(18, 4),
            real_supply_amount    NUMERIC(18, 2),
            real_total_amount     NUMERIC(18, 2),

            cogs_unit_price       NUMERIC(18, 4),
            cogs_real_unit_price  NUMERIC(18, 4),

            bank_settled          BOOLEAN NOT NULL DEFAULT FALSE,

            sales_rep             TEXT,
            note                  TEXT,

            raw_data              JSONB,
            source_file           TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(entity_id, sales_date, document_no, row_number, product_name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ws_sales_entity_date ON wholesale_sales(entity_id, sales_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ws_sales_payee ON wholesale_sales(entity_id, payee_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ws_sales_product ON wholesale_sales(entity_id, product_name)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS wholesale_purchases (
            id                  SERIAL PRIMARY KEY,
            entity_id           INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

            purchase_date       DATE NOT NULL,
            document_date       DATE,
            document_no         TEXT,
            row_number          INTEGER,

            payee_name          TEXT NOT NULL,
            payee_code          TEXT,

            product_name        TEXT NOT NULL,
            product_spec        TEXT,
            manufacturer        TEXT,

            quantity            NUMERIC(18, 4) NOT NULL DEFAULT 0,
            unit_price          NUMERIC(18, 4),
            supply_amount       NUMERIC(18, 2),
            vat                 NUMERIC(18, 2),
            total_amount        NUMERIC(18, 2) NOT NULL DEFAULT 0,

            real_unit_price     NUMERIC(18, 4),
            real_supply_amount  NUMERIC(18, 2),
            real_total_amount   NUMERIC(18, 2),

            bank_settled        BOOLEAN NOT NULL DEFAULT FALSE,

            note                TEXT,

            raw_data            JSONB,
            source_file         TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(entity_id, purchase_date, document_no, row_number, product_name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ws_pur_entity_date ON wholesale_purchases(entity_id, purchase_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ws_pur_payee ON wholesale_purchases(entity_id, payee_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ws_pur_product ON wholesale_purchases(entity_id, product_name)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wholesale_purchases")
    op.execute("DROP TABLE IF EXISTS wholesale_sales")

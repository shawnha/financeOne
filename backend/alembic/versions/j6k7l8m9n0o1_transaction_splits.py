"""transaction_splits — 한 거래를 여러 표준계정으로 분개 split.

배경:
- 단일 거래(예: ₩100,000 카드 결제)가 실제로 여러 비용 항목 (사무용품 70k + 식비 30k)
  으로 나뉠 수 있음. 기존엔 standard_account_id 1개만 매핑 가능 → 부정확.
- 분개 split: 한 transaction → multi-line journal_entry. 합계 = tx.amount.
- 기존 transactions.standard_account_id 는 호환성 위해 유지 (split 없으면 단일 매핑).

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op


revision: str = "j6k7l8m9n0o1"
down_revision: Union[str, None] = "i5j6k7l8m9n0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS transaction_splits (
            id                   SERIAL PRIMARY KEY,
            transaction_id       INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            entity_id            INTEGER NOT NULL REFERENCES entities(id),
            standard_account_id  INTEGER NOT NULL REFERENCES standard_accounts(id),
            amount               NUMERIC(18,2) NOT NULL CHECK (amount > 0),
            description          TEXT,
            sort_order           INTEGER NOT NULL DEFAULT 0,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_tx_splits_transaction ON transaction_splits(transaction_id);
        CREATE INDEX IF NOT EXISTS idx_tx_splits_entity ON transaction_splits(entity_id);
        CREATE INDEX IF NOT EXISTS idx_tx_splits_sa ON transaction_splits(standard_account_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transaction_splits CASCADE;")

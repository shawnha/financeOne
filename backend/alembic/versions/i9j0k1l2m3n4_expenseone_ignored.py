"""expenseone_ignored — 미매칭 expense 중 FinanceOne에서 '무시'로 표시한 것

ExpenseOne 원본 DB는 건드리지 않고 FinanceOne 쪽에서만 플래그.
무시된 expense는 사이드바 뱃지/기본 목록에서 제외되지만 필터로 복원 조회 가능.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-04-22
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS expenseone_ignored (
          id          SERIAL PRIMARY KEY,
          expense_id  UUID NOT NULL UNIQUE,
          entity_id   INTEGER,
          reason      TEXT,
          ignored_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          ignored_by  TEXT
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_eo_ignored_entity
          ON expenseone_ignored(entity_id, ignored_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_eo_ignored_entity")
    op.execute("DROP TABLE IF EXISTS expenseone_ignored")

"""transaction_expenseone_match: 1:1 → N:M 지원

기존: expense_id UNIQUE → 한 expense 가 정확히 하나의 transaction 과만 매칭
변경: 복합 (expense_id, transaction_id) UNIQUE → 같은 (expense, tx) 페어만
      중복 방지하고, 1 expense ↔ N transactions 또는 1 transaction ↔ N expenses
      자유롭게 매칭 가능 (집합 입금 / 분할 결제 케이스).

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'r8s9t0u1v2w3'
down_revision: Union[str, None] = 'q7r8s9t0u1v2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 단일 UNIQUE 제거 → 복합 UNIQUE 로 교체
    op.execute("DROP INDEX IF EXISTS uq_eo_match_expense")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_eo_match_pair
        ON transaction_expenseone_match (expense_id, transaction_id)
    """)
    # 후속 조회 효율 — expense_id 기준 N개 row 빠른 lookup
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_eo_match_expense_only
        ON transaction_expenseone_match (expense_id)
    """)


def downgrade() -> None:
    # 주의: 다중 매칭 데이터가 있으면 UNIQUE expense_id 복원이 실패함.
    # 운영 데이터에서는 사전에 정리 후 downgrade.
    op.execute("DROP INDEX IF EXISTS idx_eo_match_expense_only")
    op.execute("DROP INDEX IF EXISTS uq_eo_match_pair")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_eo_match_expense
        ON transaction_expenseone_match (expense_id)
    """)

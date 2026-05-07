"""mapping_rules.applicable_directions — 매출/매입 방향 인지 매핑.

같은 거래처가 매출과 매입 둘 다 하는 경우 (예: 새로엠에스 — 매출 시
상품매출 / 매입 시 사무용품비) 잘못 매핑되는 문제 해결.

NULL = 모든 방향에 적용 (default 동작 유지)
['sales'] = 매출 거래에만 적용 (transactions.type='in' / invoices.direction='sales')
['purchase'] = 매입 거래에만 적용
['sales','purchase'] = 둘 다 명시적 적용 (NULL 과 동일)

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'y5z6a7b8c9d0'
down_revision: Union[str, None] = 'x4y5z6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE mapping_rules
        ADD COLUMN IF NOT EXISTS applicable_directions TEXT[] DEFAULT NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_mapping_rules_directions ON mapping_rules USING GIN(applicable_directions)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_mapping_rules_directions")
    op.execute("ALTER TABLE mapping_rules DROP COLUMN IF EXISTS applicable_directions")

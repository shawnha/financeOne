"""forecasts.line_items JSONB — 예상 항목 세부 라인 breakdown

한 forecast row 안에 여러 거래처·금액을 라인으로 저장할 수 있도록 한다.
예: 법률서비스 forecast 하나에 A법률사무소 100만 + B법률사무소 80만 → 합계 180만.

line_items 구조:
[
  {"name": "A법률사무소", "amount": 1000000, "note": "..."},
  {"name": "B법률사무소", "amount": 800000}
]

forecast_amount는 라인 합계로 자동 계산 (백엔드). NULL 이면 단일 금액(기존 동작).

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-21
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE forecasts
        ADD COLUMN IF NOT EXISTS line_items JSONB
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE forecasts DROP COLUMN IF EXISTS line_items")

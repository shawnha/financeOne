"""forecasts.holiday_rule — 예상 지급일 휴일 보정 룰

휴일/주말과 겹친 expected_day 를 어떻게 처리할지 항목별로 지정:
  - 'none'   : 보정 안 함 (default)
  - 'before' : 직전 영업일 (급여 통례)
  - 'after'  : 다음 영업일 (4대보험·세금·카드결제 통례)

Revision ID: f2g3h4i5j6k7
Revises: e1f2g3h4i5j6
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f2g3h4i5j6k7'
down_revision: Union[str, None] = 'e1f2g3h4i5j6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET search_path TO financeone, public")
    op.execute(
        """
        ALTER TABLE forecasts
        ADD COLUMN IF NOT EXISTS holiday_rule TEXT NOT NULL DEFAULT 'none'
        CHECK (holiday_rule IN ('none', 'before', 'after'))
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO financeone, public")
    op.execute("ALTER TABLE forecasts DROP COLUMN IF EXISTS holiday_rule")

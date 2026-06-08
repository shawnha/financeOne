"""forecasts UNIQUE 에 note 추가 — 같은 계정/월이라도 메모 다르면 별 항목 허용.

예상현금에서 같은 내부계정·월·타입이라도 메모가 다르면(예: "4월분"/"5월분")
별도 forecast 로 추가 가능하게 한다. recurring 자동생성은 note=NULL 이고
NULLS NOT DISTINCT 라 여전히 dedup 됨(동작 불변).

Revision ID: o1p2q3r4s5t6
Revises: n0o1p2q3r4s5
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = "o1p2q3r4s5t6"
down_revision: Union[str, None] = "n0o1p2q3r4s5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS financeone.uq_forecasts_account")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_account
          ON financeone.forecasts
             (entity_id, year, month, internal_account_id, type, note)
          NULLS NOT DISTINCT
          WHERE internal_account_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS financeone.uq_forecasts_account")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_account
          ON financeone.forecasts
             (entity_id, year, month, internal_account_id, type)
          WHERE internal_account_id IS NOT NULL
        """
    )

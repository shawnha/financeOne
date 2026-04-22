"""standard_accounts.name_en — 영문 계정명 (연결재무제표 영/한 토글용)

HOI 연결재무제표를 영문으로 출력할 때 각 계정의 영문명이 필요.
K-GAAP 한국법인 표준계정을 영문명과 함께 저장.

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-22
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE standard_accounts
        ADD COLUMN IF NOT EXISTS name_en TEXT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE standard_accounts DROP COLUMN IF EXISTS name_en")

"""entities.business_number — 법인 사업자번호 영속화

Codef 홈택스 sync 시 direction 자동 판별 (우리=공급자/공급받는자) 위해
entity 별 사업자번호를 entities 테이블에 영속화. 매번 호출 인자로 받지 않고
DB 에서 조회.

형식: digits only (10자리, 하이픈 제거 권장).

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-04-28
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE entities ADD COLUMN IF NOT EXISTS business_number TEXT
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_entities_business_number
        ON entities (business_number)
        WHERE business_number IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entities_business_number")
    op.execute("ALTER TABLE entities DROP COLUMN IF EXISTS business_number")

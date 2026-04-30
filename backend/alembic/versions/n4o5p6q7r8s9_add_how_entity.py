"""주식회사 한아원홀세일 (HOW) 법인 추가

한아원그룹 4번째 법인. parent_id=2 (HOK) — 기존 HOR 와 동일한 한국 자회사 구조.
internal_accounts 등 다른 테이블은 추가 후 UI 의 "다른 회사에서 복사" 또는 수동
입력으로 채움. ON CONFLICT 로 idempotent.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'n4o5p6q7r8s9'
down_revision: Union[str, None] = 'm3n4o5p6q7r8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO entities (code, name, type, currency, parent_id)
        VALUES ('HOW', '주식회사 한아원홀세일', 'KR_CORP', 'KRW', 2)
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    # entities 삭제는 FK 연쇄 위험 — 비활성화로 처리
    op.execute("UPDATE entities SET is_active = false WHERE code = 'HOW'")

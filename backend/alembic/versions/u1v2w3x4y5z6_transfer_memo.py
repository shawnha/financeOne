"""transactions.transfer_memo — 이체 시 입력 메모 (이체결과내역에서 import).

우리/신한 BZ뱅크 이체결과내역 grid_exceldata 의 '거래메모' 컬럼 등.
description (통장 표시) 과 별개로 사용자가 직접 적은 메모 (예: '주정차과태료',
'본사임대료', '운영자금 상환') 를 보존해 매핑 정확도 향상.

기존 `note` 와 의미 분리: note 는 사용자/내부 메모, transfer_memo 는 이체 원장 메모.

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'u1v2w3x4y5z6'
down_revision: Union[str, None] = 't0u1v2w3x4y5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transfer_memo TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tx_transfer_memo "
        "ON transactions(transfer_memo) WHERE transfer_memo IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tx_transfer_memo")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS transfer_memo")

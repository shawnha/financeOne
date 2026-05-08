"""82100 보험료 — is_vat_taxable=false 정정 (한국 부가세법 §26 보험상품 면세).

이전 migration w3x4y5z6a7b8 의 TAX_FREE_CODES 에서 82100 누락. 결과로 보험료 거래가
opex_excl_vat 계산 시 ÷1.1 처리되어 비용이 인위적으로 ₩14,661 적게 잡혔음
(한아원홀세일 4월 케이스 발견, 2026-05-08).

부가세법 §26 1항 11호: 보험업, 신탁업, 자산운용업의 용역 → 면세.
손해보험·생명보험 모두 인보이스에 부가세 없음 → ÷1.1 적용 부적절.

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'z6a7b8c9d0e1'
down_revision: Union[str, None] = 'y5z6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE standard_accounts
        SET is_vat_taxable = false
        WHERE code = '82100'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE standard_accounts
        SET is_vat_taxable = true
        WHERE code = '82100'
    """)

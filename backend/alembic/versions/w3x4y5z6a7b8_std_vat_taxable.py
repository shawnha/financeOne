"""standard_accounts.is_vat_taxable — VAT 과세/면세 분류.

K-GAAP 정합 손익계산서 (P&L VAT 제외 / 재무제표) 위해 각 표준계정의
부가세 과세 여부 표시. opex_excl_vat 계산 시:
  SUM(CASE WHEN is_vat_taxable THEN amount/1.1 ELSE amount END)

면세 (is_vat_taxable=false) 항목 (한국 부가세법 base):
- 인건비: 직원급여 (80200), 잡급 (80500)
- 4대보험/공과금: 세금과공과금 (81700)
- 영업외: 이자비용 (93100), 이자수익 (90100)

과세 (is_vat_taxable=true): 임차료, 통신비, 사무용품, 운반비, 광고비 등 일반 비용

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'w3x4y5z6a7b8'
down_revision: Union[str, None] = 'v2w3x4y5z6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 면세 표준계정 코드 (default false 로 시작 후 이 list 만 false 유지, 나머지는 true)
TAX_FREE_CODES = [
    "80200",  # 직원급여
    "80500",  # 잡급
    "81700",  # 세금과공과금 (조세)
    "93100",  # 이자비용 (영업외, 면세)
    "90100",  # 이자수익 (영업외, 면세)
    # 자산/부채/자본 계정은 손익에 안 들어가지만 default false 로 안전 처리
]


def upgrade() -> None:
    op.execute("""
        ALTER TABLE standard_accounts
        ADD COLUMN IF NOT EXISTS is_vat_taxable BOOLEAN NOT NULL DEFAULT true
    """)

    # 손익 비용 계정 중 면세 항목만 false 로 설정 (default true 와 다른 것들)
    op.execute(f"""
        UPDATE standard_accounts
        SET is_vat_taxable = false
        WHERE code IN ({", ".join(repr(c) for c in TAX_FREE_CODES)})
    """)

    # 자산/부채/자본 계정은 손익 영향 없으나, opex 계산 시 entity_id IN ... 와 함께 사용해도 안전
    # 매출/매출원가는 별도 처리 (revenue_excl_vat, cogs_excl_vat) 라 영향 없음

    op.execute("CREATE INDEX IF NOT EXISTS idx_std_vat_taxable ON standard_accounts(is_vat_taxable)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_std_vat_taxable")
    op.execute("ALTER TABLE standard_accounts DROP COLUMN IF EXISTS is_vat_taxable")

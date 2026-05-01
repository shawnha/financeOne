"""invoices.source_kind 컬럼 추가 + NAVER/SalesOne backfill

세금계산서 화면이 SalesOne (NAVER/Shopify/Amazon 등) 매출까지 보여주던 문제 해결.

source_kind:
  - 'tax_invoice'    : 홈택스 통합조회 또는 직접 등록한 진짜 세금계산서
  - 'platform_sales' : SalesOne(NAVER/Shopify/Amazon 등) 플랫폼 매출
  - 'manual'         : 사용자가 수동 등록한 임시 invoice (분류 보류)

세금계산서 화면은 source_kind='tax_invoice' 만 보여줌.
발생주의 매출/매입 인식 화면은 source_kind 무관 모두 보여줌.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-05-01
"""
from typing import Sequence, Union
from alembic import op


revision: str = 's9t0u1v2w3x4'
down_revision: Union[str, None] = 'r8s9t0u1v2w3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 컬럼 + CHECK
    op.execute("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'tax_invoice'
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_invoice_source_kind'
            ) THEN
                ALTER TABLE invoices ADD CONSTRAINT chk_invoice_source_kind
                CHECK (source_kind IN ('tax_invoice', 'platform_sales', 'manual'));
            END IF;
        END $$;
    """)

    # 2) backfill — note 의 'salesone:' 마커 있으면 platform_sales (확실한 신호)
    op.execute("""
        UPDATE invoices SET source_kind = 'platform_sales'
        WHERE note LIKE 'salesone:%' OR note LIKE 'salesone%'
    """)
    # NAVER/SHOPIFY/AMAZON/TIKTOK counterparty 도 platform_sales
    op.execute("""
        UPDATE invoices SET source_kind = 'platform_sales'
        WHERE source_kind = 'tax_invoice'
          AND (
            counterparty ILIKE 'NAVER%' OR
            counterparty ILIKE 'SHOPIFY%' OR
            counterparty ILIKE 'AMAZON%' OR
            counterparty ILIKE 'TIKTOK%'
          )
    """)

    # 3) 인덱스
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoices_source_kind
        ON invoices(entity_id, source_kind)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_invoices_source_kind")
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS chk_invoice_source_kind")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS source_kind")

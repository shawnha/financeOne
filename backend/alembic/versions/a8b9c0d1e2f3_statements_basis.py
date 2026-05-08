"""financial_statements.basis — 현금주의/발생주의 모드 분기.

K-GAAP 발생주의 재무제표 추가. 기존 record 는 모두 basis='cash' 로 backfill.
UNIQUE 제약을 (entity_id, fiscal_year, ki_num, start_month, end_month, basis) 로 재정의 →
동일 entity/period 의 cash + accrual record 공존 가능.

설계 doc: docs/statements-accrual-plan.md

Revision ID: a8b9c0d1e2f3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) basis 컬럼 추가 (기존 row 자동 'cash' backfill)
    op.execute("""
        ALTER TABLE financial_statements
        ADD COLUMN IF NOT EXISTS basis VARCHAR(16) NOT NULL DEFAULT 'cash'
    """)

    # 2) 기존 UNIQUE 제약 제거
    op.execute("""
        ALTER TABLE financial_statements
        DROP CONSTRAINT IF EXISTS financial_statements_entity_id_fiscal_year_ki_num_start_mon_key
    """)

    # 3) basis 포함 UNIQUE 재생성
    op.execute("""
        ALTER TABLE financial_statements
        ADD CONSTRAINT financial_statements_entity_period_basis_key
        UNIQUE (entity_id, fiscal_year, ki_num, start_month, end_month, basis)
    """)

    # 4) basis check (cash | accrual)
    op.execute("""
        ALTER TABLE financial_statements
        ADD CONSTRAINT financial_statements_basis_check
        CHECK (basis IN ('cash', 'accrual'))
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_fs_basis ON financial_statements(basis)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_fs_basis")
    op.execute("ALTER TABLE financial_statements DROP CONSTRAINT IF EXISTS financial_statements_basis_check")
    op.execute("ALTER TABLE financial_statements DROP CONSTRAINT IF EXISTS financial_statements_entity_period_basis_key")
    op.execute("""
        ALTER TABLE financial_statements
        ADD CONSTRAINT financial_statements_entity_id_fiscal_year_ki_num_start_mon_key
        UNIQUE (entity_id, fiscal_year, ki_num, start_month, end_month)
    """)
    op.execute("ALTER TABLE financial_statements DROP COLUMN IF EXISTS basis")

"""payee_aliases — 거래처명 별칭 (canonical ↔ alias 매핑).

매출관리 xlsx 의 정식 거래처명 (예: 동탄)아이튼튼약국) 과 거래내역의
counterparty (예: 이희성(아이튼) — 약국 사장 개인명+약자) 를 연결.

용도:
- 외상매출금 자동 계산: SUM(매출관리) - SUM(거래내역 입금, alias 매칭)
- 매출 회수율 분석 (월별)
- 거래처별 마진 분석 (제품 매출 + 입금 통합)

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'x4y5z6a7b8c9'
down_revision: Union[str, None] = 'w3x4y5z6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS payee_aliases (
            id              SERIAL PRIMARY KEY,
            entity_id       INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            canonical_name  TEXT NOT NULL,
            alias           TEXT NOT NULL,
            source          TEXT NOT NULL DEFAULT 'auto',
            confidence      NUMERIC(3, 2) NOT NULL DEFAULT 0.7,
            note            TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(entity_id, alias)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_payee_aliases_alias ON payee_aliases(entity_id, alias)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_payee_aliases_canonical ON payee_aliases(entity_id, canonical_name)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payee_aliases")

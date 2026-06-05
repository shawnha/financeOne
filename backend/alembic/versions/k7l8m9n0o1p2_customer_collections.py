"""customer_collections — 거래처 입출금(수금) raw 거래 (SsArt AccTransState).

자료: SsArt SIMS OpenAPI /v2/AccTransState/get/ (거래처별 입금/출금, 방식별).
컬럼: 명세서일자/번호, 거래처, 분류(보통예금/카드결제/몰 등), 입출구분, 금액.
거래처별 실수금 → 매출(AR)/선수금 대사용. customer_balances(스냅샷)와 별개의 거래원장.

거래 단위 — (entity_id, trans_date, trans_seq) UNIQUE.

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op


revision: str = "k7l8m9n0o1p2"
down_revision: Union[str, None] = "j6k7l8m9n0o1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financeone.customer_collections (
            id                  SERIAL PRIMARY KEY,
            entity_id           INTEGER NOT NULL REFERENCES financeone.entities(id),
            trans_date          DATE NOT NULL,
            trans_seq           TEXT NOT NULL,
            customer_code       TEXT,
            customer_name       TEXT,
            customer_print_name TEXT,
            method_code         TEXT,
            method              TEXT,
            io_gu               TEXT,
            amount              NUMERIC(18,2) NOT NULL DEFAULT 0,
            remark              TEXT,
            add_date            DATE,
            mod_date            DATE,
            source              TEXT,
            raw_row             JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (entity_id, trans_date, trans_seq)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_coll_entity_date "
        "ON financeone.customer_collections (entity_id, trans_date);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_coll_customer "
        "ON financeone.customer_collections (entity_id, customer_code);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS financeone.customer_collections;")

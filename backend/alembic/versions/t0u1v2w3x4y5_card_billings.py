"""card_billings — 카드사 월별 청구서/명세서 저장

Codef `/v1/kr/card/b/account/billing-list` 응답을 정규화해 저장.
청구서 = 카드사가 회사에 청구한 결제 예정/완료 내역. 거래 (transactions) 와 별개.

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-05-01
"""
from typing import Sequence, Union
from alembic import op


revision: str = 't0u1v2w3x4y5'
down_revision: Union[str, None] = 's9t0u1v2w3x4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS card_billings (
            id                 SERIAL PRIMARY KEY,
            entity_id          INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            card_org           TEXT NOT NULL,           -- 'lotte_card' / 'shinhan_card' / ...
            card_no_masked     TEXT,                    -- '****1840'
            billing_month      TEXT NOT NULL,           -- 'YYYYMM' 청구월
            billing_date       DATE,                    -- 청구일자
            settlement_date    DATE,                    -- 결제 예정일 (출금일)
            total_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,    -- 청구 총액
            principal_amount   NUMERIC(18,2),           -- 일시불/할부 원금
            installment_amount NUMERIC(18,2),           -- 할부 잔액
            interest_amount    NUMERIC(18,2),           -- 이자/수수료
            currency           TEXT NOT NULL DEFAULT 'KRW',
            status             TEXT NOT NULL DEFAULT 'pending',  -- pending|paid|overdue
            paid_amount        NUMERIC(18,2) NOT NULL DEFAULT 0,
            transaction_id     INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
                                       -- 결제 완료 시 매칭된 출금 transaction
            raw_data           JSONB,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(entity_id, card_org, card_no_masked, billing_month)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_card_billings_entity_month
        ON card_billings(entity_id, billing_month DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_card_billings_settlement
        ON card_billings(entity_id, settlement_date)
        WHERE status = 'pending'
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS card_billings")

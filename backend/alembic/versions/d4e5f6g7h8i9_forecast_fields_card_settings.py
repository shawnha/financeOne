"""Add expected_day, payment_method to forecasts; statement_day, billing_start_day to card_settings

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-04-01

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- forecasts 확장 (TENSION-1: is_fixed 제거, is_recurring 재사용) --
    op.execute("""
        ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS expected_day INTEGER;
    """)
    op.execute("""
        ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS payment_method TEXT DEFAULT 'bank' NOT NULL;
    """)
    # Codex-5: CHECK constraint
    op.execute("""
        ALTER TABLE forecasts ADD CONSTRAINT chk_forecasts_payment_method
            CHECK (payment_method IN ('bank', 'card'));
    """)

    # -- card_settings 확장 --
    op.execute("""
        ALTER TABLE card_settings ADD COLUMN IF NOT EXISTS statement_day INTEGER;
    """)
    op.execute("""
        ALTER TABLE card_settings ADD COLUMN IF NOT EXISTS billing_start_day INTEGER;
    """)

    # -- ARCH-5: partial unique index (card_number IS NULL 대응) --
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_card_settings_no_cardnum
            ON card_settings (entity_id, source_type) WHERE card_number IS NULL;
    """)

    # -- card_settings 초기 데이터 (한아원코리아 entity_id=2) --
    op.execute("""
        INSERT INTO card_settings (entity_id, card_name, source_type, payment_day, statement_day, billing_start_day)
        VALUES
            (2, '롯데카드', 'lotte_card', 15, 2, NULL),
            (2, '우리카드', 'woori_card', 25, 16, 11)
        ON CONFLICT (entity_id, source_type) WHERE card_number IS NULL DO UPDATE
        SET payment_day = EXCLUDED.payment_day,
            statement_day = EXCLUDED.statement_day,
            billing_start_day = EXCLUDED.billing_start_day;
    """)

    # -- ARCH-3: 기존 카드사용 forecast → payment_method='card' --
    op.execute("""
        UPDATE forecasts SET payment_method = 'card' WHERE category = '카드사용';
    """)


def downgrade() -> None:
    op.execute("UPDATE forecasts SET payment_method = 'bank' WHERE payment_method = 'card'")
    op.execute("ALTER TABLE forecasts DROP CONSTRAINT IF EXISTS chk_forecasts_payment_method")
    op.execute("ALTER TABLE forecasts DROP COLUMN IF EXISTS payment_method")
    op.execute("ALTER TABLE forecasts DROP COLUMN IF EXISTS expected_day")
    op.execute("DROP INDEX IF EXISTS uq_card_settings_no_cardnum")
    op.execute("ALTER TABLE card_settings DROP COLUMN IF EXISTS billing_start_day")
    op.execute("ALTER TABLE card_settings DROP COLUMN IF EXISTS statement_day")

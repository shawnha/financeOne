"""codef_api_log — Codef API 응답 기록 (transactionId 포함)

Codef 측 기술 문의 시 transactionId가 필요한데, 현재는 요청 끝난 뒤
그 값이 사라진다. 실패 응답을 DB에 보존해 UI에서 조회·복사 가능하게 한다.

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS codef_api_log (
          id              SERIAL PRIMARY KEY,
          entity_id       INTEGER,
          organization    TEXT,                -- 'lotte_card' | 'woori_bank' | ...
          endpoint        TEXT,
          result_code     TEXT,                -- 'CF-00000' | 'CF-12803' | ...
          message         TEXT,
          extra_message   TEXT,
          transaction_id  TEXT,                -- Codef 문의용 식별자
          is_error        BOOLEAN NOT NULL DEFAULT FALSE,
          request_params  JSONB,               -- masked
          response_body   JSONB,
          created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_codef_log_created
            ON codef_api_log(created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_codef_log_error
            ON codef_api_log(is_error, created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_codef_log_entity_org
            ON codef_api_log(entity_id, organization, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_codef_log_entity_org")
    op.execute("DROP INDEX IF EXISTS idx_codef_log_error")
    op.execute("DROP INDEX IF EXISTS idx_codef_log_created")
    op.execute("DROP TABLE IF EXISTS codef_api_log")

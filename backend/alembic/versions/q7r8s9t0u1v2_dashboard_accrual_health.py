"""Dashboard accrual gating — entities.accrual_data_status + dashboard_accrual_health view

Premise 4 (P3-9 진행 중 부정확 데이터 위에 dashboard 빌드) 처리:
- entities.accrual_data_status 컬럼 추가 ('accurate' | 'in_progress' | 'cold_start')
  - HOI = 'accurate' (QBO Report API direct, gating 무관)
  - HOK = 'in_progress' (P3-9 진행 중, 5/19 PASS, threshold 18/19)
  - HOR = 'cold_start' (운영 초기, 거래 적음)
  - HOW = 'cold_start' (신규 entity)
- dashboard_accrual_health view 추가 (cron monthly refresh)
  - dashboard 가 verify_bs_against_ledger script 직접 호출 안 하고 view 만 read

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'q7r8s9t0u1v2'
down_revision: Union[str, None] = 'p6q7r8s9t0u1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) entities.accrual_data_status 컬럼 추가
    op.execute("""
        ALTER TABLE financeone.entities
        ADD COLUMN IF NOT EXISTS accrual_data_status TEXT
            NOT NULL DEFAULT 'cold_start'
            CHECK (accrual_data_status IN ('accurate', 'in_progress', 'cold_start'))
    """)

    # 2) 초기값 설정 (entity code 기반)
    op.execute("""
        UPDATE financeone.entities
        SET accrual_data_status = CASE
            WHEN code = 'HOI' THEN 'accurate'      -- QBO Report API direct
            WHEN code = 'HOK' THEN 'in_progress'   -- P3-9 진행 중
            WHEN code = 'HOR' THEN 'cold_start'    -- 운영 초기
            WHEN code = 'HOW' THEN 'cold_start'    -- 신규 entity
            ELSE 'cold_start'
        END
        WHERE accrual_data_status = 'cold_start'   -- default 만 update
    """)

    # 3) dashboard_accrual_health 테이블 (materialized cache)
    # verify_bs_against_ledger 결과를 cache. cron 매월 1회 갱신.
    op.execute("""
        CREATE TABLE IF NOT EXISTS financeone.dashboard_accrual_health (
            entity_id INTEGER PRIMARY KEY REFERENCES financeone.entities(id) ON DELETE CASCADE,
            pass_count INTEGER NOT NULL DEFAULT 0,
            total_count INTEGER NOT NULL DEFAULT 19,
            last_run TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'unknown'
                CHECK (status IN ('accurate', 'in_progress', 'cold_start', 'unknown')),
            details JSONB,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dashboard_accrual_health_status
        ON financeone.dashboard_accrual_health(status)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS financeone.dashboard_accrual_health")
    op.execute("ALTER TABLE financeone.entities DROP COLUMN IF EXISTS accrual_data_status")

"""standard_accounts.gaap_type 컬럼 + US-GAAP COA seed

HOI 가 K-GAAP standard 에 매핑되던 임시 구조를 정상화.
- gaap_type 컬럼 추가 ('K_GAAP' | 'US_GAAP'), 기본 K_GAAP (기존 row 보존)
- code UNIQUE → (code, gaap_type) 복합 UNIQUE
- parent_code FK 제거 (code 가 더이상 단일 unique 가 아니므로). parent 트리는 application-level 로 유지.
- gaap_mapping 에 이미 있는 us_gaap_code/name 을 distinct 추출해 US-GAAP standard_accounts 로 INSERT.

NOTE: 기존 코드 곳곳의 `WHERE code = 'X'` lookup 은 별도 commit 에서
`AND gaap_type = 'K_GAAP'` 를 명시하도록 갱신. 마이그레이션만으론 ambiguous 가
발생할 수 있으므로 코드 변경과 함께 deploy 해야 안전.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'o5p6q7r8s9t0'
down_revision: Union[str, None] = 'n4o5p6q7r8s9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) gaap_type 컬럼 + CHECK
    op.execute("""
        ALTER TABLE standard_accounts
        ADD COLUMN IF NOT EXISTS gaap_type TEXT NOT NULL DEFAULT 'K_GAAP'
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'standard_accounts_gaap_type_chk'
            ) THEN
                ALTER TABLE standard_accounts
                ADD CONSTRAINT standard_accounts_gaap_type_chk
                CHECK (gaap_type IN ('K_GAAP', 'US_GAAP'));
            END IF;
        END $$;
    """)

    # 2) parent_code FK 제거 (code 가 더이상 단일 UNIQUE 가 아니므로 깨짐)
    op.execute("""
        ALTER TABLE standard_accounts
        DROP CONSTRAINT IF EXISTS standard_accounts_parent_code_fkey
    """)

    # 3) code UNIQUE → (code, gaap_type) 복합 UNIQUE
    op.execute("""
        ALTER TABLE standard_accounts
        DROP CONSTRAINT IF EXISTS standard_accounts_code_key
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'standard_accounts_code_gaap_unique'
            ) THEN
                ALTER TABLE standard_accounts
                ADD CONSTRAINT standard_accounts_code_gaap_unique
                UNIQUE (code, gaap_type);
            END IF;
        END $$;
    """)

    # 4) gaap_mapping 의 (us_gaap_code, us_gaap_name, category) distinct
    #    → standard_accounts (gaap_type='US_GAAP') 로 INSERT
    #    normal_side 는 코드 첫자리 휴리스틱 (1 자산/5 비용=DR, 2 부채/3 자본/4 수익=CR)
    op.execute("""
        INSERT INTO standard_accounts (code, name, category, normal_side, gaap_type, sort_order)
        SELECT DISTINCT
            us_gaap_code,
            MIN(us_gaap_name)                                   AS name,
            MIN(category)                                       AS category,
            CASE
                WHEN substring(us_gaap_code, 1, 1) IN ('1', '5') THEN 'debit'
                ELSE 'credit'
            END                                                 AS normal_side,
            'US_GAAP'                                           AS gaap_type,
            (substring(us_gaap_code, 1, 4))::int                AS sort_order
        FROM gaap_mapping
        WHERE us_gaap_code IS NOT NULL AND us_gaap_code <> ''
        GROUP BY us_gaap_code
        ON CONFLICT (code, gaap_type) DO NOTHING
    """)


def downgrade() -> None:
    # US-GAAP rows 삭제 → unique 복귀 → FK 복귀 → gaap_type 컬럼 제거
    op.execute("DELETE FROM standard_accounts WHERE gaap_type = 'US_GAAP'")
    op.execute("ALTER TABLE standard_accounts DROP CONSTRAINT IF EXISTS standard_accounts_code_gaap_unique")
    op.execute("ALTER TABLE standard_accounts ADD CONSTRAINT standard_accounts_code_key UNIQUE (code)")
    op.execute("""
        ALTER TABLE standard_accounts
        ADD CONSTRAINT standard_accounts_parent_code_fkey
        FOREIGN KEY (parent_code) REFERENCES standard_accounts(code)
    """)
    op.execute("ALTER TABLE standard_accounts DROP CONSTRAINT IF EXISTS standard_accounts_gaap_type_chk")
    op.execute("ALTER TABLE standard_accounts DROP COLUMN IF EXISTS gaap_type")

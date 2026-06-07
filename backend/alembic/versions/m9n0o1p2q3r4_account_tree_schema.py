"""account_tree_schema — 계정 트리 재설계 M1 스키마 신설 (가역, 데이터 무변경).

신설 테이블 4종 + internal_accounts 운영태그 3컬럼 + 트리거 함수 2종(비활성 생성).
정식설계 docs/account-tree-redesign-design.md §1·§2, 메커니즘 §1·§2·§4·§6·§7.
스코프 A'(plan-eng-review 2026-06-07): locked_statement_archive 풀머신·42그룹 dedup은 Phase2 보류.

- entity_standard_accounts : 법인별 표준 골격(결산 union). 빈 표준도 골격으로 유지. 롤업 영향 0.
- fiscal_period_locks      : 기간 동결(경량 historical 쓰기 가드). 2025-12 이하 잠금 대상.
- canonical_remap          : 중복 표준코드 일원화(old→canonical), 같은 gaap_type 내.
- remap_audit              : 행별 old→new 기록(역재생). entity_id로 영향 법인 추적.
- internal_accounts +3     : cost_behavior·is_subscription·cost_center (직교 운영태그, 롤업 영향 0).
- 트리거 함수 2종          : 기간잠금 가드 + 표준 도출 sync. 함수만 생성, 트리거 바인딩은 M2/M3.

⚠️ 이 마이그레이션은 순수 가산·가역(데이터 무변경). 트리거는 바인딩 안 함 → 발화 0.
   prod 적용은 dry-run(BEGIN…ROLLBACK)+diff+명시승인 후에만.

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = "m9n0o1p2q3r4"
down_revision: Union[str, None] = "l8m9n0o1p2q3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. entity_standard_accounts — 법인별 표준 골격(설계 §1.1) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financeone.entity_standard_accounts (
            id                  SERIAL PRIMARY KEY,
            entity_id           INTEGER NOT NULL REFERENCES financeone.entities(id),
            standard_account_id INTEGER NOT NULL REFERENCES financeone.standard_accounts(id),
            is_backbone         BOOLEAN NOT NULL DEFAULT TRUE,
            source              TEXT NOT NULL DEFAULT 'settlement',
            valid_from          DATE,
            note                TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (entity_id, standard_account_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_esa_entity "
        "ON financeone.entity_standard_accounts (entity_id);"
    )

    # ── 2. fiscal_period_locks — 기간 동결(설계 §1.2, 메커니즘 §1.2) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financeone.fiscal_period_locks (
            id         SERIAL PRIMARY KEY,
            entity_id  INTEGER NOT NULL REFERENCES financeone.entities(id),
            period     DATE NOT NULL,
            basis      TEXT NOT NULL CHECK (basis IN ('cash', 'accrual', 'both')),
            locked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            locked_by  INTEGER REFERENCES financeone.members(id),
            note       TEXT,
            UNIQUE (entity_id, period, basis)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_fpl_entity_period "
        "ON financeone.fiscal_period_locks (entity_id, period);"
    )

    # ── 3. canonical_remap — 중복 표준코드 일원화(설계 §1.2, 메커니즘 §2.2) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financeone.canonical_remap (
            id             SERIAL PRIMARY KEY,
            old_account_id INTEGER NOT NULL REFERENCES financeone.standard_accounts(id),
            new_account_id INTEGER NOT NULL REFERENCES financeone.standard_accounts(id),
            gaap_type      TEXT NOT NULL CHECK (gaap_type IN ('K_GAAP', 'US_GAAP')),
            is_relabel     BOOLEAN NOT NULL,
            reason         TEXT,
            applied_at     TIMESTAMPTZ,
            CHECK (old_account_id <> new_account_id)
        );
        """
    )

    # ── 4. remap_audit — 행별 old→new 감사(메커니즘 §7.1, entity_id §14-M3) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financeone.remap_audit (
            id          SERIAL PRIMARY KEY,
            batch_id    UUID NOT NULL,
            table_name  TEXT NOT NULL,
            row_id      INTEGER NOT NULL,
            column_name TEXT NOT NULL,
            old_value   INTEGER,
            new_value   INTEGER,
            entity_id   INTEGER,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reverted_at TIMESTAMPTZ
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_remap_audit_batch "
        "ON financeone.remap_audit (batch_id);"
    )

    # ── 5. internal_accounts 운영태그 3컬럼(설계 §1.3, 메커니즘 §6.1) ──
    # 직교 태그 — 어떤 재무제표 롤업도 안 읽음(롤업 권위=category/subcategory). 재무 영향 0.
    op.execute(
        """
        ALTER TABLE financeone.internal_accounts
            ADD COLUMN IF NOT EXISTS cost_behavior   TEXT
                CHECK (cost_behavior IN ('fixed', 'variable')),
            ADD COLUMN IF NOT EXISTS is_subscription BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS cost_center     TEXT;
        """
    )

    # ── 6. 트리거 함수 2종 — 생성만, 바인딩(ENABLE)은 M2/M3 ──
    # (a) 기간잠금 가드(메커니즘 §1.3-A). 잠긴 (entity, period) 쓰기 거부.
    #     financeone.allow_locked_write=on 세션에서만 우회(통제된 재분류·마이그).
    #     M1에서는 함수만 — 어떤 테이블에도 트리거 바인딩 안 함 → 발화 0.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION financeone.trg_fiscal_period_lock_guard()
        RETURNS trigger AS $$
        DECLARE
            v_entity_id INTEGER;
            v_date      DATE;
            v_row       RECORD;
        BEGIN
            IF current_setting('financeone.allow_locked_write', true) = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;

            v_row := COALESCE(NEW, OLD);

            IF TG_TABLE_NAME = 'transactions' THEN
                v_entity_id := v_row.entity_id;
                v_date      := v_row.date;
            ELSIF TG_TABLE_NAME = 'journal_entry_lines' THEN
                SELECT je.entity_id, je.entry_date INTO v_entity_id, v_date
                  FROM financeone.journal_entries je
                 WHERE je.id = v_row.journal_entry_id;
            ELSIF TG_TABLE_NAME = 'transaction_splits' THEN
                SELECT t.entity_id, t.date INTO v_entity_id, v_date
                  FROM financeone.transactions t
                 WHERE t.id = v_row.transaction_id;
            ELSE
                RETURN v_row;
            END IF;

            IF v_entity_id IS NULL OR v_date IS NULL THEN
                RETURN v_row;
            END IF;

            IF EXISTS (
                SELECT 1 FROM financeone.fiscal_period_locks fpl
                 WHERE fpl.entity_id = v_entity_id
                   AND fpl.period = date_trunc('month', v_date)::date
            ) THEN
                RAISE EXCEPTION
                    'fiscal period locked: entity=% period=% (table=%). '
                    'Set financeone.allow_locked_write=on for controlled reclassification.',
                    v_entity_id, date_trunc('month', v_date)::date, TG_TABLE_NAME;
            END IF;

            RETURN v_row;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # (b) 표준 도출 sync(메커니즘 §4.3). 내부 잎 있고 splits 없으면 표준=내부.std 도출.
    #     financeone.bypass_std_sync=on 에서만 우회(잎 교정 끝나기 전·벌크 마이그).
    #     ⚠️ M1에서는 함수만 — 트리거 바인딩은 M3(잎 교정 완료 후, 불변식 #1).
    #        INSERT 시 NEW.id 부재로 splits 조회 불가(§4.4)는 M3 바인딩에서 BEFORE/AFTER 결정.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION financeone.trg_sync_standard_from_internal()
        RETURNS trigger AS $$
        BEGIN
            IF current_setting('financeone.bypass_std_sync', true) = 'on' THEN
                RETURN NEW;
            END IF;
            IF NEW.internal_account_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM financeone.transaction_splits
                    WHERE transaction_id = NEW.id
               ) THEN
                SELECT standard_account_id INTO NEW.standard_account_id
                  FROM financeone.internal_accounts
                 WHERE id = NEW.internal_account_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    # 역순 DROP — 완전 가역(데이터 무변경이라 손실 0, 운영태그 값만 소실).
    op.execute("DROP FUNCTION IF EXISTS financeone.trg_sync_standard_from_internal();")
    op.execute("DROP FUNCTION IF EXISTS financeone.trg_fiscal_period_lock_guard();")
    op.execute(
        """
        ALTER TABLE financeone.internal_accounts
            DROP COLUMN IF EXISTS cost_center,
            DROP COLUMN IF EXISTS is_subscription,
            DROP COLUMN IF EXISTS cost_behavior;
        """
    )
    op.execute("DROP TABLE IF EXISTS financeone.remap_audit;")
    op.execute("DROP TABLE IF EXISTS financeone.canonical_remap;")
    op.execute("DROP TABLE IF EXISTS financeone.fiscal_period_locks;")
    op.execute("DROP TABLE IF EXISTS financeone.entity_standard_accounts;")

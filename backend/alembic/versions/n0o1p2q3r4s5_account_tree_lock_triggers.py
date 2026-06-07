"""account_tree_lock_triggers — M2 기간잠금 가드 트리거 바인딩 (코리아 PoC).

trg_fiscal_period_lock_guard(M1에서 생성)를 transactions·journal_entry_lines·transaction_splits에
BEFORE INSERT/UPDATE/DELETE FOR EACH ROW로 바인딩. 잠긴 (entity, period) 쓰기 거부.
financeone.allow_locked_write=on 세션에서만 우회(통제된 재분류·마이그).

⚠️ lock 행이 없으면 아무것도 막지 않음(fast-negative). 코리아 2025 lock 행은
   scripts/account_tree_m2_korea_lock.py 로 등록. 다른 법인/2026은 미잠금 → 정상 입력 통과.
정식설계 §2.3·§5.1-step2, 메커니즘 §1.3-A.

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = "n0o1p2q3r4s5"
down_revision: Union[str, None] = "m9n0o1p2q3r4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("transactions", "journal_entry_lines", "transaction_splits")


def upgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_period_lock_guard ON financeone.{tbl};")
        op.execute(
            f"""
            CREATE TRIGGER trg_period_lock_guard
                BEFORE INSERT OR UPDATE OR DELETE ON financeone.{tbl}
                FOR EACH ROW EXECUTE FUNCTION financeone.trg_fiscal_period_lock_guard();
            """
        )


def downgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_period_lock_guard ON financeone.{tbl};")

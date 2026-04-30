"""K-GAAP standard_accounts 14개 누락 코드 보강

도팜인(=한아원홀세일) 25년 결산 ledger 에 등장하지만 기존 K_GAAP standard_accounts
139건에 없던 코드들. HOW internal_accounts seed 53개 중 14개가 standard 매핑 못
받던 문제 해결.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'p6q7r8s9t0u1'
down_revision: Union[str, None] = 'o5p6q7r8s9t0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (code, name, category, subcategory, normal_side, sort_order)
NEW_K_GAAP_ACCOUNTS = [
    ("11400", "단기대여금",   "자산", "당좌자산",   "debit",  1140),
    ("11600", "미수수익",     "자산", "당좌자산",   "debit",  1160),
    ("13300", "선급비용",     "자산", "당좌자산",   "debit",  1330),
    ("25900", "선수금",       "부채", "유동부채",   "credit", 2590),
    ("26000", "단기차입금",   "부채", "유동부채",   "credit", 2600),
    ("29300", "장기차입금",   "부채", "비유동부채", "credit", 2930),
    ("81400", "통신비",       "비용", "판매관리비", "debit",  8140),
    ("81600", "전력비",       "비용", "판매관리비", "debit",  8160),
    ("82000", "수선비",       "비용", "판매관리비", "debit",  8200),
    ("82200", "차량유지비",   "비용", "판매관리비", "debit",  8220),
    ("82500", "교육훈련비",   "비용", "판매관리비", "debit",  8250),
    ("82600", "도서인쇄비",   "비용", "판매관리비", "debit",  8260),
    ("83700", "건물관리비",   "비용", "판매관리비", "debit",  8370),
    ("93100", "이자비용",     "비용", "영업외비용", "debit",  9310),
]


def upgrade() -> None:
    for code, name, category, subcategory, normal_side, sort_order in NEW_K_GAAP_ACCOUNTS:
        op.execute(f"""
            INSERT INTO standard_accounts
                (code, name, category, subcategory, normal_side, sort_order, gaap_type, is_active)
            VALUES
                ('{code}', '{name}', '{category}', '{subcategory}',
                 '{normal_side}', {sort_order}, 'K_GAAP', true)
            ON CONFLICT (code, gaap_type) DO NOTHING
        """)


def downgrade() -> None:
    codes = ", ".join(f"'{c[0]}'" for c in NEW_K_GAAP_ACCOUNTS)
    op.execute(f"""
        DELETE FROM standard_accounts
        WHERE gaap_type = 'K_GAAP' AND code IN ({codes})
    """)

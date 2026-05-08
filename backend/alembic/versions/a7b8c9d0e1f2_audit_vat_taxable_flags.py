"""면세 계정 전수 감사 — 한국 부가세법 §26 + K-GAAP 결산자료 cross-check 후 17개 정정.

이전 migration w3x4y5z6a7b8 가 면세 코드 5개만 (80200, 80500, 81700, 93100, 90100)
박아둠 → 인건비 family/감가상각비/이자비용/외환차손/잡손실/법인세 모두 default true 로
잘못 분류됨.

## 검증 절차 (2026-05-08)

1. 결산자료 cross-check
   - 한아원홀세일 (도팜인) 25년 K-GAAP 손익계산서:
     `~/Documents/HanahOneAll/한아원홀세일/재무자료/25년 재무제표.pdf`
   - 한아원코리아 25년 K-GAAP 손익계산서:
     `~/Documents/HanahOneAll/Finance/결산자료/[주식회사 한아원코리아]_25년귀속 재무제표 (2).pdf`
   → 양 회사 모두 보험료 별도 line, 인건비 별도 line, 영업외 잡손실 분리 확인

2. 부가세법 §26 웹 검증 (국세청, 회계기준원, 주요 회계법인)
   - §26 11호: 금융·보험용역 면세 (이자, 보험료)
   - §26 14호: 토지 면세
   - §26 15호: 인적용역 면세
   - 시행령 §40 (금융), §42 (인적용역)
   → 본 migration 17개 모두 면세 확정

3. KB 노트
   - `~/Documents/HanahOneAll/Knowledge/법령/부가세법-26조-면세-매핑.md`
   - `~/Documents/HanahOneAll/Knowledge/결산자료-매핑/한아원홀세일-2025-손익계산서.md`
   - `~/Documents/HanahOneAll/Knowledge/결산자료-매핑/한아원코리아-2025-손익계산서.md`
   - `~/Documents/HanahOneAll/Knowledge/표준계정-검증/2026-05-08-VAT-taxable-감사기록.md`

## 영향 범위

| 카테고리 | 코드 | 한아원홀세일 1~5월 | 한아원코리아 1~5월 |
|---|---|---|---|
| 인건비 | 80100, 50200, 50300 | 0 (매핑 차후) | 0 (매핑 차후) |
| 비현금성 | 51100, 51000 | ₩484K | 0 |
| 조세 | 50900 | 0 | ₩5K |
| 이자 | 52000, 90200, 93300 | 0 | 0 |
| 외환 | 52100, 52200, 93600 | 0 | 0 |
| 잡손실 | 52300, 95300, 96000 | ₩194K | ₩200M |
| 법인세 | 52400, 99800 | 0 | 0 |

영업외 항목 (이자, 외환, 잡손실, 법인세)은 opex_excl_vat 계산에 영향 없음 (영업외는
÷1.1 적용 안 함). 다만 데이터 정합성 차원 정정.

판관비 항목 (인건비, 비현금, 세금) 은 opex_excl_vat 영향 있음.

Revision ID: a7b8c9d0e1f2
Revises: z6a7b8c9d0e1
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'z6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 부가세 면세 (default true 였던 항목)
ADDITIONAL_TAX_FREE_CODES = [
    # 인건비 family (노무용역 면세)
    "80100",  # 직원급여
    "50200",  # 급여 (구 K-GAAP 코드)
    "50300",  # 퇴직급여
    # 비현금성 (외부거래 아님)
    "51100",  # 감가상각비 (현행)
    "51000",  # 감가상각비 (구 코드)
    # 조세 (81700과 정합)
    "50900",  # 세금과공과 (구 코드)
    # 금융용역 (§26 11호, 93100과 정합)
    "52000",  # 이자비용 (구)
    "90200",  # 이자비용
    "93300",  # 이자비용
    "52100",  # 외환차손
    "52200",  # 외화환산손실
    "93600",  # 외환차손
    # 잡손실 family (영업외 비거래)
    "52300",  # 잡손실
    "95300",  # 잡손실
    "96000",  # 잡손실
    # 법인세 (별도 line)
    "52400",  # 법인세비용
    "99800",  # 법인세등
]


def upgrade() -> None:
    op.execute(f"""
        UPDATE standard_accounts
        SET is_vat_taxable = false
        WHERE code IN ({", ".join(repr(c) for c in ADDITIONAL_TAX_FREE_CODES)})
    """)


def downgrade() -> None:
    op.execute(f"""
        UPDATE standard_accounts
        SET is_vat_taxable = true
        WHERE code IN ({", ".join(repr(c) for c in ADDITIONAL_TAX_FREE_CODES)})
    """)

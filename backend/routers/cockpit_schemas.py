# 경영 코쿼핏(사장님 뷰) API 응답 Pydantic 스키마
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class CockpitFx(BaseModel):
    usd_krw: Decimal          # 1 USD = ? KRW (월말 기준, 뱃지용)
    as_of: str                # YYYY-MM-DD (환율 기준일)


class CockpitEntity(BaseModel):
    id: int
    code: str
    name: str
    currency: str             # 자국통화 (KRW/USD)
    income: Decimal           # 월 수입 (native)
    expense: Decimal          # 월 지출 (native)
    net: Decimal              # 월 순현금 (native)
    balance: Decimal          # 통장 잔고 (native)


class CockpitGroup(BaseModel):
    income: Decimal           # display_currency 환산 (영업만)
    expense: Decimal          # 영업만
    net: Decimal
    balance: Decimal
    runway_months: Optional[Decimal] = None   # 적자일 때만, 흑자면 None
    nonop_income: Decimal = Decimal("0")      # 제외한 비영업(재무·투자) 수입 — 투명표기
    nonop_expense: Decimal = Decimal("0")     # 제외한 비영업 지출


class CockpitTrendPoint(BaseModel):
    month: str                # YYYY-MM
    net: Decimal              # 그룹 순현금 (display_currency)


class CockpitCeoResponse(BaseModel):
    year_month: str
    display_currency: str     # USD | KRW
    fx: CockpitFx
    entities: List[CockpitEntity]
    group: CockpitGroup
    trend: List[CockpitTrendPoint]

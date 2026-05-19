"""한국 영업일 보정 — 예상 지급일이 휴일/주말일 때 직전/직후 영업일로 이동.

forecasts.holiday_rule:
  - 'none'   : 보정 안 함 (expected_day 그대로)
  - 'before' : 휴일이면 직전 영업일 (급여 통례)
  - 'after'  : 휴일이면 다음 영업일 (4대보험·세금·카드결제 통례)
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Literal, Optional

import holidays

HolidayRule = Literal["none", "before", "after"]


@lru_cache(maxsize=8)
def _kr_holidays(year: int) -> holidays.HolidayBase:
    """연도별 한국 공휴일 캐시 (lru_cache — 같은 연도 재호출 시 재계산 없음)."""
    return holidays.KR(years=[year])


def is_business_day(d: date) -> bool:
    """영업일 여부 — 주말(토/일) + 한국 공휴일 제외."""
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return False
    if d in _kr_holidays(d.year):
        return False
    return True


def _step(d: date, direction: int) -> date:
    """주말/공휴일 건너뛰며 한 방향으로 이동."""
    cur = d
    while not is_business_day(cur):
        cur += timedelta(days=direction)
    return cur


def clamp_day_to_month(day: int, year: int, month: int) -> int:
    """expected_day 가 해당 월 마지막 날을 초과하면 마지막 날로 clamp.
    (예: 31일 설정 → 2월은 28/29, 4월은 30)
    """
    if month == 12:
        last = 31
    else:
        last = (date(year, month + 1, 1) - timedelta(days=1)).day
    return min(day, last)


def adjust_to_business_day(
    year: int, month: int, day: int, rule: HolidayRule = "none",
) -> tuple[date, date]:
    """예상 지급일을 룰에 따라 영업일로 보정.

    Returns:
        (original_date, adjusted_date) — original 은 보정 전, adjusted 는 보정 후.
        rule='none' 이면 둘 다 동일.
        adjusted 가 다른 월로 넘어가면 원래 월 안의 가장 가까운 영업일로 fallback.
    """
    clamped = clamp_day_to_month(day, year, month)
    original = date(year, month, clamped)

    if rule == "none":
        return original, original

    if is_business_day(original):
        return original, original

    direction = -1 if rule == "before" else 1
    adjusted = _step(original, direction)

    # 다른 월로 넘어가면 같은 월의 반대 방향 영업일로 fallback
    if adjusted.year != year or adjusted.month != month:
        adjusted = _step(original, -direction)

    return original, adjusted


def default_rule_for_account(account_name: Optional[str]) -> HolidayRule:
    """내부계정 이름으로 default holiday_rule 추정.
    급여/상여는 before, 4대보험·세금·카드결제·임대료는 after, 그 외 none.
    """
    if not account_name:
        return "none"
    name = account_name.lower()
    # 급여류 — 휴일이면 앞당겨 지급
    if any(k in account_name for k in ("급여", "월급", "상여", "성과급", "임금", "인건비")):
        return "before"
    # 세금·보험·카드·임대 — 휴일이면 다음 영업일
    if any(k in account_name for k in (
        "4대보험", "국민연금", "건강보험", "고용보험", "산재보험",
        "세금", "원천세", "부가세", "법인세", "지방세",
        "카드결제", "카드대금", "임대료", "월세",
    )):
        return "after"
    return "none"

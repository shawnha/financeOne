"""KST(Asia/Seoul) timezone 헬퍼.

P1-4: forecast/scheduler/import 로직에서 `date.today()` / `datetime.now()` 사용 시
서버 timezone(UTC 등)에 따라 KST 자정~9시 사이 하루 어긋남 발생.
모든 비즈니스 로직은 KST 기준으로 통일 (한아원그룹 본사 운영 timezone).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """현재 시각 (KST timezone-aware datetime)."""
    return datetime.now(tz=KST)


def today_kst() -> date:
    """현재 KST 기준 오늘 날짜 (date 객체).

    서버 timezone 무관 — 항상 한국 영업일 기준.
    """
    return now_kst().date()

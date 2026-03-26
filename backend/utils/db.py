"""Database utility functions."""

import calendar
from datetime import date


def fetch_all(cur) -> list[dict]:
    """Convert cursor results to list of dicts using column names."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_date_range(year: int, month: int) -> tuple[date, date]:
    """Return (first_day, next_month_first_day) for use in date >= %s AND date < %s.

    Replaces EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
    which can't use indexes efficiently.
    """
    first_day = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return first_day, next_month

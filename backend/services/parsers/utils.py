"""Shared parsing utilities for date and amount fields."""

from datetime import date
from typing import Optional


def parse_date(s: str) -> Optional[date]:
    """Parse various Korean/intl date formats into a date object."""
    if not s or not s.strip():
        return None
    s = s.strip()

    # Try ISO format first
    for fmt_sep in ("-", ".", "/"):
        parts = s.split(fmt_sep)
        if len(parts) == 3:
            try:
                if len(parts[0]) == 4:
                    return date(int(parts[0]), int(parts[1]), int(parts[2]))
                elif len(parts[2]) == 4:
                    return date(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                continue

    # Fallback: strip non-digit then parse YYYYMMDD
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            pass

    return None


def parse_amount(s: str) -> Optional[float]:
    """Parse amount string, handling commas, parens (negative), etc."""
    if s is None:
        return None
    try:
        cleaned = str(s).strip().replace(",", "").replace(" ", "")
        if not cleaned or cleaned == "-":
            return None
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        return float(cleaned)
    except (ValueError, AttributeError):
        return None

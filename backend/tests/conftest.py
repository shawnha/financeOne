"""Shared fixtures for Phase 1 backend tests."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `backend.*` imports resolve.
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # financeOne/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_DIR = PROJECT_ROOT / "transaction_sample"


@pytest.fixture
def lotte_card_bytes() -> bytes:
    """Raw bytes of the Lotte Card January sample file."""
    path = SAMPLE_DIR / "롯데카드_1월.xls"
    return path.read_bytes()


@pytest.fixture
def woori_card_bytes() -> bytes:
    """Raw bytes of the Woori Card January sample file."""
    path = SAMPLE_DIR / "우리카드_1월.xls"
    return path.read_bytes()


@pytest.fixture
def woori_bank_bytes() -> bytes:
    """Raw bytes of the Woori Bank January sample file."""
    path = SAMPLE_DIR / "우리은행 거래내역_1월.xlsx"
    return path.read_bytes()

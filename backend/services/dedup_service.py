"""중복 거래 감지 서비스 — O(1) set 기반."""

from collections import Counter


def build_file_key_counts(parsed) -> Counter:
    """파일 내 동일 키 거래의 누적 카운트를 O(n)으로 계산.

    Returns: Counter mapping dedup_key → count
    """
    counter = Counter()
    cumulative = {}
    for i, tx in enumerate(parsed):
        key = _make_key(tx)
        counter[key] += 1
        cumulative[i] = counter[key]
    return cumulative


def is_file_duplicate(tx_index: int, cumulative: dict, db_count: int) -> bool:
    """파일 내 해당 거래의 누적 순번이 DB 기존 개수 이하면 중복."""
    return cumulative[tx_index] <= db_count


def _make_key(tx) -> tuple:
    """거래의 중복 감지 키 생성."""
    return (str(tx.date), tx.amount, tx.counterparty, tx.description, tx.source_type)

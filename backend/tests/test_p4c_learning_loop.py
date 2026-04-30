"""P4-C 학습 루프 단위테스트.

검증:
  - extract_words: 단어 추출 정확
  - passes_noise_filter: stopwords + 짧은 영문 + 길이 제약
  - normalize_keyword_for_storage: brand 약자 보존, 일반 영문 lowercase
  - DB integration: candidate extraction (DATABASE_URL 있을 때)
"""
import os

import psycopg2
import pytest
from dotenv import load_dotenv

from backend.scripts.learn_keywords_from_confirmed import (
    STOPWORDS,
    SHORT_ENGLISH_WHITELIST,
    extract_words,
    passes_noise_filter,
    normalize_keyword_for_storage,
)


# ─── extract_words ──────────────────────────────────────────


def test_extract_words_korean():
    words = extract_words("스타벅스 강남역점")
    assert "스타벅스" in words
    assert "강남역점" in words


def test_extract_words_english():
    words = extract_words("Adobe Creative Cloud")
    # 2자 이상 단어만 (Adobe, Creative, Cloud)
    assert "Adobe" in words
    assert "Creative" in words


def test_extract_words_mixed():
    words = extract_words("주식회사 한아원 (주) Hanahone Inc")
    assert "주식회사" in words or "(주)" in [w for w in words]
    assert "한아원" in words
    assert "Hanahone" in words
    assert "Inc" in words


def test_extract_words_handles_special_chars():
    words = extract_words("(주)이니시스 - KCP결제대행")
    # 특수문자 제거, 알파벳/한글만
    assert "이니시스" in words
    # KCP 추출됨
    assert "KCP" in words or "KCP결제대행" in words


def test_extract_words_empty():
    assert extract_words("") == []
    assert extract_words(None) == []


# ─── passes_noise_filter ────────────────────────────────────


def test_filter_blocks_stopwords():
    assert not passes_noise_filter("주식회사")
    assert not passes_noise_filter("(주)")
    assert not passes_noise_filter("재단법인")
    assert not passes_noise_filter("협동조합")
    assert not passes_noise_filter("USA")
    assert not passes_noise_filter("CITY")  # 이전 시도 노이즈
    assert not passes_noise_filter("CULVER")


def test_filter_blocks_stopwords_case_insensitive():
    assert not passes_noise_filter("usa")
    assert not passes_noise_filter("city")
    assert not passes_noise_filter("Inc")


def test_filter_blocks_short_english():
    """3자 미만 영문 거부 (화이트리스트 외)."""
    assert not passes_noise_filter("ab")
    assert not passes_noise_filter("xy")
    # 화이트리스트는 통과
    assert passes_noise_filter("KFC")
    assert passes_noise_filter("AWS")
    assert passes_noise_filter("KTX")


def test_filter_blocks_short_korean():
    """1자 한글 거부."""
    assert not passes_noise_filter("가")


def test_filter_passes_korean_2chars():
    assert passes_noise_filter("스벅")  # 의미 없는 2자라도 길이 OK


def test_filter_passes_normal_words():
    assert passes_noise_filter("스타벅스")
    assert passes_noise_filter("Adobe")
    assert passes_noise_filter("Creative")
    assert passes_noise_filter("이니시스")


# ─── normalize_keyword_for_storage ──────────────────────────


def test_normalize_korean_unchanged():
    assert normalize_keyword_for_storage("스타벅스") == "스타벅스"


def test_normalize_short_uppercase_brand_preserved():
    assert normalize_keyword_for_storage("KFC") == "KFC"
    assert normalize_keyword_for_storage("AWS") == "AWS"
    assert normalize_keyword_for_storage("KTX") == "KTX"


def test_normalize_long_english_lowercased():
    """4자 초과 일반 영문은 lowercase 정규화 (중복 방지)."""
    assert normalize_keyword_for_storage("Adobe") == "adobe"
    assert normalize_keyword_for_storage("Creative") == "creative"


def test_normalize_mixed_case_lowercased():
    assert normalize_keyword_for_storage("PayPal") == "paypal"


# ─── DB integration ─────────────────────────────────────────


@pytest.fixture(scope="module")
def db_conn():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL 미설정")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    cur.close()
    yield conn
    conn.close()


def test_db_extract_candidates_no_noise(db_conn):
    """이전 시도 회귀: USA / CITY / CULVER 가 후보에 안 들어가야 함."""
    from backend.scripts.learn_keywords_from_confirmed import extract_candidates

    candidates = extract_candidates(db_conn)
    keywords = {c["keyword"].upper() for c in candidates}

    forbidden = {"USA", "CITY", "CULVER", "INC", "CORP", "LLC"}
    leaked = keywords & forbidden
    assert not leaked, f"이전 시도 노이즈 후보에 등장: {leaked}"


def test_db_measure_coverage_returns_dict(db_conn):
    from backend.scripts.learn_keywords_from_confirmed import measure_coverage

    metric = measure_coverage(db_conn)
    assert "entities" in metric
    assert "standard_account_keywords" in metric
    assert "timestamp" in metric


def test_db_no_short_english_candidates(db_conn):
    """후보 중 짧은 영문 대문자 약자가 화이트리스트 외에 없는지."""
    from backend.scripts.learn_keywords_from_confirmed import extract_candidates

    candidates = extract_candidates(db_conn)
    for c in candidates:
        kw = c["keyword"]
        if kw.isascii() and 2 <= len(kw) <= 3 and kw.isupper():
            assert kw in SHORT_ENGLISH_WHITELIST, (
                f"화이트리스트 외 짧은 영문 후보: {kw}"
            )

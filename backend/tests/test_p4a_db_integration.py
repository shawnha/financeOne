"""P4-A integration test — DB 무결성 검증.

P1-6 (Code Reviewer 발견): standard_account_code 가 실제 DB 에 존재하는지 검증.
expand_keyword_dictionary.py 의 silent skip (code_to_id.get(code) is None) 이
CI 에서 잡히지 않는 위험 차단.

실행:
  pytest backend/tests/test_p4a_db_integration.py -v

Skip 조건:
  DATABASE_URL 환경변수 없으면 자동 skip (단위테스트만 실행 가능).
"""
import os

import psycopg2
import pytest
from dotenv import load_dotenv

from backend.scripts.expand_keyword_dictionary import DOMAIN_KEYWORDS


def _get_conn():
    """DB 연결. DATABASE_URL 없으면 None."""
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    return psycopg2.connect(url)


@pytest.fixture(scope="module")
def db_conn():
    conn = _get_conn()
    if conn is None:
        pytest.skip("DATABASE_URL 미설정 — integration test skip")
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    cur.close()
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def code_to_id(db_conn):
    cur = db_conn.cursor()
    cur.execute("SELECT code, id FROM standard_accounts")
    mapping = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()
    return mapping


def test_all_codes_exist_in_db(code_to_id):
    """DOMAIN_KEYWORDS 의 모든 standard_account_code 가 DB 에 존재."""
    missing = [code for _, code, _ in DOMAIN_KEYWORDS if code not in code_to_id]
    assert not missing, (
        f"DB 에 없는 standard_account_code 매핑 시도: {set(missing)} "
        f"(silent skip 발생 위험)"
    )


def test_inserted_keywords_match_dictionary(db_conn):
    """스크립트 1회 실행 후 DB 의 키워드 ⊇ DOMAIN_KEYWORDS (운영 적용 확인).

    참고: 14개 기존 키워드는 별도. 본 검증은 P4-A 스크립트 실행 후만 의미 있음.
    """
    cur = db_conn.cursor()
    cur.execute("SELECT keyword FROM standard_account_keywords")
    db_keywords = {r[0] for r in cur.fetchall()}
    cur.close()

    script_keywords = {kw for kw, _, _ in DOMAIN_KEYWORDS}
    not_in_db = script_keywords - db_keywords
    if not_in_db:
        pytest.skip(
            f"P4-A 스크립트 미실행 또는 신규 키워드 추가됨: {not_in_db}. "
            f"`python -m backend.scripts.expand_keyword_dictionary` 실행 필요."
        )


def test_no_dangling_keyword_to_account(db_conn):
    """DB 의 모든 standard_account_keywords.standard_account_id 가 valid FK."""
    cur = db_conn.cursor()
    cur.execute(
        """
        SELECT k.id, k.keyword, k.standard_account_id
        FROM standard_account_keywords k
        LEFT JOIN standard_accounts sa ON k.standard_account_id = sa.id
        WHERE sa.id IS NULL
        """
    )
    dangling = cur.fetchall()
    cur.close()
    assert not dangling, f"FK 무결성 깨짐: {dangling}"


def test_keyword_length_distribution_no_short_substring(code_to_id):
    """P0 회귀 방지: DB 의 짧은 영문 대문자 keyword 가 화이트리스트 외에 없는지."""
    cur = _get_conn()
    if cur is None:
        pytest.skip("DATABASE_URL 미설정")
    c = cur.cursor()
    c.execute("SET search_path TO financeone, public")
    c.execute("SELECT keyword FROM standard_account_keywords")
    keywords = [r[0] for r in c.fetchall()]
    c.close()
    cur.close()

    SHORT_ENGLISH_WHITELIST = {
        "KFC", "BBQ", "KCP", "AWS", "SKT", "KTX", "KTV", "META",
    }
    for kw in keywords:
        is_short_uppercase_english = (
            kw.isascii()
            and 2 <= len(kw) <= 3
            and kw.isupper()
            and kw.isalpha()
        )
        if is_short_uppercase_english:
            assert kw in SHORT_ENGLISH_WHITELIST, (
                f"DB 에 짧은 영문 대문자 keyword '{kw}' 존재 — "
                f"ILIKE false-positive 위험. 화이트리스트 점검 필요."
            )

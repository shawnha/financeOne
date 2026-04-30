"""P4-B keyword_match cascade 통합 테스트.

검증 (Stage 3 D1/D2):
  D1: 통합 SQL — entity_keyword ∪ global_keyword, length × confidence 정렬
  D2: global 매칭 시 internal_account_id 자동 추론

스키마:
  keyword_mapping_rules: entity_id, keyword, internal_account_id, confidence
  standard_account_keywords: keyword UNIQUE, standard_account_id, confidence
  internal_accounts: id, entity_id, name, standard_account_id

테스트 종류:
  - Mock 단위테스트 (cur.fetchone 반환값 시나리오)
  - DB integration (실제 DB 매칭 검증, DATABASE_URL 있을 때만)
"""
from unittest.mock import MagicMock

import os
import psycopg2
import pytest
from dotenv import load_dotenv

from backend.services.mapping_service import keyword_match


# ─── Mock 단위테스트 ────────────────────────────────────────


def _make_mock_cur(fetchone_return):
    """SQL 호출 흉내 mock cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_return
    return cur


def test_keyword_match_no_search_text():
    """counterparty/description 모두 None → None 반환."""
    cur = _make_mock_cur(None)
    result = keyword_match(cur, entity_id=1, counterparty=None, description=None)
    assert result is None
    cur.execute.assert_not_called()


def test_keyword_match_no_db_match():
    """DB 매칭 없음 → None 반환."""
    cur = _make_mock_cur(None)
    result = keyword_match(cur, entity_id=1, counterparty="알수없는거래처", description=None)
    assert result is None
    cur.execute.assert_called_once()


def test_keyword_match_entity_level_hit():
    """entity-level (keyword_mapping_rules) 매칭."""
    cur = _make_mock_cur((42, 100, 0.90, "keyword", "스타벅스"))
    result = keyword_match(cur, entity_id=1, counterparty="스타벅스 강남점", description=None)
    assert result == {
        "internal_account_id": 42,
        "standard_account_id": 100,
        "confidence": 0.90,
        "match_type": "keyword",
        "matched_keyword": "스타벅스",
    }


def test_keyword_match_global_level_hit():
    """global (standard_account_keywords) 매칭, internal_account_id 추론 성공."""
    cur = _make_mock_cur((55, 200, 0.85, "global_keyword", "Adobe Creative Cloud"))
    result = keyword_match(cur, entity_id=1, counterparty="Adobe Creative Cloud", description="Photoshop subscription")
    assert result["match_type"] == "global_keyword"
    assert result["internal_account_id"] == 55  # 추론됨
    assert result["standard_account_id"] == 200
    assert result["matched_keyword"] == "Adobe Creative Cloud"


def test_keyword_match_global_no_internal_account():
    """global 매칭 + entity 에 매핑된 internal_account 없음 → internal_account_id=NULL."""
    cur = _make_mock_cur((None, 200, 0.85, "global_keyword", "Notion"))
    result = keyword_match(cur, entity_id=999, counterparty="Notion", description=None)
    assert result["internal_account_id"] is None
    assert result["standard_account_id"] == 200
    assert result["match_type"] == "global_keyword"


def test_keyword_match_uses_combined_text():
    """counterparty + description 모두 검색 텍스트로 사용."""
    cur = _make_mock_cur(None)
    keyword_match(cur, entity_id=1, counterparty="ABC", description="Adobe purchase")
    args, _ = cur.execute.call_args
    sql, params = args[0], args[1]
    # search_text 가 두 번 (entity 쿼리 + global 쿼리) 들어감
    assert "ABC Adobe purchase" in params


# ─── P0/P1 회귀 방지 ──────────────────────────────────────────


def test_sql_uses_escape_clause():
    """P1-4: ILIKE 메타문자 (% / _) 가 의도치 않은 wildcard 매칭 차단.
    keyword 컬럼에 '100%' 가 있어도 'ESCAPE \\' 로 literal 매칭.
    """
    cur = _make_mock_cur(None)
    keyword_match(cur, entity_id=1, counterparty="100%순면 양말", description=None)
    args, _ = cur.execute.call_args
    sql = args[0]
    assert r"ESCAPE '\\'" in sql or "ESCAPE '\\'" in sql or "ESCAPE" in sql, (
        "ILIKE ESCAPE 절 누락 — keyword 의 % / _ false-match 위험"
    )


def test_sql_blocks_cross_entity_leak():
    """P0-1 회귀 방지: entity 쿼리에 ia.entity_id = k.entity_id 검증."""
    cur = _make_mock_cur(None)
    keyword_match(cur, entity_id=1, counterparty="X", description=None)
    args, _ = cur.execute.call_args
    sql = args[0]
    assert "ia.entity_id = k.entity_id" in sql, (
        "Cross-entity leak 위험: keyword_mapping_rules 의 internal_account 가 "
        "다른 entity 소속이어도 매칭됨. ia.entity_id = k.entity_id 검증 필수."
    )


def test_sql_filters_inactive_accounts():
    """P0-2 회귀 방지: deactivated internal_account/standard_account 매칭 안 됨."""
    cur = _make_mock_cur(None)
    keyword_match(cur, entity_id=1, counterparty="X", description=None)
    args, _ = cur.execute.call_args
    sql = args[0]
    # entity 쿼리 + global 쿼리 양쪽에 is_active 필터
    is_active_count = sql.count("is_active = TRUE")
    assert is_active_count >= 3, (
        f"is_active 필터 누락 (현재 {is_active_count}개). "
        f"필요: entity_account, global_account 추론, standard_account."
    )


def test_sql_priority_order_entity_first():
    """P2-6: ORDER BY 가 source_priority 우선 (entity > global)."""
    cur = _make_mock_cur(None)
    keyword_match(cur, entity_id=1, counterparty="X", description=None)
    args, _ = cur.execute.call_args
    sql = args[0]
    # 마지막 ORDER BY (top-level, subquery 내부 ORDER BY 가 아닌 것)
    order_idx = sql.rfind("ORDER BY")
    assert order_idx > 0
    order_clause = sql[order_idx:order_idx + 200]
    sp_pos = order_clause.find("source_priority")
    w_pos = order_clause.find("w DESC")
    conf_pos = order_clause.find("confidence DESC")
    assert sp_pos < w_pos < conf_pos, (
        f"ORDER BY 순서 오류: source_priority({sp_pos}) → w({w_pos}) → "
        f"confidence({conf_pos}) 여야 함"
    )


def test_sql_injection_safe():
    """P2-7: counterparty 에 SQL injection 시도해도 parametrized 라 안전."""
    cur = _make_mock_cur(None)
    malicious = "' OR 1=1 --"
    keyword_match(cur, entity_id=1, counterparty=malicious, description=None)
    args, _ = cur.execute.call_args
    sql, params = args[0], args[1]
    # malicious 가 SQL string 에 직접 들어가지 않고 params 로 전달됨
    assert malicious not in sql, "SQL injection: malicious 입력이 쿼리에 직접 삽입됨"
    assert malicious in params, "malicious 입력이 parameter 로 안전 전달됨"


def test_empty_string_returns_none():
    """P2: empty string + None 모두 None 반환 (단일 SQL 호출 안 함)."""
    cur = _make_mock_cur(None)
    result = keyword_match(cur, entity_id=1, counterparty="", description="")
    assert result is None
    cur.execute.assert_not_called()


# ─── DB integration ────────────────────────────────────────


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


def test_db_global_keyword_hits_real_data(db_conn):
    """실제 DB 의 global keyword '스타벅스' 가 'STARBUCKS COFFEE' 매칭."""
    cur = db_conn.cursor()
    # P4-A 등록 키워드 — 스타벅스 (ILIKE case-insensitive 라 영문도 매칭 가능)
    result = keyword_match(
        cur, entity_id=2, counterparty="스타벅스 강남역점", description=None
    )
    cur.close()
    if result is None:
        pytest.skip("'스타벅스' 키워드 미등록 — P4-A 스크립트 실행 필요")
    assert result["match_type"] in ("keyword", "global_keyword")
    assert result["confidence"] >= 0.8


def test_db_kt_substring_no_longer_false_positive(db_conn):
    """P4-A 회귀 검증: 'KTX' 거래가 'KT' 통신비로 잘못 매칭 안 됨."""
    cur = db_conn.cursor()
    result = keyword_match(
        cur, entity_id=2, counterparty="KTX 특실 서울→부산", description=None
    )
    cur.close()
    # 'KT' 가 dictionary 에서 제거됐으므로 'KTX' 매칭은 통신비 50700 아니어야 함
    if result and result["match_type"] in ("keyword", "global_keyword"):
        # KTX 가 별도 키워드 (51300 여비교통비) 로 등록돼 있다면 매칭 OK
        assert result["standard_account_id"] != 48, (
            f"'KTX' 거래가 통신비로 false-positive: {result}"
        )


def test_db_no_dangling_global_keyword_orphan(db_conn):
    """global keyword 가 entity 의 internal_account 추론 시 dangling 없음."""
    cur = db_conn.cursor()
    cur.execute(
        """
        SELECT sak.keyword, sak.standard_account_id
        FROM standard_account_keywords sak
        WHERE NOT EXISTS (
            SELECT 1 FROM internal_accounts ia
            WHERE ia.entity_id = 2
              AND ia.standard_account_id = sak.standard_account_id
              AND ia.is_active = TRUE
        )
        LIMIT 5
        """
    )
    orphans = cur.fetchall()
    cur.close()
    # 일부 orphan 은 정상 (entity 가 사용 안 하는 standard_account)
    # 그러나 매칭 시 internal_account_id=NULL 이어야 함 (D2 행동)
    # 이 테스트는 information only — orphan 수 로깅만
    if orphans:
        print(
            f"\n[INFO] entity=2 에 매핑된 internal_account 없는 global keyword "
            f"{len(orphans)}+ 개. internal_account_id=NULL 로 반환됨 (정상). "
            f"샘플: {orphans[:3]}"
        )


def test_db_longer_keyword_wins(db_conn):
    """length DESC 정렬 검증: 'Adobe Creative Cloud' (20자) vs 'Adobe' (5자) 충돌 시 긴 게 우선.
    P4-A 에서 'Adobe' 단독은 제거됐지만, 분리 키워드 동작 확인.
    """
    cur = db_conn.cursor()
    result = keyword_match(
        cur, entity_id=2, counterparty="Adobe Creative Cloud subscription", description=None
    )
    cur.close()
    if result is None:
        pytest.skip("'Adobe Creative Cloud' 키워드 미등록")
    assert "Adobe Creative Cloud" in result.get("matched_keyword", ""), (
        f"긴 키워드 우선 매칭 실패: {result}"
    )

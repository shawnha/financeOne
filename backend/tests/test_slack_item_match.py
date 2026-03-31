"""다중 항목 개별 매칭 API 테스트"""

import pytest
from unittest.mock import MagicMock, patch


def make_mock_cursor(rows=None, fetchone_val=None):
    """테스트용 mock cursor 생성"""
    cur = MagicMock()
    if rows is not None:
        cur.fetchall.return_value = rows
    if fetchone_val is not None:
        cur.fetchone.return_value = fetchone_val
    cur.description = []
    return cur


class TestGetCandidatesItemIndex:
    """GET /api/slack/messages/{id}/candidates?item_index=N 테스트"""

    def test_item_index_extracts_single_item_amount(self):
        """item_index 지정 시 해당 항목 금액만으로 검색해야 함"""
        from backend.routers.slack import _build_search_amounts

        structured = {
            "total_amount": 1811250,
            "items": [
                {"description": "설치", "amount": 1350000, "currency": "KRW"},
                {"description": "제거", "amount": 400000, "currency": "KRW"},
                {"description": "수수료", "amount": 61250, "currency": "KRW"},
            ],
            "vendor": "현수막업체",
        }

        # item_index=0 → 설치 1,350,000만
        amounts = _build_search_amounts(structured, parsed_amount=None, item_index=0)
        assert len(amounts) == 1
        assert amounts[0]["amount"] == 1350000
        assert amounts[0]["label"] == "설치"

    def test_item_index_none_uses_all_amounts(self):
        """item_index 미지정 시 total + 모든 items 금액 사용 (기존 동작)"""
        from backend.routers.slack import _build_search_amounts

        structured = {
            "total_amount": 1811250,
            "items": [
                {"description": "설치", "amount": 1350000, "currency": "KRW"},
                {"description": "제거", "amount": 400000, "currency": "KRW"},
            ],
        }

        amounts = _build_search_amounts(structured, parsed_amount=None, item_index=None)
        assert len(amounts) == 3  # total + 2 items
        assert amounts[0]["amount"] == 1811250

    def test_item_index_out_of_range(self):
        """item_index가 범위 밖이면 빈 목록 반환"""
        from backend.routers.slack import _build_search_amounts

        structured = {
            "total_amount": 100000,
            "items": [{"description": "A", "amount": 100000, "currency": "KRW"}],
        }

        amounts = _build_search_amounts(structured, parsed_amount=None, item_index=5)
        assert len(amounts) == 0

    def test_no_structured_data_fallback(self):
        """structured 없으면 parsed_amount fallback"""
        from backend.routers.slack import _build_search_amounts

        amounts = _build_search_amounts({}, parsed_amount=50000, item_index=None)
        assert len(amounts) == 1
        assert amounts[0]["amount"] == 50000


class TestConfirmItemMatch:
    """POST /api/slack/messages/{id}/confirm with item_index 테스트"""

    def test_confirm_body_accepts_item_fields(self):
        """ConfirmMatch 모델이 item_index, item_description 필드 허용"""
        from backend.routers.slack import ConfirmMatch

        body = ConfirmMatch(
            transaction_id=100,
            item_index=0,
            item_description="설치",
        )
        assert body.item_index == 0
        assert body.item_description == "설치"

    def test_confirm_body_item_fields_optional(self):
        """기존 동작: item_index 미지정 시 None"""
        from backend.routers.slack import ConfirmMatch

        body = ConfirmMatch(transaction_id=100)
        assert body.item_index is None
        assert body.item_description is None


class TestBuildItemMatches:
    """item_matches 응답 빌드 로직 테스트"""

    def test_builds_item_matches_for_multi_item(self):
        """items ≥ 2인 메시지에 item_matches 배열 생성"""
        from backend.routers.slack import _build_item_matches

        parsed_structured = {
            "items": [
                {"description": "설치", "amount": 1350000, "currency": "KRW"},
                {"description": "제거", "amount": 400000, "currency": "KRW"},
            ],
        }
        match_rows = [
            {"item_index": 0, "item_description": "설치", "transaction_id": 6001, "is_confirmed": True},
        ]

        result = _build_item_matches(parsed_structured, match_rows)
        assert result["match_progress"]["total_items"] == 2
        assert result["match_progress"]["matched_items"] == 1
        assert len(result["item_matches"]) == 2
        assert result["item_matches"][0]["is_confirmed"] is True
        assert result["item_matches"][1]["is_confirmed"] is False

    def test_returns_none_for_single_item(self):
        """items < 2이면 None 반환"""
        from backend.routers.slack import _build_item_matches

        parsed_structured = {
            "items": [{"description": "A", "amount": 100000, "currency": "KRW"}],
        }
        result = _build_item_matches(parsed_structured, [])
        assert result is None

    def test_returns_none_for_no_structured(self):
        """structured 없으면 None 반환"""
        from backend.routers.slack import _build_item_matches

        result = _build_item_matches(None, [])
        assert result is None


class TestUndoItemMatch:
    """DELETE /api/slack/messages/{id}/match/{item_index} 테스트"""

    def test_undo_endpoint_exists(self):
        """UndoItemMatch 엔드포인트가 존재하는지 확인"""
        from backend.routers.slack import router
        routes = [r.path for r in router.routes]
        assert "/api/slack/messages/{message_id}/match/{item_index}" in routes


class TestBuildExcludedTransactions:
    """이미 매칭된 거래 제외 로직 테스트"""

    def test_excludes_confirmed_from_same_message(self):
        """같은 메시지의 다른 항목에 확정된 거래는 제외해야 함"""
        from backend.routers.slack import _get_excluded_transaction_ids

        cur = make_mock_cursor(rows=[(100,), (200,)])
        excluded = _get_excluded_transaction_ids(cur, message_id=1339)
        assert 100 in excluded
        assert 200 in excluded

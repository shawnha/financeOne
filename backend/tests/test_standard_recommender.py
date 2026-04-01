"""standard_account_recommender 테스트"""

from unittest.mock import MagicMock


class TestRecommendStandardAccount:
    def test_inherits_from_parent(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.return_value = (42,)  # parent's standard_account_id
        result = recommend_standard_account(cur, entity_id=1, account_name="점심식대", parent_id=5)
        assert result is not None
        assert result["standard_account_id"] == 42
        assert result["source"] == "parent_inherit"

    def test_parent_has_no_standard_falls_through(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (None,),    # parent has no standard_account_id
            (50, "복리후생비", 0.6),  # similar account match
        ]
        result = recommend_standard_account(cur, entity_id=1, account_name="점심식대", parent_id=5)
        assert result is not None
        assert result["source"] == "similar_account"

    def test_similar_account_match(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (50, "복리후생비", 0.7),  # similar account
        ]
        result = recommend_standard_account(cur, entity_id=1, account_name="회식비", parent_id=None)
        assert result is not None
        assert result["source"] == "similar_account"
        assert result["standard_account_id"] == 50

    def test_keyword_dict_match(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,           # no similar account
            (30, 0.85, "택시"),  # keyword dict match
        ]
        result = recommend_standard_account(cur, entity_id=1, account_name="택시비", parent_id=None)
        assert result is not None
        assert result["source"] == "keyword_dict"
        assert result["standard_account_id"] == 30

    def test_returns_none_when_no_match(self):
        from backend.services.standard_account_recommender import recommend_standard_account
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = recommend_standard_account(cur, entity_id=1, account_name="ASDFGH", parent_id=None)
        assert result is None

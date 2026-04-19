"""Codef 연동 테스트 — 정규화, env toggle, 중복감지, connected_id 저장."""

import json
import os
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.services.integrations.codef import (
    CodefClient,
    CodefError,
    ORG_CODES,
    CODEF_SANDBOX_URL,
    CODEF_PRODUCTION_URL,
    SETTINGS_PREFIX,
    _parse_codef_date,
    _parse_amount,
    _mask_card_number,
    _normalize_bank_row,
    _normalize_card_row,
    _is_duplicate,
    _parse_codef_response,
    resolve_base_url,
    is_production,
)


# ── 헬퍼: 날짜/금액/카드번호 ──────────────────────────


def test_parse_date_yyyymmdd():
    assert _parse_codef_date("20260315") == "2026-03-15"


def test_parse_date_iso_passthrough():
    assert _parse_codef_date("2026-03-15") == "2026-03-15"


def test_parse_date_invalid():
    assert _parse_codef_date("") is None
    assert _parse_codef_date("abc") is None
    assert _parse_codef_date("20261345") == "2026-13-45"  # 포맷만 체크, 날짜 유효성은 DB


def test_parse_amount_comma_string():
    assert _parse_amount("1,234,567") == Decimal("1234567")


def test_parse_amount_plain():
    assert _parse_amount("50000") == Decimal("50000")


def test_parse_amount_empty():
    assert _parse_amount("") == Decimal("0")
    assert _parse_amount(None) == Decimal("0")


def test_parse_amount_negative_abs():
    # 음수도 절대값으로
    assert _parse_amount("-1000") == Decimal("1000")


def test_mask_card_number_basic():
    assert _mask_card_number("1234567890123456") == "****3456"
    assert _mask_card_number("1234-5678-9012-3456") == "****3456"


def test_mask_card_number_short():
    assert _mask_card_number("") is None
    assert _mask_card_number("12") is None


# ── 은행 정규화 ────────────────────────────────────


def test_normalize_bank_row_incoming():
    item = {
        "resAccountTrDate": "20260315",
        "resAccountIn": "50000",
        "resAccountOut": "",
        "resAccountTrAmount": "50000",
        "resAccountDesc1": "고객ABC 입금",
        "resAccountDesc": "이체",
    }
    result = _normalize_bank_row(item)
    assert result is not None
    assert result["date"] == "2026-03-15"
    assert result["amount"] == Decimal("50000")
    assert result["type"] == "in"
    assert "고객ABC" in result["counterparty"]


def test_normalize_bank_row_outgoing():
    item = {
        "resAccountTrDate": "20260315",
        "resAccountIn": "",
        "resAccountOut": "1000000",
        "resAccountTrAmount": "1000000",
        "resAccountDesc": "월세 송금",
    }
    result = _normalize_bank_row(item)
    assert result is not None
    assert result["type"] == "out"
    assert result["amount"] == Decimal("1000000")


def test_normalize_bank_row_invalid_date():
    item = {"resAccountTrDate": "", "resAccountTrAmount": "1000"}
    assert _normalize_bank_row(item) is None


def test_normalize_bank_row_zero_amount():
    item = {"resAccountTrDate": "20260315", "resAccountTrAmount": "0"}
    assert _normalize_bank_row(item) is None


# ── 카드 정규화 ────────────────────────────────────


def test_normalize_card_row_approval():
    item = {
        "resUsedDate": "20260320",
        "resUsedAmount": "25,000",
        "resMemberStoreName": "스타벅스 서초점",
        "resCardNo": "1234-5678-9012-3456",
        "resCancelYN": "0",
        "resUserName": "홍길동",
    }
    result = _normalize_card_row(item)
    assert result is not None
    assert result["date"] == "2026-03-20"
    assert result["amount"] == Decimal("25000")
    assert result["type"] == "out"
    assert result["is_cancel"] is False
    assert result["counterparty"] == "스타벅스 서초점"
    assert result["card_number"] == "****3456"
    assert result["member_name"] == "홍길동"


def test_normalize_card_row_cancel_becomes_inflow():
    item = {
        "resUsedDate": "20260320",
        "resUsedAmount": "25,000",
        "resMemberStoreName": "스타벅스",
        "resCancelYN": "1",
    }
    result = _normalize_card_row(item)
    assert result["is_cancel"] is True
    assert result["type"] == "in"
    assert "(취소)" in result["description"]


def test_normalize_card_row_cancel_y_uppercase():
    item = {
        "resUsedDate": "20260320",
        "resUsedAmount": "10000",
        "resMemberStoreName": "가맹점",
        "resCancelYN": "Y",
    }
    assert _normalize_card_row(item)["is_cancel"] is True


def test_normalize_card_row_missing_date():
    item = {"resUsedAmount": "1000", "resMemberStoreName": "x"}
    assert _normalize_card_row(item) is None


def test_normalize_card_row_fallback_total_amount():
    # 해외결제 — resUsedAmount 0이면 resTotalAmount 사용
    item = {
        "resUsedDate": "20260320",
        "resUsedAmount": "0",
        "resTotalAmount": "12,500",
        "resMemberStoreName": "Amazon",
    }
    result = _normalize_card_row(item)
    assert result is not None
    assert result["amount"] == Decimal("12500")


# ── 환경 토글 ───────────────────────────────────────


def test_resolve_base_url_default_demo(monkeypatch):
    monkeypatch.delenv("CODEF_ENV", raising=False)
    monkeypatch.delenv("CODEF_BASE_URL", raising=False)
    assert resolve_base_url() == CODEF_SANDBOX_URL
    assert is_production() is False


def test_resolve_base_url_sandbox_alias(monkeypatch):
    # "sandbox" 구 이름도 demo로 인식해야 하지만, 현재는 production만 별도.
    # "sandbox" 는 non-production → demo로 fallback.
    monkeypatch.setenv("CODEF_ENV", "sandbox")
    monkeypatch.delenv("CODEF_BASE_URL", raising=False)
    assert resolve_base_url() == CODEF_SANDBOX_URL
    assert is_production() is False


def test_resolve_base_url_production(monkeypatch):
    monkeypatch.setenv("CODEF_ENV", "production")
    monkeypatch.delenv("CODEF_BASE_URL", raising=False)
    assert resolve_base_url() == CODEF_PRODUCTION_URL
    assert is_production() is True


def test_resolve_base_url_override(monkeypatch):
    monkeypatch.setenv("CODEF_ENV", "production")
    monkeypatch.setenv("CODEF_BASE_URL", "https://custom.codef.example.com")
    assert resolve_base_url() == "https://custom.codef.example.com"


def test_client_environment_property(monkeypatch):
    monkeypatch.delenv("CODEF_BASE_URL", raising=False)
    monkeypatch.setenv("CODEF_ENV", "demo")
    c = CodefClient("id", "sec")
    assert c.environment == "demo"
    c.close()

    monkeypatch.setenv("CODEF_ENV", "production")
    c2 = CodefClient("id", "sec")
    assert c2.environment == "production"
    c2.close()


# ── 중복감지 ───────────────────────────────────────


def test_is_duplicate_found():
    cur = MagicMock()
    cur.fetchone.return_value = (123,)
    tx = {
        "date": "2026-03-15",
        "amount": Decimal("50000"),
        "counterparty": "스타벅스",
        "is_cancel": False,
    }
    assert _is_duplicate(cur, 1, tx, "codef_lotte_card") is True
    cur.execute.assert_called_once()


def test_is_duplicate_not_found():
    cur = MagicMock()
    cur.fetchone.return_value = None
    tx = {
        "date": "2026-03-15",
        "amount": Decimal("50000"),
        "counterparty": "스타벅스",
        "is_cancel": False,
    }
    assert _is_duplicate(cur, 1, tx, "codef_lotte_card") is False


def test_is_duplicate_cancel_separate_from_approval():
    """같은 금액·가맹점·날짜라도 is_cancel 다르면 별개 건."""
    cur = MagicMock()
    cur.fetchone.return_value = None
    tx = {
        "date": "2026-03-15",
        "amount": Decimal("50000"),
        "counterparty": "스타벅스",
        "is_cancel": True,
    }
    _is_duplicate(cur, 1, tx, "codef_lotte_card")
    # is_cancel param 전달되는지 확인
    args, _ = cur.execute.call_args
    params = args[1]
    assert True in params  # is_cancel=True 포함


# ── sync card approvals ──────────────────────────────


def test_sync_card_approvals_unknown_card_type():
    client = CodefClient("id", "sec")
    conn = MagicMock()
    with pytest.raises(CodefError, match="Unknown card type"):
        client.sync_card_approvals(conn, 1, "cid", "20260301", "20260331", "hyundai_card")
    client.close()


def test_sync_card_approvals_inserts_and_dedups():
    client = CodefClient("id", "sec")
    approvals = [
        {
            "resUsedDate": "20260301",
            "resUsedAmount": "10,000",
            "resMemberStoreName": "가맹점A",
            "resCardNo": "1234-5678-9012-3456",
            "resCancelYN": "0",
        },
        {
            "resUsedDate": "20260302",
            "resUsedAmount": "20,000",
            "resMemberStoreName": "가맹점B",
            "resCardNo": "1234-5678-9012-3456",
            "resCancelYN": "0",
        },
        # 중복 — 같은 내용
        {
            "resUsedDate": "20260301",
            "resUsedAmount": "10,000",
            "resMemberStoreName": "가맹점A",
            "resCardNo": "1234-5678-9012-3456",
            "resCancelYN": "0",
        },
        # 취소 건
        {
            "resUsedDate": "20260303",
            "resUsedAmount": "5,000",
            "resMemberStoreName": "가맹점C",
            "resCardNo": "1234-5678-9012-3456",
            "resCancelYN": "1",
        },
    ]

    with patch.object(client, "get_card_approvals", return_value=approvals):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        # 첫 세 건은 중복 아님(fetchone None), 네 번째도 취소라 별개
        # 단 세 번째(중복)만 True
        # dedup query는 INSERT 전에 호출됨 — 총 4건 중 중복 1건
        fetchone_results = [None, None, (999,), None]  # 3번째가 중복
        cur.fetchone.side_effect = fetchone_results

        result = client.sync_card_approvals(
            conn, 1, "cid", "20260301", "20260331", "lotte_card",
        )

        assert result["total_fetched"] == 4
        assert result["synced"] == 3
        assert result["duplicates"] == 1
        assert result["cancels"] == 1
        assert result["card_type"] == "lotte_card"

    client.close()


# ── connected_id settings storage ────────────────────


def test_get_connected_id_found():
    from backend.services.integrations.codef import get_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = ("cid_abc123",)

    result = get_connected_id(conn, 2, "woori_bank")
    assert result == "cid_abc123"
    args, _ = cur.execute.call_args
    assert args[1][0] == SETTINGS_PREFIX + "woori_bank"
    assert args[1][1] == 2


def test_get_connected_id_not_found():
    from backend.services.integrations.codef import get_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = None

    assert get_connected_id(conn, 2, "woori_bank") is None


def test_set_connected_id_upserts():
    from backend.services.integrations.codef import set_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    set_connected_id(conn, 2, "lotte_card", "cid_xyz")
    cur.execute.assert_called_once()
    args, _ = cur.execute.call_args
    assert "ON CONFLICT" in args[0]
    assert args[1][0] == SETTINGS_PREFIX + "lotte_card"
    assert args[1][1] == "cid_xyz"
    assert args[1][2] == 2


def test_list_connected_ids():
    from backend.services.integrations.codef import list_connected_ids
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = [
        (SETTINGS_PREFIX + "woori_bank", "cid_bank"),
        (SETTINGS_PREFIX + "lotte_card", "cid_card"),
    ]

    result = list_connected_ids(conn, 2)
    assert result == {"woori_bank": "cid_bank", "lotte_card": "cid_card"}


def test_delete_connected_id():
    from backend.services.integrations.codef import delete_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.rowcount = 1

    assert delete_connected_id(conn, 2, "woori_bank") is True


def test_delete_connected_id_missing():
    from backend.services.integrations.codef import delete_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.rowcount = 0

    assert delete_connected_id(conn, 2, "woori_bank") is False


# ── create_connected_id ──────────────────────────────


def test_create_connected_id_success():
    client = CodefClient("id", "sec")
    with patch.object(client, "_request", return_value={"connectedId": "cid_new123"}):
        result = client.create_connected_id([{"organization": "0020"}])
        assert result == "cid_new123"
    client.close()


def test_create_connected_id_missing_in_response():
    client = CodefClient("id", "sec")
    with patch.object(client, "_request", return_value={}):
        with pytest.raises(CodefError, match="No connectedId"):
            client.create_connected_id([{"organization": "0020"}])
    client.close()


# ── Codef 응답 파싱 (URL-encoded JSON) ───────────────


def test_parse_codef_response_plain_json():
    raw = '{"result":{"code":"CF-00000","message":"success"},"data":{"connectedId":"abc"}}'
    parsed = _parse_codef_response(raw)
    assert parsed["result"]["code"] == "CF-00000"
    assert parsed["data"]["connectedId"] == "abc"


def test_parse_codef_response_url_encoded():
    import urllib.parse
    original = {"result": {"code": "CF-00000"}, "data": {"connectedId": "xyz"}}
    encoded = urllib.parse.quote(json.dumps(original))
    parsed = _parse_codef_response(encoded)
    assert parsed["result"]["code"] == "CF-00000"
    assert parsed["data"]["connectedId"] == "xyz"


def test_parse_codef_response_empty():
    with pytest.raises(CodefError, match="Empty response"):
        _parse_codef_response("")


def test_parse_codef_response_garbage():
    with pytest.raises(CodefError, match="응답 파싱 실패"):
        _parse_codef_response("not json and not url-encoded either")


def test_parse_codef_response_korean_url_encoded():
    """한글 메시지 포함 — 한글이 UTF-8 URL-encoded."""
    import urllib.parse
    original = {"result": {"code": "CF-12345", "message": "로그인 정보 불일치"}}
    encoded = urllib.parse.quote(json.dumps(original, ensure_ascii=False))
    parsed = _parse_codef_response(encoded)
    assert parsed["result"]["message"] == "로그인 정보 불일치"


# ── RSA 비밀번호 암호화 ─────────────────────────────


def test_encrypt_password_requires_public_key(monkeypatch):
    from backend.services.integrations.codef import encrypt_password, CodefError
    monkeypatch.delenv("CODEF_PUBLIC_KEY", raising=False)
    with pytest.raises(CodefError, match="CODEF_PUBLIC_KEY 미설정"):
        encrypt_password("secret")


def test_encrypt_password_roundtrip(monkeypatch):
    """생성한 키쌍으로 암호화 → 복호화 해서 원문 복구 검증."""
    import base64 as _b64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as _pad, rsa
    from backend.services.integrations.codef import encrypt_password

    # 테스트용 RSA 키쌍 생성
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    plain = "myS3cretP@ssw0rd!"
    ciphertext_b64 = encrypt_password(plain, public_key_pem=public_pem)

    # base64 디코드 후 개인키로 복호화
    ciphertext = _b64.b64decode(ciphertext_b64)
    recovered = private_key.decrypt(ciphertext, _pad.PKCS1v15()).decode("utf-8")
    assert recovered == plain


def test_encrypt_password_accepts_raw_base64_key(monkeypatch):
    """Codef 포털에서 헤더 없이 복사된 공개키(raw base64)도 정규화해서 처리."""
    import base64 as _b64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding as _pad, rsa
    from backend.services.integrations.codef import encrypt_password

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    # PEM 헤더 제거하고 raw base64만 추출
    raw_b64 = "".join(
        line for line in public_pem.splitlines() if not line.startswith("-----")
    )

    plain = "pw123"
    ciphertext_b64 = encrypt_password(plain, public_key_pem=raw_b64)
    ciphertext = _b64.b64decode(ciphertext_b64)
    recovered = private_key.decrypt(ciphertext, _pad.PKCS1v15()).decode("utf-8")
    assert recovered == plain


def test_encrypt_password_invalid_key():
    from backend.services.integrations.codef import encrypt_password, CodefError
    with pytest.raises(CodefError, match="공개키 처리 실패"):
        encrypt_password("secret", public_key_pem="not-a-real-key")


# ── ORG_CODES 완전성 ─────────────────────────────────


def test_org_codes_covers_all_supported_orgs():
    assert "woori_bank" in ORG_CODES
    assert "lotte_card" in ORG_CODES
    assert "woori_card" in ORG_CODES
    assert "shinhan_card" in ORG_CODES
    # 기관 코드는 4자리 숫자 문자열
    for code in ORG_CODES.values():
        assert len(code) == 4
        assert code.isdigit()

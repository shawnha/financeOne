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
        "resAccountOut": "0",
        "resAccountDesc2": "이체",
        "resAccountDesc3": "고객ABC",
    }
    result = _normalize_bank_row(item)
    assert result is not None
    assert result["date"] == "2026-03-15"
    assert result["amount"] == Decimal("50000")
    assert result["type"] == "in"
    assert result["counterparty"] == "고객ABC"
    assert "이체" in result["description"]


def test_normalize_bank_row_outgoing():
    item = {
        "resAccountTrDate": "20260315",
        "resAccountIn": "0",
        "resAccountOut": "1000000",
        "resAccountDesc2": "인터넷",
        "resAccountDesc3": "월세 송금",
        "resAccountDesc4": "강남지점",
    }
    result = _normalize_bank_row(item)
    assert result is not None
    assert result["type"] == "out"
    assert result["amount"] == Decimal("1000000")
    assert result["counterparty"] == "월세 송금"
    assert result["memo"] == "인터넷"
    assert result["branch"] == "강남지점"


def test_normalize_bank_row_with_balance():
    item = {
        "resAccountTrDate": "20260315",
        "resAccountIn": "0",
        "resAccountOut": "5000",
        "resAccountDesc3": "test",
        "resAfterTranBalance": "12345678",
    }
    result = _normalize_bank_row(item)
    assert result["balance_after"] == 12345678.0


def test_normalize_bank_row_invalid_date():
    item = {"resAccountTrDate": "", "resAccountIn": "1000"}
    assert _normalize_bank_row(item) is None


def test_normalize_bank_row_both_zero():
    item = {"resAccountTrDate": "20260315", "resAccountIn": "0", "resAccountOut": "0"}
    assert _normalize_bank_row(item) is None


def test_normalize_bank_row_check_card_memo():
    item = {
        "resAccountTrDate": "20260315",
        "resAccountIn": "0",
        "resAccountOut": "5000",
        "resAccountDesc2": "체크우리",
        "resAccountDesc3": "스타벅스",
    }
    result = _normalize_bank_row(item)
    assert result["memo"] == "체크우리"


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
    # API 응답 카드번호는 이미 마스킹 형태 (5275********1840)이므로 그대로 보존
    assert result["card_number"] == "1234-5678-9012-3456"
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
    cur.fetchone.return_value = (123, None)  # (id, time) — time backfill 도입 후 2-tuple
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
        client.sync_card_approvals(conn, 1, "cid", "20260301", "20260331", "fake_xx_card")
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

    # 새 sync_card_approvals: get_card_list 1회 + 카드별 get_card_approvals
    fake_cards = [{"resCardNo": "1234********3456", "resCardName": "TEST"}]
    with patch.object(client, "get_card_list", return_value=fake_cards), \
         patch.object(client, "get_card_approvals", return_value=approvals), \
         patch("backend.services.mapping_service.auto_map_transaction", return_value=None):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        # sync_card_approvals 동작 (각 row별):
        #   1) _is_duplicate (fetchone, (id,time) 2-tuple 또는 None) — None=신규
        #   2) member 매칭: 이름 없음 → 카드번호 exact(fetchone) → 실패 시 뒤3자리 tail3(fetchone)
        # 신규 row fetchone: dedup(1) + exact(1) + tail3(1) = 3 (둘 다 None)
        # 중복 row: dedup hit 에서 멈춤 → fetchone 1회
        # 4 rows: row1(신규)=3, row2(신규)=3, row3(중복)=1, row4(신규)=3 → 10
        fetchone_results = [
            None, None, None,   # row 1: dedup None, member exact None, tail3 None
            None, None, None,   # row 2
            (999, None),        # row 3: dedup hit (id,time) → 즉시 continue
            None, None, None,   # row 4
        ]
        cur.fetchone.side_effect = fetchone_results

        result = client.sync_card_approvals(
            conn, 1, "cid", "20260301", "20260331", "lotte_card",
        )

        assert result["total_fetched"] == 4
        assert result["synced"] == 3
        assert result["duplicates"] == 1
        assert result["cancels"] == 1
        assert result["card_type"] == "lotte_card"
        assert result["auto_mapped"] == 0  # 매핑 mock None

    client.close()


# ── connected_id settings storage ────────────────────


def test_get_connected_id_found():
    from backend.services.integrations.codef import get_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = ("cid_abc123",)

    # explicit env 로 호출 → env-scoped 키 조회
    result = get_connected_id(conn, 2, "woori_bank", env="demo")
    assert result == "cid_abc123"
    args, _ = cur.execute.call_args
    assert args[1][0] == "codef_connected_id_demo_woori_bank"
    assert args[1][1] == 2


def test_get_connected_id_legacy_fallback_demo():
    """demo 모드에서 env-scoped 키 없으면 legacy unscoped 키로 fallback."""
    from backend.services.integrations.codef import get_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    # 첫 호출 (env-scoped) None, 두 번째 호출 (legacy) 값 반환
    cur.fetchone.side_effect = [None, ("cid_legacy",)]

    result = get_connected_id(conn, 2, "woori_bank", env="demo")
    assert result == "cid_legacy"
    # 마지막 execute 는 legacy SETTINGS_PREFIX 키여야 함
    args, _ = cur.execute.call_args
    assert args[1][0] == SETTINGS_PREFIX + "woori_bank"


def test_get_connected_id_production_no_legacy_fallback():
    """production 모드에서는 legacy 키로 fallback 하지 않음 (격리)."""
    from backend.services.integrations.codef import get_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = None

    assert get_connected_id(conn, 2, "woori_bank", env="production") is None


def test_get_connected_id_not_found():
    from backend.services.integrations.codef import get_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = None

    assert get_connected_id(conn, 2, "woori_bank", env="demo") is None


def test_set_connected_id_upserts():
    from backend.services.integrations.codef import set_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    set_connected_id(conn, 2, "lotte_card", "cid_xyz", env="demo")
    cur.execute.assert_called_once()
    args, _ = cur.execute.call_args
    assert "ON CONFLICT" in args[0]
    assert args[1][0] == "codef_connected_id_demo_lotte_card"
    assert args[1][1] == "cid_xyz"
    assert args[1][2] == 2


def test_set_connected_id_production_separate():
    """production env 는 별도 키로 저장 → demo connected_id 와 격리."""
    from backend.services.integrations.codef import set_connected_id
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    set_connected_id(conn, 2, "lotte_card", "cid_prod", env="production")
    args, _ = cur.execute.call_args
    assert args[1][0] == "codef_connected_id_production_lotte_card"


def test_list_connected_ids():
    from backend.services.integrations.codef import list_connected_ids
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    # demo 모드는 두 번 query (env-scoped + legacy fallback)
    cur.fetchall.side_effect = [
        [
            ("codef_connected_id_demo_woori_bank", "cid_bank"),
            ("codef_connected_id_demo_lotte_card", "cid_card"),
        ],
        [],  # legacy unscoped 비어있음
    ]

    result = list_connected_ids(conn, 2, env="demo")
    assert result == {"woori_bank": "cid_bank", "lotte_card": "cid_card"}


def test_list_connected_ids_includes_legacy_in_demo():
    """demo 모드에서 legacy unscoped 키도 함께 노출 (마이그레이션 호환)."""
    from backend.services.integrations.codef import list_connected_ids
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.side_effect = [
        [("codef_connected_id_demo_woori_bank", "cid_new")],
        [(SETTINGS_PREFIX + "ibk_bank", "cid_legacy")],  # 옛 unscoped 데이터
    ]

    result = list_connected_ids(conn, 2, env="demo")
    assert result == {"woori_bank": "cid_new", "ibk_bank": "cid_legacy"}


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
    assert "hometax" in ORG_CODES  # 국세청 (P2 세금계산서 sync)
    assert ORG_CODES["hometax"] == "0001"
    # 기관 코드는 4자리 숫자 문자열
    for code in ORG_CODES.values():
        assert len(code) == 4
        assert code.isdigit()


# ── 홈택스 세금계산서 정규화 ─────────────────────────


class TestNormalizeTaxInvoiceRow:
    """Codef 홈택스 전자세금계산서 응답 → invoices 컬럼 매핑."""

    def test_sales_when_our_biz_is_seller(self):
        from backend.services.integrations.codef import _normalize_tax_invoice_row
        row = {
            "resIssueDate": "20260415",
            "resApprovalNo": "DOC123",
            "resInvoicerRegNum": "999-88-77777",  # 우리 = 공급자
            "resInvoicerName": "한아원코리아",
            "resTrusteeRegNum": "555-44-33333",
            "resTrusteeName": "고객A",
            "resSupplyAmount": "100000",
            "resTaxAmount": "10000",
            "resTotalAmount": "110000",
            "resItemName": "컨설팅",
        }
        result = _normalize_tax_invoice_row(row, our_biz_no="999-88-77777")
        assert result is not None
        assert result["direction"] == "sales"
        assert result["counterparty"] == "고객A"
        assert result["counterparty_biz_no"] == "5554433333"
        assert result["amount"] == 100000.0
        assert result["vat"] == 10000.0
        assert result["total"] == 110000.0
        assert result["document_no"] == "DOC123"

    def test_purchase_when_our_biz_is_buyer(self):
        from backend.services.integrations.codef import _normalize_tax_invoice_row
        row = {
            "resIssueDate": "20260420",
            "resInvoicerRegNum": "111-22-33333",  # 공급자 = 외부
            "resInvoicerName": "공급사B",
            "resTrusteeRegNum": "999-88-77777",  # 우리 = 공급받는자
            "resSupplyAmount": "60000",
            "resTaxAmount": "6000",
        }
        result = _normalize_tax_invoice_row(row, our_biz_no="999-88-77777")
        assert result["direction"] == "purchase"
        assert result["counterparty"] == "공급사B"
        assert result["total"] == 66000.0  # amount + vat 자동

    def test_unknown_when_no_match(self):
        from backend.services.integrations.codef import _normalize_tax_invoice_row
        row = {
            "resIssueDate": "20260420",
            "resInvoicerRegNum": "111-11-11111",
            "resTrusteeRegNum": "222-22-22222",
            "resSupplyAmount": "50000",
        }
        result = _normalize_tax_invoice_row(row, our_biz_no="999-99-99999")
        assert result["direction"] == "unknown"

    def test_returns_none_without_issue_date(self):
        from backend.services.integrations.codef import _normalize_tax_invoice_row
        row = {"resInvoicerRegNum": "x", "resSupplyAmount": "100"}
        assert _normalize_tax_invoice_row(row, our_biz_no="x") is None

    def test_returns_none_when_amount_zero(self):
        from backend.services.integrations.codef import _normalize_tax_invoice_row
        row = {"resIssueDate": "20260415", "resSupplyAmount": "0", "resTotalAmount": "0"}
        assert _normalize_tax_invoice_row(row) is None


def test_public_orgs_includes_hometax():
    """scheduler 분기에서 PUBLIC_ORGS 처리에 hometax 가 들어있어야 함."""
    from backend.services.integrations.codef import PUBLIC_ORGS, BANK_ORGS, CARD_ORGS
    assert "hometax" in PUBLIC_ORGS
    # 다른 그룹과 겹치지 않아야 (분기 모호성 방지)
    assert PUBLIC_ORGS.isdisjoint(BANK_ORGS)
    assert PUBLIC_ORGS.isdisjoint(CARD_ORGS)


def test_scheduler_sync_one_sync_handles_hometax():
    """scheduler._sync_one_sync 가 hometax org 분기를 가지고 있어야."""
    import inspect
    from backend.services import scheduler
    src = inspect.getsource(scheduler._sync_one_sync)
    assert "PUBLIC_ORGS" in src
    assert "sync_tax_invoices" in src
    assert "business_number" in src  # entity 자동 조회


# ── 경로 B: 목록 API 없이 번호 직접공급 ────────────────


def test_sync_card_approvals_with_card_numbers_skips_card_list():
    """card_numbers 공급 시 get_card_list 를 호출하지 않아야 (목록 상품 미신청 대응)."""
    client = CodefClient("id", "sec")
    approvals = [
        {
            "resUsedDate": "20260301",
            "resUsedAmount": "10,000",
            "resMemberStoreName": "가맹점A",
            "resCardNo": "5105*********059",
            "resCancelYN": "0",
        },
    ]

    def _boom(*a, **k):
        raise AssertionError("get_card_list 가 호출되면 안 됨 (card_numbers 공급됨)")

    with patch.object(client, "get_card_list", side_effect=_boom), \
         patch.object(client, "get_card_approvals", return_value=approvals), \
         patch("backend.services.mapping_service.auto_map_transaction", return_value=None):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = None  # dedup/member 모두 미스 (호출 횟수 무관)

        result = client.sync_card_approvals(
            conn, 1, "cid", "20260301", "20260331", "lotte_card",
            card_numbers=["5105*********059"],
        )
        assert result["synced"] == 1
        assert result["total_fetched"] == 1
    client.close()


def test_sync_card_approvals_empty_card_numbers_falls_back_to_list():
    """card_numbers=None 이면 기존대로 card-list 자동발견 (하위호환)."""
    client = CodefClient("id", "sec")
    with patch.object(client, "get_card_list", return_value=[]) as m_list:
        conn = MagicMock()
        with pytest.raises(CodefError, match="보유 카드 없음"):
            client.sync_card_approvals(
                conn, 1, "cid", "20260301", "20260331", "lotte_card",
                card_numbers=None,
            )
        m_list.assert_called_once()
    client.close()


def test_resolve_codef_card_numbers_override_wins():
    from backend.services.integrations.codef import resolve_codef_card_numbers
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    with patch("backend.services.integrations.codef.get_active_env", return_value="production"):
        # override 설정 존재 → transactions 조회 안 함
        cur.fetchone.return_value = ('["5105*********059", "5105*********114"]',)
        nums = resolve_codef_card_numbers(conn, 2, "lotte_card")
    assert nums == ["5105*********059", "5105*********114"]


def test_resolve_codef_card_numbers_from_transactions():
    from backend.services.integrations.codef import resolve_codef_card_numbers
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    with patch("backend.services.integrations.codef.get_active_env", return_value="production"):
        # override 없음(None) → distinct transactions.card_number
        cur.fetchone.return_value = None
        cur.fetchall.return_value = [("5275********1840",), ("5339********5646",)]
        nums = resolve_codef_card_numbers(conn, 2, "woori_card")
    assert nums == ["5275********1840", "5339********5646"]


def test_resolve_codef_card_numbers_none_when_empty():
    from backend.services.integrations.codef import resolve_codef_card_numbers
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    with patch("backend.services.integrations.codef.get_active_env", return_value="production"):
        cur.fetchone.return_value = None       # override 없음
        cur.fetchall.return_value = []         # 거래도 없음
        nums = resolve_codef_card_numbers(conn, 99, "lotte_card")
    assert nums is None


def test_get_codef_account_digits_only_roundtrip():
    from backend.services.integrations.codef import set_codef_account, get_codef_account
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    captured = {}

    def _exec(sql, params):
        if "INSERT" in sql:
            captured["value"] = params[1]
    cur.execute.side_effect = _exec
    with patch("backend.services.integrations.codef.get_active_env", return_value="production"):
        set_codef_account(conn, 2, "woori_bank", "1002-345-678901")
    # 하이픈 제거된 digits-only 로 저장
    assert captured["value"] == "1002345678901"


def test_get_codef_account_none_when_blank():
    from backend.services.integrations.codef import get_codef_account
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = ("   ",)  # 공백만 → None
    with patch("backend.services.integrations.codef.get_active_env", return_value="production"):
        assert get_codef_account(conn, 2, "woori_bank") is None


def test_codef_account_card_keys_env_scoped():
    from backend.services.integrations.codef import _codef_account_key, _codef_cards_key
    assert _codef_account_key("production", "woori_bank") == "codef_account_production_woori_bank"
    assert _codef_cards_key("demo", "lotte_card") == "codef_cards_demo_lotte_card"

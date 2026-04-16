"""QuickBooks Online 연동 테스트 — OAuth, sync, seed"""

import pytest
from unittest.mock import MagicMock, patch
from backend.services.integrations.qbo import (
    QBOClient,
    QBOError,
    _normalize_payee,
    _normalize_qbo_account_type,
    generate_csrf_state,
    validate_csrf_state,
)


# ── Payee normalization ──────────────────────────────────────


def test_normalize_payee_basic():
    assert _normalize_payee("ANTHROPIC INC.") == "anthropic"
    assert _normalize_payee("Amazon Web Services LLC") == "amazon web services"
    assert _normalize_payee("  Google  Corp  ") == "google"


def test_normalize_payee_empty():
    assert _normalize_payee("") == ""
    assert _normalize_payee("Inc") == ""


def test_normalize_payee_special_chars():
    assert _normalize_payee("AT&T Inc.") == "at t"
    assert _normalize_payee("McDonald's Corp") == "mcdonald s"


# ── QBO account type normalization ───────────────────────────


def test_normalize_qbo_account_type_exact():
    assert _normalize_qbo_account_type("Expense", "AdvertisingPromotional") == "Advertising Expense"
    assert _normalize_qbo_account_type("Bank", None) == "Cash and Cash Equivalents"
    assert _normalize_qbo_account_type("Income", None) == "Revenue"


def test_normalize_qbo_account_type_fallback():
    # Unknown sub_type falls back to category-level
    result = _normalize_qbo_account_type("Expense", "SomethingUnknown")
    assert result == "Professional Fees"  # Expense category fallback


def test_normalize_qbo_account_type_unknown():
    assert _normalize_qbo_account_type("UnknownType", None) is None


# ── CSRF state ───────────────────────────────────────────────


def test_generate_csrf_state():
    state = generate_csrf_state(1)
    assert state.startswith("1:")
    assert len(state) > 5


def test_validate_csrf_state_valid():
    state = generate_csrf_state(1)
    valid, entity_id = validate_csrf_state(state, state)
    assert valid is True
    assert entity_id == 1


def test_validate_csrf_state_mismatch():
    state1 = generate_csrf_state(1)
    state2 = generate_csrf_state(1)
    valid, _ = validate_csrf_state(state1, state2)
    assert valid is False


def test_validate_csrf_state_empty():
    valid, _ = validate_csrf_state("", "something")
    assert valid is False


# ── OAuth ────────────────────────────────────────────────────


def test_get_auth_url():
    client = QBOClient("test_id", "test_secret", "http://localhost:8000/callback")
    url = client.get_auth_url("1:abc123")
    assert "appcenter.intuit.com/connect/oauth2" in url
    assert "client_id=test_id" in url
    assert "state=1%3Aabc123" in url
    assert "com.intuit.quickbooks.accounting" in url
    client.close()


def test_exchange_code_success():
    client = QBOClient("test_id", "test_secret", "http://localhost:8000/callback")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "at_123",
        "refresh_token": "rt_456",
        "expires_in": 3600,
    }
    client.client = MagicMock()
    client.client.post.return_value = mock_resp

    result = client.exchange_code("code123", "realm789")
    assert result["access_token"] == "at_123"
    assert result["refresh_token"] == "rt_456"
    assert result["realm_id"] == "realm789"


def test_exchange_code_failure():
    client = QBOClient("test_id", "test_secret", "http://localhost:8000/callback")
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Bad request"
    client.client = MagicMock()
    client.client.post.return_value = mock_resp

    with pytest.raises(QBOError, match="Token exchange failed"):
        client.exchange_code("bad_code", "realm789")


# ── Line extraction ──────────────────────────────────────────


def test_extract_lines_purchase():
    client = QBOClient("id", "secret", "http://localhost/cb")
    item = {
        "Id": "123",
        "TxnDate": "2026-03-15",
        "EntityRef": {"name": "Anthropic"},
        "Line": [
            {
                "Amount": 100.0,
                "Description": "Claude API",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"name": "Professional Fees", "value": "42"},
                },
            },
            {
                "Amount": 50.0,
                "Description": "Storage",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"name": "Cloud Services", "value": "43"},
                },
            },
        ],
    }
    lines = client._extract_lines(item, "Purchase")
    assert len(lines) == 2
    assert lines[0]["payee"] == "Anthropic"
    assert lines[0]["account_name"] == "Professional Fees"
    assert lines[0]["line_number"] == 1
    assert lines[1]["line_number"] == 2
    assert lines[1]["amount"] == 50.0
    client.close()


def test_extract_lines_journal_entry():
    client = QBOClient("id", "secret", "http://localhost/cb")
    item = {
        "Id": "456",
        "TxnDate": "2026-03-20",
        "Line": [
            {
                "Amount": 200.0,
                "Description": "Rent",
                "JournalEntryLineDetail": {
                    "AccountRef": {"name": "Rent Expense", "value": "10"},
                    "Entity": {"name": "Landlord Co"},
                },
            },
        ],
    }
    lines = client._extract_lines(item, "JournalEntry")
    assert len(lines) == 1
    assert lines[0]["payee"] == "Landlord Co"
    assert lines[0]["txn_type"] == "JournalEntry"
    client.close()


def test_extract_lines_bill():
    client = QBOClient("id", "secret", "http://localhost/cb")
    item = {
        "Id": "789",
        "TxnDate": "2026-03-25",
        "VendorRef": {"name": "AWS"},
        "Line": [
            {
                "Amount": 300.0,
                "Description": "EC2",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"name": "Cloud", "value": "50"},
                },
            },
        ],
    }
    lines = client._extract_lines(item, "Bill")
    assert len(lines) == 1
    assert lines[0]["payee"] == "AWS"
    client.close()


# ── Fuzzy matching threshold ─────────────────────────────────


def test_fuzzy_match_similar():
    import difflib
    ratio = difflib.SequenceMatcher(None, "anthropic", "anthropic").ratio()
    assert ratio >= 0.8

    ratio = difflib.SequenceMatcher(None, "amazon web services", "aws").ratio()
    assert ratio < 0.8  # too different


def test_fuzzy_match_normalized():
    norm1 = _normalize_payee("ANTHROPIC INC")
    norm2 = _normalize_payee("Anthropic")
    import difflib
    ratio = difflib.SequenceMatcher(None, norm1, norm2).ratio()
    assert ratio >= 0.8

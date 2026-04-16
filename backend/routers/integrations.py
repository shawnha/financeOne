"""외부 API 연동 라우터 — Mercury, Codef, QuickBooks Online"""

import os
import re
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


# --- Mercury ---

class MercurySyncRequest(BaseModel):
    account_id: str

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Invalid account_id format")
        return v


def _get_mercury_token(conn: PgConnection) -> str:
    """settings 테이블에서 Mercury API 토큰 조회."""
    cur = conn.cursor()
    cur.execute(
        "SELECT value FROM settings WHERE key = 'mercury_api_token' AND entity_id = 1",
    )
    row = cur.fetchone()
    cur.close()
    if not row or not row[0]:
        # fallback: 환경변수
        token = os.environ.get("MERCURY_API_TOKEN", "")
        if not token:
            raise HTTPException(400, "Mercury API token not configured")
        return token
    return row[0]


@router.get("/mercury/status")
def mercury_status(conn: PgConnection = Depends(get_db)):
    """Mercury 연결 상태 확인."""
    try:
        token = _get_mercury_token(conn)
        from backend.services.integrations.mercury import MercuryClient
        client = MercuryClient(token)
        accounts = client.get_accounts()
        client.close()
        return {
            "connected": True,
            "accounts": len(accounts),
            "account_names": [a.get("name", "") for a in accounts],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Connection check failed")
        return {"connected": False, "error": "Unable to connect"}


@router.get("/mercury/accounts")
def mercury_accounts(conn: PgConnection = Depends(get_db)):
    """Mercury 계좌 목록."""
    token = _get_mercury_token(conn)
    from backend.services.integrations.mercury import MercuryClient
    client = MercuryClient(token)
    try:
        accounts = client.get_accounts()
        return {"accounts": accounts}
    finally:
        client.close()


@router.post("/mercury/sync")
def mercury_sync(
    body: MercurySyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """Mercury 거래 동기화."""
    token = _get_mercury_token(conn)
    from backend.services.integrations.mercury import MercuryClient
    client = MercuryClient(token)
    try:
        result = client.sync_transactions(conn, body.account_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        client.close()


# --- Codef ---

class CodefSyncRequest(BaseModel):
    entity_id: int
    connected_id: str
    start_date: str  # YYYYMMDD
    end_date: str

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if not re.match(r"^\d{8}$", v):
            raise ValueError("Date must be YYYYMMDD format")
        year, month, day = int(v[:4]), int(v[4:6]), int(v[6:8])
        if not (2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError("Date out of valid range")
        return v

    @field_validator("connected_id")
    @classmethod
    def validate_connected_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Invalid connected_id format")
        return v

class CodefCardSyncRequest(CodefSyncRequest):
    card_type: str = "lotte_card"  # lotte_card, woori_card, shinhan_card


def _get_codef_client():
    """Codef 클라이언트 생성. 환경변수에서 인증정보 조회."""
    from backend.services.integrations.codef import CodefClient
    client_id = os.environ.get("CODEF_CLIENT_ID", "")
    client_secret = os.environ.get("CODEF_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(400, "Codef credentials not configured")
    return CodefClient(client_id, client_secret)


@router.get("/codef/status")
def codef_status():
    """Codef 연결 상태 확인."""
    try:
        client = _get_codef_client()
        client._get_token()
        client.close()
        return {"connected": True, "environment": "sandbox"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Connection check failed")
        return {"connected": False, "error": "Unable to connect"}


@router.post("/codef/sync-bank")
def codef_sync_bank(
    body: CodefSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """Codef 우리은행 거래 동기화."""
    client = _get_codef_client()
    try:
        result = client.sync_bank_transactions(
            conn, body.entity_id, body.connected_id,
            body.start_date, body.end_date,
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        client.close()


@router.post("/codef/sync-card")
def codef_sync_card(
    body: CodefCardSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """Codef 카드 승인내역 동기화."""
    client = _get_codef_client()
    try:
        approvals = client.get_card_approvals(
            body.connected_id, body.start_date, body.end_date, body.card_type,
        )
        # TODO: Parse and insert card approvals into transactions
        conn.commit()
        return {"total_fetched": len(approvals), "synced": 0, "note": "Card sync parsing not yet implemented"}
    except Exception:
        conn.rollback()
        raise
    finally:
        client.close()


# --- QuickBooks Online ---

class QBOSyncRequest(BaseModel):
    entity_id: int = 1
    start_date: Optional[str] = None

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, v: str | None) -> str | None:
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("Date must be YYYY-MM-DD format")
        return v


class QBOSeedRequest(BaseModel):
    entity_id: int = 1


def _get_qbo_client():
    """QBO 클라이언트 생성."""
    from backend.services.integrations.qbo import QBOClient
    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID", "")
    client_secret = os.environ.get("QUICKBOOKS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(400, "QuickBooks credentials not configured")
    redirect_uri = os.environ.get(
        "QUICKBOOKS_REDIRECT_URI",
        "http://localhost:8000/api/integrations/quickbooks/callback",
    )
    return QBOClient(client_id, client_secret, redirect_uri)


@router.get("/quickbooks/status")
def quickbooks_status(
    entity_id: int = 1,
    conn: PgConnection = Depends(get_db),
):
    """QBO 연결 상태 확인."""
    cur = conn.cursor()
    # realm_id 확인
    cur.execute(
        "SELECT value FROM settings WHERE key = 'qbo_realm_id' AND entity_id = %s",
        [entity_id],
    )
    realm_row = cur.fetchone()

    # last sync 확인
    cur.execute(
        "SELECT MAX(synced_at) FROM qbo_accounts WHERE entity_id = %s",
        [entity_id],
    )
    sync_row = cur.fetchone()

    # account count
    cur.execute(
        "SELECT count(*) FROM qbo_accounts WHERE entity_id = %s",
        [entity_id],
    )
    count_row = cur.fetchone()

    cur.close()

    connected = bool(realm_row and realm_row[0])
    return {
        "connected": connected,
        "realm_id": realm_row[0] if realm_row else None,
        "last_sync": sync_row[0].isoformat() if sync_row and sync_row[0] else None,
        "accounts": count_row[0] if count_row else 0,
    }


@router.get("/quickbooks/authorize")
def quickbooks_authorize(
    entity_id: int = 1,
    conn: PgConnection = Depends(get_db),
):
    """OAuth authorize URL 생성 + CSRF state 저장."""
    from backend.services.integrations.qbo import generate_csrf_state, _save_tokens
    client = _get_qbo_client()

    state = generate_csrf_state(entity_id)
    # state를 settings에 저장
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO settings (key, value, entity_id, updated_at)
        VALUES ('qbo_oauth_state', %s, %s, NOW())
        ON CONFLICT (key, entity_id) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        [state, entity_id],
    )
    cur.close()
    conn.commit()

    auth_url = client.get_auth_url(state)
    client.close()
    return {"auth_url": auth_url}


@router.get("/quickbooks/callback")
def quickbooks_callback(
    code: str = "",
    state: str = "",
    realmId: str = "",
    conn: PgConnection = Depends(get_db),
):
    """OAuth callback — code → tokens 교환 → settings 저장 → frontend redirect."""
    from backend.services.integrations.qbo import validate_csrf_state, _save_tokens

    if not code or not state or not realmId:
        return RedirectResponse("http://localhost:3000/settings?qbo=error&reason=missing_params")

    # CSRF 검증: state에서 entity_id 추출
    parts = state.split(":", 1)
    if len(parts) != 2:
        return RedirectResponse("http://localhost:3000/settings?qbo=error&reason=invalid_state")

    try:
        entity_id = int(parts[0])
    except ValueError:
        return RedirectResponse("http://localhost:3000/settings?qbo=error&reason=invalid_state")

    # 저장된 state와 비교
    cur = conn.cursor()
    cur.execute(
        "SELECT value FROM settings WHERE key = 'qbo_oauth_state' AND entity_id = %s",
        [entity_id],
    )
    stored_row = cur.fetchone()
    cur.close()

    if not stored_row or stored_row[0] != state:
        return RedirectResponse("http://localhost:3000/settings?qbo=error&reason=csrf_mismatch")

    # Token exchange
    client = _get_qbo_client()
    try:
        tokens = client.exchange_code(code, realmId)
        tokens["realm_id"] = realmId
        _save_tokens(conn, entity_id, tokens)
        conn.commit()
        return RedirectResponse(f"http://localhost:3000/settings?qbo=connected")
    except Exception as e:
        logger.exception("QBO callback failed")
        conn.rollback()
        return RedirectResponse(f"http://localhost:3000/settings?qbo=error&reason=token_exchange")
    finally:
        client.close()


@router.post("/quickbooks/sync")
def quickbooks_sync(
    body: QBOSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """QBO accounts + transactions 동기화."""
    client = _get_qbo_client()
    try:
        acct_result = client.sync_accounts(conn, body.entity_id)
        txn_result = client.sync_transactions(conn, body.entity_id, body.start_date)
        conn.commit()
        return {
            "accounts": acct_result,
            "transactions": txn_result,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        client.close()


@router.post("/quickbooks/seed-rules")
def quickbooks_seed_rules(
    body: QBOSeedRequest,
    conn: PgConnection = Depends(get_db),
):
    """mapping_rules 시드 (80% 룰 + gaap_mapping 경유)."""
    client = _get_qbo_client()
    try:
        result = client.seed_mapping_rules(conn, body.entity_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        client.close()

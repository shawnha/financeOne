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

VALID_CODEF_ORGS = {"woori_bank", "lotte_card", "woori_card", "shinhan_card"}


class CodefSyncRequest(BaseModel):
    entity_id: int
    start_date: str  # YYYYMMDD
    end_date: str
    connected_id: Optional[str] = None  # None이면 settings에서 조회

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
    def validate_connected_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Invalid connected_id format")
        return v


class CodefCardSyncRequest(CodefSyncRequest):
    card_type: str = "lotte_card"  # lotte_card, woori_card, shinhan_card

    @field_validator("card_type")
    @classmethod
    def validate_card_type(cls, v: str) -> str:
        if v not in ("lotte_card", "woori_card", "shinhan_card"):
            raise ValueError("card_type must be lotte_card|woori_card|shinhan_card")
        return v


class CodefConnectionUpsertRequest(BaseModel):
    entity_id: int
    organization: str  # woori_bank | lotte_card | woori_card | shinhan_card
    connected_id: str

    @field_validator("organization")
    @classmethod
    def validate_org(cls, v: str) -> str:
        if v not in VALID_CODEF_ORGS:
            raise ValueError(f"organization must be one of {VALID_CODEF_ORGS}")
        return v

    @field_validator("connected_id")
    @classmethod
    def validate_cid(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Invalid connected_id format")
        return v


class CodefConnectionDeleteRequest(BaseModel):
    entity_id: int
    organization: str

    @field_validator("organization")
    @classmethod
    def validate_org(cls, v: str) -> str:
        if v not in VALID_CODEF_ORGS:
            raise ValueError(f"organization must be one of {VALID_CODEF_ORGS}")
        return v


class CodefAccountSpec(BaseModel):
    """Codef /v1/account/create 요청 단위. id/pw 로그인 또는 공동인증서.

    우리은행(0020) 등 일부 기관은 공동인증서 의무 — loginType='0' + derFile + keyFile + password 필수.
    """
    organization: str
    business_type: str = "BK"  # BK=bank, CD=card
    client_type: str = "B"  # B=법인, P=개인
    login_type: str = "1"  # "0"=공동인증서, "1"=id/pw

    # id/pw 로그인 (loginType=1)
    login_id: Optional[str] = None
    login_password: Optional[str] = None  # plain → 서버에서 RSA+base64

    # 공동인증서 (loginType=0)
    # Codef SDK 표준 필드명: derFile, keyFile, password(=cert 비번)
    der_file_b64: Optional[str] = None   # base64-encoded signCert.der
    key_file_b64: Optional[str] = None   # base64-encoded signPri.key
    cert_password: Optional[str] = None  # plain → 서버에서 RSA+base64
    # NPKI 로컬 경로로 cert 지정 (der/key 자동 로드)
    npki_cert_path: Optional[str] = None

    @field_validator("organization")
    @classmethod
    def validate_org(cls, v: str) -> str:
        if v not in VALID_CODEF_ORGS:
            raise ValueError(f"organization must be one of {VALID_CODEF_ORGS}")
        return v

    @field_validator("login_type")
    @classmethod
    def validate_login_type(cls, v: str) -> str:
        if v not in ("0", "1"):
            raise ValueError("login_type must be '0' (cert) or '1' (id/pw)")
        return v

    @field_validator("business_type")
    @classmethod
    def validate_btype(cls, v: str) -> str:
        if v not in ("BK", "CD"):
            raise ValueError("business_type must be BK (bank) or CD (card)")
        return v


class CodefConnectRequest(BaseModel):
    entity_id: int
    accounts: list[CodefAccountSpec]
    save_as: Optional[str] = None  # settings 키로 저장할 org 이름. 첫 계정 org 기본값.


def _get_codef_client():
    """Codef 클라이언트 생성. env var로 환경 결정 (sandbox/production)."""
    from backend.services.integrations.codef import CodefClient
    client_id = os.environ.get("CODEF_CLIENT_ID", "")
    client_secret = os.environ.get("CODEF_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(400, "Codef credentials not configured")
    return CodefClient(client_id, client_secret)


def _resolve_connected_id(
    conn: PgConnection,
    entity_id: int,
    organization: str,
    provided: Optional[str],
) -> str:
    """body에 connected_id 있으면 우선. 없으면 settings에서 조회."""
    if provided:
        return provided
    from backend.services.integrations.codef import get_connected_id
    cid = get_connected_id(conn, entity_id, organization)
    if not cid:
        raise HTTPException(
            400,
            f"connected_id not configured for entity={entity_id}, org={organization}",
        )
    return cid


@router.get("/codef/status")
def codef_status(
    entity_id: int = 2,
    conn: PgConnection = Depends(get_db),
):
    """Codef 연결 상태 + 환경 + 등록된 connected_id 목록."""
    from backend.services.integrations.codef import (
        resolve_base_url,
        is_production,
        list_connected_ids,
    )

    configured = bool(
        os.environ.get("CODEF_CLIENT_ID") and os.environ.get("CODEF_CLIENT_SECRET")
    )
    env = "production" if is_production() else "demo"
    connections = list_connected_ids(conn, entity_id) if configured else {}

    if not configured:
        return {
            "configured": False,
            "connected": False,
            "environment": env,
            "base_url": resolve_base_url(),
            "connections": {},
        }

    try:
        client = _get_codef_client()
        client._get_token()
        client.close()
        return {
            "configured": True,
            "connected": True,
            "environment": env,
            "base_url": resolve_base_url(),
            "connections": connections,
        }
    except Exception:
        logger.exception("Connection check failed")
        return {
            "configured": True,
            "connected": False,
            "environment": env,
            "base_url": resolve_base_url(),
            "connections": connections,
            "error": "Unable to authenticate",
        }


@router.get("/codef/connections")
def codef_list_connections(
    entity_id: int,
    conn: PgConnection = Depends(get_db),
):
    """entity의 Codef connected_id 목록."""
    from backend.services.integrations.codef import list_connected_ids
    return {"connections": list_connected_ids(conn, entity_id)}


@router.post("/codef/connections")
def codef_upsert_connection(
    body: CodefConnectionUpsertRequest,
    conn: PgConnection = Depends(get_db),
):
    """connected_id 저장/갱신."""
    from backend.services.integrations.codef import set_connected_id
    try:
        set_connected_id(conn, body.entity_id, body.organization, body.connected_id)
        conn.commit()
        return {"ok": True, "organization": body.organization}
    except Exception:
        conn.rollback()
        raise


@router.delete("/codef/connections")
def codef_delete_connection(
    body: CodefConnectionDeleteRequest,
    conn: PgConnection = Depends(get_db),
):
    """connected_id 삭제."""
    from backend.services.integrations.codef import delete_connected_id
    try:
        deleted = delete_connected_id(conn, body.entity_id, body.organization)
        conn.commit()
        return {"deleted": deleted, "organization": body.organization}
    except Exception:
        conn.rollback()
        raise


@router.get("/codef/npki/certs")
def codef_npki_list():
    """로컬 Mac/Linux의 공동인증서 목록 (발견된 것만)."""
    from backend.services.integrations.codef import discover_npki_certs
    return {"certs": discover_npki_certs()}


@router.post("/codef/connect")
def codef_connect(
    body: CodefConnectRequest,
    conn: PgConnection = Depends(get_db),
):
    """연계 계정 등록 → connected_id 발급 + settings 저장.

    샌드박스: Codef 테스트 id/pw로 검증 가능.
    프로덕션: 공동인증서(cert_file_b64 + key_file_b64 + cert_password) 필요.
    """
    from backend.services.integrations.codef import (
        ORG_CODES,
        set_connected_id,
        is_production,
        encrypt_password,
        CodefError,
    )

    if not body.accounts:
        raise HTTPException(400, "accounts list empty")

    # Codef 요청 포맷으로 변환 — 비밀번호는 RSA(PKCS1v15) + base64
    account_list = []
    try:
        for spec in body.accounts:
            org_code = ORG_CODES.get(spec.organization)
            if not org_code:
                raise HTTPException(400, f"Unknown organization: {spec.organization}")

            account = {
                "countryCode": "KR",
                "businessType": spec.business_type,
                "organization": org_code,
                "clientType": spec.client_type,
                "loginType": spec.login_type,
            }

            if spec.login_type == "1":
                if not spec.login_id or not spec.login_password:
                    raise HTTPException(400, "login_id + login_password required for id/pw auth")
                account["id"] = spec.login_id
                account["password"] = encrypt_password(spec.login_password)
            else:
                # 공동인증서 — npki_cert_path 우선, 없으면 업로드된 der/key 사용
                der_b64 = spec.der_file_b64
                key_b64 = spec.key_file_b64
                if spec.npki_cert_path:
                    from backend.services.integrations.codef import load_npki_cert_files
                    der_b64, key_b64 = load_npki_cert_files(spec.npki_cert_path)

                if not (der_b64 and key_b64 and spec.cert_password):
                    raise HTTPException(
                        400,
                        "인증서 파일(.der+.key) 또는 npki_cert_path + 인증서 비밀번호 필요",
                    )
                account["derFile"] = der_b64
                account["keyFile"] = key_b64
                account["password"] = encrypt_password(spec.cert_password)

            account_list.append(account)
    except CodefError as e:
        # 공개키 미설정 등 설정 문제 — 400으로 사용자에게 명확한 안내
        raise HTTPException(400, str(e))

    client = _get_codef_client()
    try:
        connected_id = client.create_connected_id(account_list)
        saved_orgs = []
        for spec in body.accounts:
            set_connected_id(conn, body.entity_id, spec.organization, connected_id)
            saved_orgs.append(spec.organization)
        conn.commit()
        return {
            "connected_id": connected_id,
            "saved_for": saved_orgs,
            "environment": client.environment,
        }
    except HTTPException:
        conn.rollback()
        raise
    except CodefError as e:
        conn.rollback()
        raise HTTPException(400, f"Codef 연결 실패: {str(e)}")
    except Exception as e:
        conn.rollback()
        logger.exception("Codef connect failed")
        raise HTTPException(500, f"내부 오류: {type(e).__name__}")
    finally:
        client.close()


@router.post("/codef/sync-bank")
def codef_sync_bank(
    body: CodefSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """Codef 우리은행 거래 동기화."""
    from backend.services.integrations.codef import CodefError
    connected_id = _resolve_connected_id(conn, body.entity_id, "woori_bank", body.connected_id)
    client = _get_codef_client()
    try:
        result = client.sync_bank_transactions(
            conn, body.entity_id, connected_id,
            body.start_date, body.end_date,
        )
        conn.commit()
        return result
    except CodefError as e:
        conn.rollback()
        raise HTTPException(400, f"Codef 은행 sync 실패: {str(e)}")
    except Exception as e:
        conn.rollback()
        logger.exception("Codef bank sync failed")
        raise HTTPException(500, f"내부 오류: {type(e).__name__}")
    finally:
        client.close()


@router.post("/codef/sync-card")
def codef_sync_card(
    body: CodefCardSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """Codef 카드 승인내역 동기화."""
    from backend.services.integrations.codef import CodefError
    connected_id = _resolve_connected_id(conn, body.entity_id, body.card_type, body.connected_id)
    client = _get_codef_client()
    try:
        result = client.sync_card_approvals(
            conn, body.entity_id, connected_id,
            body.start_date, body.end_date, body.card_type,
        )
        conn.commit()
        return result
    except CodefError as e:
        conn.rollback()
        raise HTTPException(400, f"Codef 카드 sync 실패: {str(e)}")
    except Exception as e:
        conn.rollback()
        logger.exception("Codef card sync failed")
        raise HTTPException(500, f"내부 오류: {type(e).__name__}")
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


# --- ExpenseOne ---

class ExpenseOneSyncRequest(BaseModel):
    entity_id: int = 2  # 한아원코리아
    since_date: Optional[str] = None  # ISO date (YYYY-MM-DD) or timestamp

    @field_validator("since_date")
    @classmethod
    def validate_since_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # YYYY-MM-DD 또는 ISO timestamp 허용
        if not re.match(r"^\d{4}-\d{2}-\d{2}", v):
            raise ValueError("since_date must be YYYY-MM-DD (optionally with time suffix)")
        return v


@router.get("/expenseone/status")
def expenseone_status(
    entity_id: int = 2,
    conn: PgConnection = Depends(get_db),
):
    """ExpenseOne 연결 상태 + 마지막 동기화 통계.

    ExpenseOne은 FinanceOne과 같은 Supabase 프로젝트의 expenseone 스키마.
    별도 credentials 불필요 — DATABASE_URL만으로 충분.
    """
    from backend.services.integrations import expenseone as eo

    conn_info = eo.check_connection(conn)
    stats = eo.get_synced_stats(conn, entity_id)

    return {
        "configured": True,
        "connected": conn_info.get("connected", False),
        "error": conn_info.get("error"),
        "synced_count": stats["synced_count"],
        "last_sync": stats["last_sync"],
    }


@router.post("/expenseone/sync")
def expenseone_sync(
    body: ExpenseOneSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """ExpenseOne 승인 경비 → FinanceOne transactions 동기화."""
    from backend.services.integrations import expenseone as eo

    try:
        expenses = eo.fetch_approved(conn, body.since_date)
        result = eo.sync_to_financeone(conn, body.entity_id, expenses)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise

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


def _notify_expenseone_card_sync() -> None:
    """Fire-and-forget webhook to ExpenseOne after Codef card sync."""
    import httpx
    expenseone_url = os.environ.get("EXPENSEONE_URL", "https://expenseone.vercel.app")
    cron_secret = os.environ.get("EXPENSEONE_CRON_SECRET", "")
    if not cron_secret:
        logger.warning("[ExpenseOne] EXPENSEONE_CRON_SECRET not set, skipping notify")
        return
    try:
        resp = httpx.post(
            f"{expenseone_url}/api/cron/codef-notify",
            headers={"Authorization": f"Bearer {cron_secret}"},
            timeout=15,
        )
        logger.info("[ExpenseOne] codef-notify: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("[ExpenseOne] codef-notify failed: %s", e)


def _sync_forecast_actuals_after_import(conn: PgConnection, entity_id: int) -> None:
    """P0-3: 외부 거래 import 후 current + prev month forecast.actual_amount 갱신.

    GET /forecast 가 더 이상 자동 sync 하지 않으므로 import 직후 명시적 갱신.
    실패해도 import 결과 응답을 막지 않음 (warning log).
    P1-4: KST(today_kst) 기준 — UTC 서버에서 KST 자정~9시 사이 month rollover 어긋남 방지.
    """
    try:
        from backend.services.cashflow_service import sync_forecast_actuals as _sync_fc
        from backend.utils.timezone import today_kst
        today = today_kst()
        py = today.year if today.month > 1 else today.year - 1
        pm = today.month - 1 if today.month > 1 else 12
        _sync_fc(conn, entity_id, today.year, today.month)
        _sync_fc(conn, entity_id, py, pm)
    except Exception as sync_err:
        logger.warning("forecast actuals sync after import failed: entity=%s err=%s",
                       entity_id, sync_err)


# --- Mercury ---

class MercurySyncRequest(BaseModel):
    account_id: str
    start_date: Optional[str] = None  # ISO 8601 YYYY-MM-DD
    end_date: Optional[str] = None

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Invalid account_id format")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("Date must be ISO 8601 (YYYY-MM-DD)")
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
        result = client.sync_transactions(
            conn, body.account_id,
            start_date=getattr(body, "start_date", None),
            end_date=getattr(body, "end_date", None),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        client.close()


# --- Codef ---

VALID_CODEF_ORGS = {
    "woori_bank", "ibk_bank",
    "lotte_card", "bc_card", "samsung_card", "shinhan_card",
    "hyundai_card", "nh_card", "woori_card", "kb_card", "hana_card",
}


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
    card_type: str = "lotte_card"

    @field_validator("card_type")
    @classmethod
    def validate_card_type(cls, v: str) -> str:
        from backend.services.integrations.codef import CARD_ORGS
        if v not in CARD_ORGS:
            raise ValueError(f"card_type must be one of {sorted(CARD_ORGS)}")
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
    # 카드사·일부 은행 추가 필수 필드 (없으면 무시)
    card_password: Optional[str] = None     # 4자리 카드 비밀번호 → RSA+base64
    business_no: Optional[str] = None       # 사업자등록번호 (10자리)
    birth_date: Optional[str] = None        # 대표자 생년월일 (YYMMDD)

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


def _log_codef_error(
    conn: PgConnection,
    entity_id: Optional[int],
    organization: Optional[str],
    err,
) -> Optional[int]:
    """CodefError 발생 시 codef_api_log에 기록.

    호출 전 conn.rollback()을 먼저 수행하는 것을 가정 (동기화 실패한 tx 무효화).
    로그는 별도 savepoint로 커밋.
    """
    import json as _json
    from backend.services.integrations.codef import CodefError
    tx_id = getattr(err, "transaction_id", None)
    code = getattr(err, "code", None)
    extra = getattr(err, "extra_message", None)
    endpoint = getattr(err, "endpoint", None)
    params = getattr(err, "request_params", None)
    body = getattr(err, "response_body", None)
    message = str(err)

    # response_body가 dict/list/None 모두 가능 — JSONB로 직렬화
    def _jsonable(v):
        if v is None:
            return None
        try:
            return _json.dumps(v, ensure_ascii=False, default=str)
        except Exception:
            return _json.dumps({"_unserializable": True})

    cur = conn.cursor()
    try:
        # 앞선 rollback 직후 search_path가 reset될 수 있으므로 스키마 명시
        cur.execute("SET search_path TO financeone, public")
        cur.execute(
            """
            INSERT INTO financeone.codef_api_log
                (entity_id, organization, endpoint, result_code, message,
                 extra_message, transaction_id, is_error, request_params, response_body)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s::jsonb, %s::jsonb)
            RETURNING id
            """,
            [entity_id, organization, endpoint, code, message, extra, tx_id,
             _jsonable(params), _jsonable(body)],
        )
        log_id = cur.fetchone()[0]
        conn.commit()
        return log_id
    except Exception:
        conn.rollback()
        logger.exception("failed to persist codef_api_log entry")
        return None
    finally:
        cur.close()


def _codef_error_detail(err, log_id: Optional[int] = None) -> dict:
    """HTTPException.detail 로 반환할 구조화된 에러 정보."""
    return {
        "message": str(err),
        "code": getattr(err, "code", None),
        "transaction_id": getattr(err, "transaction_id", None),
        "extra_message": getattr(err, "extra_message", None),
        "endpoint": getattr(err, "endpoint", None),
        "log_id": log_id,
    }


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
    """Codef 연결 상태 + 환경 + 등록된 connected_id + 마지막 sync 시각."""
    from backend.services.integrations.codef import (
        resolve_base_url,
        is_production,
        list_connected_ids,
        list_last_syncs,
    )

    configured = bool(
        os.environ.get("CODEF_CLIENT_ID") and os.environ.get("CODEF_CLIENT_SECRET")
    )
    env = "production" if is_production() else "demo"
    connections = list_connected_ids(conn, entity_id) if configured else {}
    last_syncs = list_last_syncs(conn, entity_id) if configured else {}

    if not configured:
        return {
            "configured": False,
            "connected": False,
            "environment": env,
            "base_url": resolve_base_url(),
            "connections": {},
            "last_syncs": {},
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
            "last_syncs": last_syncs,
        }
    except Exception:
        logger.exception("Connection check failed")
        return {
            "configured": True,
            "connected": False,
            "environment": env,
            "base_url": resolve_base_url(),
            "connections": connections,
            "last_syncs": last_syncs,
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
                # 카드사·일부 은행 추가 필드 (있으면 포함)
                if spec.card_password:
                    account["cardPassword"] = encrypt_password(spec.card_password)
                if spec.business_no:
                    account["businessNo"] = spec.business_no
                if spec.birth_date:
                    account["birthDate"] = spec.birth_date
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
        first_org = body.accounts[0].organization if body.accounts else None
        log_id = _log_codef_error(conn, body.entity_id, first_org, e)
        raise HTTPException(400, _codef_error_detail(e, log_id))
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
    from backend.services.integrations.codef import CodefError, set_last_sync
    connected_id = _resolve_connected_id(conn, body.entity_id, "woori_bank", body.connected_id)
    client = _get_codef_client()
    try:
        result = client.sync_bank_transactions(
            conn, body.entity_id, connected_id,
            body.start_date, body.end_date,
        )
        set_last_sync(conn, body.entity_id, "woori_bank")
        conn.commit()
        _sync_forecast_actuals_after_import(conn, body.entity_id)
        return result
    except CodefError as e:
        conn.rollback()
        log_id = _log_codef_error(conn, body.entity_id, "woori_bank", e)
        raise HTTPException(400, _codef_error_detail(e, log_id))
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
    from backend.services.integrations.codef import CodefError, set_last_sync
    connected_id = _resolve_connected_id(conn, body.entity_id, body.card_type, body.connected_id)
    client = _get_codef_client()
    try:
        result = client.sync_card_approvals(
            conn, body.entity_id, connected_id,
            body.start_date, body.end_date, body.card_type,
        )
        set_last_sync(conn, body.entity_id, body.card_type)
        conn.commit()
        _sync_forecast_actuals_after_import(conn, body.entity_id)
        # Notify ExpenseOne about new card transactions
        _notify_expenseone_card_sync()
        return result
    except CodefError as e:
        conn.rollback()
        log_id = _log_codef_error(conn, body.entity_id, body.card_type, e)
        raise HTTPException(400, _codef_error_detail(e, log_id))
    except Exception as e:
        conn.rollback()
        logger.exception("Codef card sync failed")
        raise HTTPException(500, f"내부 오류: {type(e).__name__}")
    finally:
        client.close()


class CodefTaxInvoiceSyncRequest(CodefSyncRequest):
    query_type: str = "3"  # '1'=매출, '2'=매입, '3'=전체
    our_biz_no: Optional[str] = None  # direction 자동 판별. 미지정 시 모두 'unknown'

    @field_validator("query_type")
    @classmethod
    def validate_query_type(cls, v: str) -> str:
        if v not in ("1", "2", "3"):
            raise ValueError("query_type must be '1' (sales), '2' (purchase), or '3' (all)")
        return v


@router.post("/codef/sync-tax-invoice")
def codef_sync_tax_invoice(
    body: CodefTaxInvoiceSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """Codef 홈택스 전자세금계산서 통합조회 → invoices 테이블 동기화.

    organization=0001 (국세청 홈택스).
    connected_id: 사전에 사업자 인증서로 등록된 connected_id (settings 'hometax').
    our_biz_no: body 에 명시 안 하면 entities.business_number 자동 조회.
    매칭 안 되는 행은 direction='unknown' 으로 invoices 에 들어감.
    """
    from backend.services.integrations.codef import CodefError, set_last_sync
    connected_id = _resolve_connected_id(conn, body.entity_id, "hometax", body.connected_id)

    # our_biz_no fallback → entities.business_number
    our_biz_no = body.our_biz_no
    if not our_biz_no:
        cur = conn.cursor()
        cur.execute("SELECT business_number FROM entities WHERE id = %s", [body.entity_id])
        row = cur.fetchone()
        cur.close()
        if row and row[0]:
            our_biz_no = row[0]

    client = _get_codef_client()
    try:
        result = client.sync_tax_invoices(
            conn, body.entity_id, connected_id,
            body.start_date, body.end_date,
            query_type=body.query_type,
            our_biz_no=our_biz_no,
        )
        set_last_sync(conn, body.entity_id, "hometax")
        conn.commit()
        result["our_biz_no_used"] = our_biz_no
        return result
    except CodefError as e:
        conn.rollback()
        log_id = _log_codef_error(conn, body.entity_id, "hometax", e)
        raise HTTPException(400, _codef_error_detail(e, log_id))
    except Exception as e:
        conn.rollback()
        logger.exception("Codef tax invoice sync failed")
        raise HTTPException(500, f"내부 오류: {type(e).__name__}")
    finally:
        client.close()


class CodefCompareCardRequest(BaseModel):
    entity_id: int
    card_type: str
    start_date: str  # YYYYMMDD
    end_date: str    # YYYYMMDD
    connected_id: Optional[str] = None


@router.post("/codef/compare-card")
def codef_compare_card(
    body: CodefCompareCardRequest,
    conn: PgConnection = Depends(get_db),
):
    """Codef 카드 승인내역 fetch (DB INSERT 없음) + 기존 DB 거래와 비교.

    목적: 다른 소스(Gowid 등)로 이미 들어온 거래와 Codef 응답을 대조하여
    정식 전환 전 정합성을 확인.

    반환:
        codef: {cards[], rows[], total_fetched, sum_amount}
        db_existing: {by_source: {<source_type>: {count, sum}}}
        diff: {
            only_in_codef: [rows...],
            only_in_db: [rows...],
            matched: N
        }
    매칭 키: (date, amount) — counterparty는 소스별 표기 차이 있어 제외.
    """
    from decimal import Decimal
    from backend.services.integrations.codef import (
        CodefError, _normalize_card_row,
    )
    from datetime import datetime

    def _fmt_date(s: str) -> str:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s

    try:
        start_iso = _fmt_date(body.start_date)
        end_iso = _fmt_date(body.end_date)
        datetime.strptime(start_iso, "%Y-%m-%d")
        datetime.strptime(end_iso, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "start_date / end_date must be YYYYMMDD")

    connected_id = _resolve_connected_id(conn, body.entity_id, body.card_type, body.connected_id)
    client = _get_codef_client()

    codef_rows: list[dict] = []
    cards_summary: list[dict] = []
    try:
        cards = client.get_card_list(connected_id, body.card_type)
        if not cards:
            raise HTTPException(400, f"{body.card_type}: Codef 보유 카드 없음")

        for card in cards:
            card_no = card.get("resCardNo", "")
            card_name = card.get("resCardName", "") or ""
            try:
                approvals = client.get_card_approvals(
                    connected_id, body.start_date, body.end_date,
                    body.card_type, card_no=card_no,
                )
            except CodefError as e:
                logger.warning("card %s approval-list 실패: %s", card_no, e)
                approvals = []
            for a in approvals:
                a["_codefCardNo"] = card_no
                a["_codefCardName"] = card_name
            cards_summary.append({
                "card_no": card_no,
                "card_name": card_name,
                "fetched": len(approvals),
            })
            for raw in approvals:
                tx = _normalize_card_row(raw)
                if not tx:
                    continue
                codef_rows.append({
                    "date": str(tx["date"]),
                    "amount": float(tx["amount"]),
                    "counterparty": tx.get("counterparty"),
                    "type": tx.get("type"),
                    "is_cancel": bool(tx.get("is_cancel")),
                    "card_number": tx.get("card_number"),
                    "member_name": tx.get("member_name"),
                    "description": tx.get("description"),
                })
    except CodefError as e:
        log_id = _log_codef_error(conn, body.entity_id, body.card_type, e)
        raise HTTPException(400, _codef_error_detail(e, log_id))
    finally:
        client.close()

    # ── 기존 DB 거래 조회 (같은 card_type의 lotte_card 또는 codef_lotte_card 등)
    plain = body.card_type
    prefixed = f"codef_{body.card_type}"
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT source_type, date, amount, counterparty, type, is_cancel,
                   card_number, parsed_member_name
            FROM transactions
            WHERE entity_id = %s
              AND source_type IN (%s, %s)
              AND date BETWEEN %s::date AND %s::date
            ORDER BY date, amount
            """,
            [body.entity_id, plain, prefixed, start_iso, end_iso],
        )
        db_rows = []
        db_by_source: dict[str, dict[str, float]] = {}
        for r in cur.fetchall():
            src, d, amt, cp, t, cancel, card_num, member = r
            amt_f = float(amt)
            db_rows.append({
                "source_type": src,
                "date": str(d),
                "amount": amt_f,
                "counterparty": cp,
                "type": t,
                "is_cancel": bool(cancel),
                "card_number": card_num,
                "member_name": member,
            })
            stats = db_by_source.setdefault(src, {"count": 0, "sum": 0.0})
            stats["count"] += 1
            stats["sum"] += amt_f
    finally:
        cur.close()

    # ── diff: 매칭 key = (date, amount) 튜플 (최소 key — counterparty 표기 차이 회피)
    # 다중 occurrence 지원 위해 list의 count 기반으로 매칭
    def _key(r):
        return (r["date"], round(r["amount"], 2))

    codef_keys: dict = {}
    for r in codef_rows:
        k = _key(r)
        codef_keys.setdefault(k, []).append(r)
    db_keys: dict = {}
    for r in db_rows:
        k = _key(r)
        db_keys.setdefault(k, []).append(r)

    only_in_codef = []
    matched = 0
    for k, cr_list in codef_keys.items():
        db_list = db_keys.get(k, [])
        for i, cr in enumerate(cr_list):
            if i < len(db_list):
                matched += 1
            else:
                only_in_codef.append(cr)

    only_in_db = []
    for k, db_list in db_keys.items():
        cr_list = codef_keys.get(k, [])
        for i, dr in enumerate(db_list):
            if i >= len(cr_list):
                only_in_db.append(dr)

    codef_sum = sum(r["amount"] for r in codef_rows)
    db_sum_total = sum(s["sum"] for s in db_by_source.values())
    db_count_total = sum(s["count"] for s in db_by_source.values())

    return {
        "range": {"start": start_iso, "end": end_iso},
        "codef": {
            "cards": cards_summary,
            "total_fetched": len(codef_rows),
            "sum_amount": round(codef_sum, 2),
            "environment": client.environment,
        },
        "db_existing": {
            "by_source": {
                k: {"count": v["count"], "sum": round(v["sum"], 2)}
                for k, v in db_by_source.items()
            },
            "total_count": db_count_total,
            "total_sum": round(db_sum_total, 2),
        },
        "diff": {
            "matched": matched,
            "only_in_codef": only_in_codef,
            "only_in_db": only_in_db,
        },
    }


@router.get("/codef/scheduler/status")
def codef_scheduler_status():
    """스케줄러 현재 상태 + 최근 실행 요약."""
    from backend.services.scheduler import get_status
    return get_status()


@router.post("/codef/scheduler/run-now")
async def codef_scheduler_run_now():
    """수동 트리거 — 즉시 sync job 1회 실행."""
    from backend.services.scheduler import run_now
    return await run_now()


@router.get("/codef/errors")
def codef_errors(
    entity_id: Optional[int] = None,
    organization: Optional[str] = None,
    limit: int = 20,
    conn: PgConnection = Depends(get_db),
):
    """Codef 기술 문의용 최근 오류 로그.

    각 항목에 transaction_id 포함 — Codef 측에 전달할 식별자.
    """
    cur = conn.cursor()
    try:
        limit = max(1, min(limit, 100))
        where = ["is_error = TRUE"]
        params: list = []
        if entity_id is not None:
            where.append("entity_id = %s")
            params.append(entity_id)
        if organization:
            where.append("organization = %s")
            params.append(organization)
        cur.execute(
            f"""
            SELECT id, entity_id, organization, endpoint, result_code,
                   message, extra_message, transaction_id, created_at
            FROM financeone.codef_api_log
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            params + [limit],
        )
        rows = cur.fetchall()
        return {
            "errors": [
                {
                    "id": r[0],
                    "entity_id": r[1],
                    "organization": r[2],
                    "endpoint": r[3],
                    "result_code": r[4],
                    "message": r[5],
                    "extra_message": r[6],
                    "transaction_id": r[7],
                    "created_at": r[8].isoformat() if r[8] else None,
                }
                for r in rows
            ]
        }
    finally:
        cur.close()


@router.get("/codef/errors/{log_id}")
def codef_error_detail(
    log_id: int,
    conn: PgConnection = Depends(get_db),
):
    """단건 상세 — 요청 파라미터(마스킹됨) + 전체 응답 body 포함."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, entity_id, organization, endpoint, result_code,
                   message, extra_message, transaction_id, is_error,
                   request_params, response_body, created_at
            FROM financeone.codef_api_log
            WHERE id = %s
            """,
            [log_id],
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(404, "log not found")
        return {
            "id": r[0],
            "entity_id": r[1],
            "organization": r[2],
            "endpoint": r[3],
            "result_code": r[4],
            "message": r[5],
            "extra_message": r[6],
            "transaction_id": r[7],
            "is_error": r[8],
            "request_params": r[9],
            "response_body": r[10],
            "created_at": r[11].isoformat() if r[11] else None,
        }
    finally:
        cur.close()


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


# --- Gowid (법인카드 차선책) ---


class GowidSyncRequest(BaseModel):
    entity_id: int = 2
    start_date: str  # ISO YYYY-MM-DD
    end_date: str

    @field_validator("start_date", "end_date")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("date must be YYYY-MM-DD")
        return v


def _get_gowid_client_for_entity(conn: PgConnection, entity_id: int):
    """entity별 API key로 Gowid 클라이언트 생성. 없으면 env GOWID_API_KEY로 fallback."""
    from backend.services.integrations.gowid import GowidClient, get_api_key
    key = get_api_key(conn, entity_id)
    if not key:
        # 하위 호환: 첫 등록 전엔 env var 사용 (entity 2 마이그레이션용)
        key = os.environ.get("GOWID_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            400,
            f"Gowid API key가 entity_id={entity_id}에 등록되지 않음 — 설정에서 추가 필요",
        )
    return GowidClient(key)


class GowidApiKeyRequest(BaseModel):
    entity_id: int
    api_key: str

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("api_key가 너무 짧습니다")
        return v


@router.get("/gowid/status")
def gowid_status(
    entity_id: int = 2,
    conn: PgConnection = Depends(get_db),
):
    """Gowid 연결 상태 + 마지막 sync 시각 (entity별)."""
    from backend.services.integrations.gowid import get_api_key
    key = get_api_key(conn, entity_id) or os.environ.get("GOWID_API_KEY", "").strip()
    configured = bool(key)

    if not configured:
        return {
            "configured": False, "connected": False,
            "last_sync": None, "synced_count": 0, "key_source": None,
        }

    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*), MAX(updated_at)
        FROM transactions
        WHERE entity_id = %s AND source_type = 'gowid_card'
        """,
        [entity_id],
    )
    row = cur.fetchone()
    cur.close()

    try:
        client = _get_gowid_client_for_entity(conn, entity_id)
        connected = client.health()
        client.close()
    except Exception:
        connected = False

    return {
        "configured": True,
        "connected": connected,
        "synced_count": row[0] if row else 0,
        "last_sync": row[1].isoformat() if row and row[1] else None,
        "key_source": "settings" if get_api_key(conn, entity_id) else "env",
    }


@router.post("/gowid/api-key")
def gowid_set_api_key(
    body: GowidApiKeyRequest,
    conn: PgConnection = Depends(get_db),
):
    """법인별 Gowid API key 저장."""
    from backend.services.integrations.gowid import set_api_key, GowidClient
    # 키 검증 — 실 API 호출
    test_client = GowidClient(body.api_key)
    try:
        if not test_client.health():
            raise HTTPException(400, "API key 검증 실패: Gowid에서 거절")
    finally:
        test_client.close()
    set_api_key(conn, body.entity_id, body.api_key)
    conn.commit()
    return {"ok": True, "entity_id": body.entity_id}


@router.delete("/gowid/api-key")
def gowid_delete_api_key(
    entity_id: int,
    conn: PgConnection = Depends(get_db),
):
    from backend.services.integrations.gowid import delete_api_key
    deleted = delete_api_key(conn, entity_id)
    conn.commit()
    return {"deleted": deleted, "entity_id": entity_id}


@router.post("/gowid/sync")
def gowid_sync(
    body: GowidSyncRequest,
    conn: PgConnection = Depends(get_db),
):
    """Gowid 거래 동기화 (entity별)."""
    from backend.services.integrations.gowid import GowidError
    client = _get_gowid_client_for_entity(conn, body.entity_id)
    try:
        result = client.sync_expenses(
            conn, body.entity_id, body.start_date, body.end_date,
        )
        conn.commit()
        return result
    except GowidError as e:
        conn.rollback()
        raise HTTPException(400, f"Gowid sync 실패: {str(e)}")
    except Exception as e:
        conn.rollback()
        logger.exception("Gowid sync failed")
        raise HTTPException(500, f"내부 오류: {type(e).__name__}")
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

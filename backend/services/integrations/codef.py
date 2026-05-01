"""Codef.io API 연동 — 한국 법인 은행/카드 자동 pull

데모(development.codef.io) ↔ 프로덕션(api.codef.io) 환경 토글 지원.
프로덕션 사용 시 공동인증서 + 연계 계정 등록 필요.

env vars:
    CODEF_ENV              : "demo" (default, alias: "sandbox") | "production"
    CODEF_CLIENT_ID        : OAuth client id
    CODEF_CLIENT_SECRET    : OAuth client secret
    CODEF_BASE_URL         : override 자동 URL 선택
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import quote, unquote_plus

import httpx
from psycopg2.extensions import connection as PgConnection

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)

# 환경별 base URL — Codef 공식 용어: 데모 / 정식(프로덕션)
CODEF_DEMO_URL = "https://development.codef.io"
CODEF_PRODUCTION_URL = "https://api.codef.io"
# 하위 호환: 이전에 SANDBOX로 부르던 이름
CODEF_SANDBOX_URL = CODEF_DEMO_URL
CODEF_TOKEN_URL = "https://oauth.codef.io/oauth/token"

# Codef 기관 코드
# 주의: 이전에 brute-force로 추정한 lotte=0301 / kb=0311은 뒤바뀐 값이었다.
# Codef 지원팀 확인 결과 0301=KB국민카드, 0311=롯데카드 (2026-04-20 정정).
ORG_CODES = {
    # 은행 — Codef 공식 표준 4자리 (정합 확인됨, demo 환경에서 정상 routing)
    "woori_bank": "0020",
    "ibk_bank": "0003",
    "shinhan_bank": "0088",   # SHB 은행 코드 (한국은행 표준). Codef 도 동일.

    # 카드사 — Codef 공식 표 (https://developer.codef.io/products/card/overview 법인카드 영역).
    # 이전 매핑은 브루트포스 추정으로 4개가 잘못되어 있었음 — 공식 source 로 정정.
    "kb_card": "0301",
    "hyundai_card": "0302",   # ← 0305 에서 정정 (공식: 0302)
    "samsung_card": "0303",
    "nh_card": "0304",        # ← 0306 에서 정정 (공식: 0304)
    "bc_card": "0305",        # ← 0302 에서 정정 (공식: 0305)
    "shinhan_card": "0306",   # ← 0304 에서 정정 (CF-12800 원인). 공식: 0306
    "citi_card": "0307",      # 신규 추가 (씨티카드)
    "woori_card": "0309",
    "lotte_card": "0311",
    "hana_card": "0313",
    "jeonbuk_card": "0315",   # 신규 추가 (전북카드)
    "gwangju_card": "0316",   # 신규 추가 (광주카드)
    "suhyup_card": "0320",    # 신규 추가 (수협카드)
    "jeju_card": "0321",      # 신규 추가 (제주카드)

    "hometax": "0001",        # 국세청 홈택스 (전자세금계산서 통합 조회)
}

# UI 표시명
ORG_LABELS = {
    "woori_bank": "우리은행",
    "ibk_bank": "IBK기업은행",
    "shinhan_bank": "신한은행",
    "kb_card": "KB국민카드",
    "hyundai_card": "현대카드",
    "samsung_card": "삼성카드",
    "nh_card": "NH농협카드",
    "bc_card": "BC카드",
    "shinhan_card": "신한카드",
    "citi_card": "씨티카드",
    "woori_card": "우리카드",
    "lotte_card": "롯데카드",
    "hana_card": "하나카드",
    "jeonbuk_card": "전북카드",
    "gwangju_card": "광주카드",
    "suhyup_card": "수협카드",
    "jeju_card": "제주카드",
}

# 은행/카드 타입 → source_type (mapping rules와 일관성 유지)
BANK_ORGS = {"woori_bank", "ibk_bank", "shinhan_bank"}
CARD_ORGS = {
    "kb_card", "hyundai_card", "samsung_card", "nh_card", "bc_card",
    "shinhan_card", "citi_card", "woori_card", "lotte_card", "hana_card",
    "jeonbuk_card", "gwangju_card", "suhyup_card", "jeju_card",
}
# 공공기관 (홈택스 등) — 세금계산서/사업자/세금신고 결과 등
PUBLIC_ORGS = {"hometax"}

# NPKI cert OU 키워드 → 한글 은행/기관명
_BANK_OU_KEYWORDS = {
    "WOORI": "우리은행",
    "우리은행": "우리은행",
    "IBK": "IBK기업은행",
    "기업은행": "IBK기업은행",
    "KB": "KB국민은행",
    "국민은행": "KB국민은행",
    "SHB": "신한은행",
    "신한은행": "신한은행",
    "HANA": "하나은행",
    "하나은행": "하나은행",
    "NH": "NH농협",
    "농협": "NH농협",
    "BizBank": "신한은행",  # SignKorea + BizBank 조합 = 신한 BizBank
}

SETTINGS_PREFIX = "codef_connected_id_"  # e.g., codef_connected_id_woori_bank
LAST_SYNC_PREFIX = "codef_last_sync_"    # e.g., codef_last_sync_woori_bank


def resolve_base_url() -> str:
    override = os.environ.get("CODEF_BASE_URL", "").strip()
    if override:
        return override
    env = os.environ.get("CODEF_ENV", "demo").strip().lower()
    return CODEF_PRODUCTION_URL if env == "production" else CODEF_DEMO_URL


def is_production() -> bool:
    return os.environ.get("CODEF_ENV", "demo").strip().lower() == "production"


def env_label() -> str:
    """UI 표시용 라벨 — demo | production."""
    return "production" if is_production() else "demo"


def _normalize_public_key_pem(raw: str) -> str:
    """Codef 포털에서 복사한 공개키를 PEM 포맷으로 정규화.

    Codef는 일반적으로 헤더 없는 base64 문자열(raw) 또는 PEM을 제공.
    """
    s = raw.strip()
    if s.startswith("-----BEGIN"):
        return s
    # raw base64 — PEM wrap
    return (
        "-----BEGIN PUBLIC KEY-----\n"
        + "\n".join(s[i:i + 64] for i in range(0, len(s), 64))
        + "\n-----END PUBLIC KEY-----"
    )


def encrypt_password(plain: str, public_key_pem: Optional[str] = None) -> str:
    """Codef 규약에 맞게 비밀번호 암호화: RSA(PKCS1v15) → base64.

    Codef 요구사항: 비밀번호·계정번호 등 민감정보는 Codef 공개키로 RSA 암호화 후
    base64 인코딩. 미암호화 base64만 보내면 Codef가 복호화 실패 → 인증 거절.

    Args:
        plain: 평문 비밀번호
        public_key_pem: PEM 형식 공개키. None이면 env CODEF_PUBLIC_KEY 사용.

    Returns:
        base64-encoded ciphertext string (Codef가 기대하는 포맷).

    Raises:
        CodefError: 공개키 없음/형식 이상/cryptography 미설치.
    """
    if not _CRYPTO_AVAILABLE:
        raise CodefError(
            "cryptography 패키지 미설치 — `pip install cryptography` 후 재시작"
        )

    pem = public_key_pem or os.environ.get("CODEF_PUBLIC_KEY", "").strip()
    if not pem:
        raise CodefError(
            "CODEF_PUBLIC_KEY 미설정 — Codef 포털 → 개발정보 관리 → 공개키 복사 후 .env에 추가"
        )

    try:
        normalized = _normalize_public_key_pem(pem)
        public_key = serialization.load_pem_public_key(normalized.encode("utf-8"))
        ciphertext = public_key.encrypt(plain.encode("utf-8"), padding.PKCS1v15())
        return base64.b64encode(ciphertext).decode("ascii")
    except CodefError:
        raise
    except Exception as e:
        logger.exception("Codef password encryption failed")
        # 진단 hint — pem 길이 + 시작 prefix (값 자체 노출 X)
        hint = (
            f"pem_len={len(pem)} "
            f"starts_BEGIN={pem.lstrip().startswith('-----BEGIN')} "
            f"has_escaped_newline={chr(92) + chr(110) in pem}"
        )
        raise CodefError(
            f"Codef 공개키 처리 실패: {type(e).__name__}: {str(e)[:160]} ({hint})"
        )


class CodefError(Exception):
    """Codef API 오류. transactionId 등 컨텍스트를 포함해 tech 문의에 활용 가능."""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        transaction_id: Optional[str] = None,
        extra_message: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_params: Optional[dict] = None,
        response_body: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.transaction_id = transaction_id
        self.extra_message = extra_message
        self.endpoint = endpoint
        self.request_params = request_params
        self.response_body = response_body

    def to_dict(self) -> dict:
        """UI/로그 직렬화용 — 민감 필드는 호출자가 _mask_sensitive 처리한 dict를 넘길 것."""
        return {
            "message": str(self),
            "code": self.code,
            "transaction_id": self.transaction_id,
            "extra_message": self.extra_message,
            "endpoint": self.endpoint,
            "request_params": self.request_params,
            "response_body": self.response_body,
        }


class CodefClient:
    """Codef API 클라이언트."""

    def __init__(self, client_id: str, client_secret: str, base_url: Optional[str] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url or resolve_base_url()
        self._token: Optional[str] = None
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def close(self):
        self.client.close()

    @property
    def environment(self) -> str:
        return "production" if self.base_url == CODEF_PRODUCTION_URL else "demo"

    # ── 인증 ────────────────────────────────────────────────
    def _get_token(self) -> str:
        if self._token:
            return self._token
        resp = httpx.post(
            CODEF_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=10.0,
        )
        if resp.status_code != 200:
            logger.error("Codef token error: status=%d body=%s", resp.status_code, resp.text)
            raise CodefError("Failed to authenticate with Codef")
        self._token = resp.json().get("access_token")
        if not self._token:
            raise CodefError("No access_token in response")
        return self._token

    def _request(self, endpoint: str, params: dict):
        token = self._get_token()
        # Codef 공식 SDK 패턴: body 전체를 URL-encoded JSON 문자열로 전송
        # (Content-Type: application/json 유지, data=quote(json.dumps(body)))
        body = quote(json.dumps(params, ensure_ascii=False))
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = self.client.post(endpoint, content=body, headers=headers)
        if resp.status_code == 401:
            self._token = None
            token = self._get_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = self.client.post(endpoint, content=body, headers=headers)

        resp.raise_for_status()
        data = _parse_codef_response(resp.text)

        result = data.get("result", {}) if isinstance(data, dict) else {}
        result_code = result.get("code", "")
        result_tx_id = result.get("transactionId")  # Codef tech 문의 식별자
        body = data.get("data", {}) if isinstance(data, dict) else {}
        masked_params = _mask_sensitive(params)

        # /v1/account/create 는 부분 성공 가능 — errorList에 실패 기관별 사유
        # result.code=CF-00000이어도 errorList에 내용 있을 수 있음 (부분 성공)
        error_list = body.get("errorList") if isinstance(body, dict) else None
        if error_list:
            first = error_list[0]
            item_code = first.get("code", "")
            item_msg = first.get("message", "")
            item_extra = first.get("extraMessage", "")
            item_tx_id = first.get("transactionId") or result_tx_id
            logger.warning(
                "Codef per-account error: code=%s msg=%s extra=%s tx=%s payload=%s",
                item_code, item_msg, item_extra, item_tx_id, masked_params,
            )
            full = f"{item_code} - {item_msg}"
            if item_extra:
                full += f" | {item_extra}"
            if item_tx_id:
                full += f" | tx={item_tx_id}"
            raise CodefError(
                f"Codef 계정 등록 실패: {full}",
                code=item_code or None,
                transaction_id=item_tx_id,
                extra_message=item_extra or None,
                endpoint=endpoint,
                request_params=masked_params,
                response_body=data,
            )

        if result_code != "CF-00000":
            msg = result.get("message", "")
            extra = result.get("extraMessage", "") or result.get("extraInfo", "")
            logger.warning(
                "Codef non-OK response: code=%s msg=%s extra=%s tx=%s endpoint=%s payload=%s data=%s",
                result_code, msg, extra, result_tx_id, endpoint, masked_params, body,
            )
            full_msg = f"{result_code} - {msg}"
            if extra:
                full_msg += f" | {extra}"
            if result_tx_id:
                full_msg += f" | tx={result_tx_id}"
            raise CodefError(
                f"Codef error: {full_msg}",
                code=result_code or None,
                transaction_id=result_tx_id,
                extra_message=extra or None,
                endpoint=endpoint,
                request_params=masked_params,
                response_body=data,
            )
        # data는 dict 또는 list 모두 가능 (예: card-list는 list)
        return body if body is not None else {}

    # ── connected_id 관리 ───────────────────────────────────
    def create_connected_id(self, accounts: list[dict]) -> str:
        """연계 계정 등록 → connected_id 발급.

        Args:
            accounts: [
                {
                    "countryCode": "KR",
                    "businessType": "BK" | "CD",
                    "organization": "0020",
                    "loginType": "0" | "1",   # 0=cert, 1=id/pw
                    "id": "...",              # id/pw 인증 시
                    "password": "...",        # base64 encoded
                    "clientType": "B" | "P",  # B=법인, P=개인
                    # 인증서 로그인 시
                    "certType": "...",
                    "certFile": "...",        # base64
                    "certPassword": "...",    # base64
                },
                ...
            ]

        프로덕션에선 공동인증서 파일이 base64 encoded로 전송됨.
        샌드박스에선 Codef 테스트 계정 id/pw로 검증 가능.
        """
        data = self._request(
            "/v1/account/create",
            {"accountList": accounts},
        )
        connected_id = data.get("connectedId", "")
        if not connected_id:
            raise CodefError("No connectedId in create response")
        return connected_id

    # ── 은행 ────────────────────────────────────────────────
    def get_bank_account_list(self, connected_id: str, org: str = "woori_bank") -> dict:
        """은행 보유계좌 조회. 첫 호출로 계좌번호 확보 후 거래내역 조회 가능.

        org: BANK_ORGS 중 하나 — woori_bank | ibk_bank | shinhan_bank
        """
        if org not in BANK_ORGS:
            raise CodefError(f"unsupported bank org: {org}")
        return self._request(
            "/v1/kr/bank/b/account/account-list",
            {"connectedId": connected_id, "organization": ORG_CODES[org]},
        )

    def get_bank_transactions(
        self,
        connected_id: str,
        start_date: str,
        end_date: str,
        account: str,
        order_by: str = "0",
        inquiry_type: str = "1",
        org: str = "woori_bank",
    ) -> list[dict]:
        """법인 은행 거래내역 조회 (YYYYMMDD).

        Args:
            account: 계좌번호 (하이픈 제거 13자리)
            order_by: '0'=오래된순, '1'=최신순
            inquiry_type: '1'=일반조회 (default)
            org: 은행 식별자 (BANK_ORGS)
        """
        if org not in BANK_ORGS:
            raise CodefError(f"unsupported bank org: {org}")
        return self._request(
            "/v1/kr/bank/b/account/transaction-list",
            {
                "connectedId": connected_id,
                "organization": ORG_CODES[org],
                "account": account,
                "startDate": start_date,
                "endDate": end_date,
                "orderBy": order_by,
                "inquiryType": inquiry_type,
            },
        ).get("resTrHistoryList", [])

    def sync_bank_transactions(
        self,
        conn: PgConnection,
        entity_id: int,
        connected_id: str,
        start_date: str,
        end_date: str,
        account: Optional[str] = None,
        org: str = "woori_bank",
    ) -> dict:
        """은행 거래를 transactions 테이블에 동기화.

        account 미지정 시 계좌목록 조회 후 첫 KRW 입출금 계좌 자동 사용.
        org 별로 source_type='codef_{org}' (woori/ibk/shinhan).
        """
        if org not in BANK_ORGS:
            raise CodefError(f"unsupported bank org: {org}")
        source_type = f"codef_{org}"
        if not account:
            acct_list = self.get_bank_account_list(connected_id, org=org)
            deposit = acct_list.get("resDepositTrust", [])
            if not deposit:
                raise CodefError("등록된 입출금 계좌 없음")
            account = deposit[0]["resAccount"]

        raw_list = self.get_bank_transactions(
            connected_id, start_date, end_date, account=account, org=org,
        )
        cur = conn.cursor()
        synced = 0
        duplicates = 0
        auto_mapped = 0

        # 잔고 추적 (Excel 파서와 동일 — balance_snapshots 자동 갱신)
        # daily_balance: 일자별 EOD 잔고 = orderBy="0"(오래된순)이라 같은 date 의 마지막 거래의 balance_after.
        # 모든 일자 EOD snapshot 을 INSERT 해야 cashflow 의 월말/기초잔고가 정확.
        latest_balance = None
        latest_balance_date = None
        daily_balance: dict = {}

        # 자동 매핑 (lazy import — 순환 회피)
        from backend.services.mapping_service import auto_map_transaction

        for item in raw_list:
            tx = _normalize_bank_row(item)
            if not tx:
                continue

            # 잔고 — orderBy="0"(오래된순)이라 마지막 row가 가장 최신
            if tx.get("balance_after") is not None:
                latest_balance = tx["balance_after"]
                latest_balance_date = tx["date"]
                # 같은 date 내에서는 마지막 거래의 balance_after = EOD (이 루프가 그 값을 덮어씀)
                daily_balance[tx["date"]] = tx["balance_after"]

            if _is_duplicate(cur, entity_id, tx, source_type):
                duplicates += 1
                continue

            # 체크카드 cross-dedup: 우리은행 '체크우리' 메모는 우리카드 결제와 매핑되어
            # Excel 업로드 정책상 은행쪽 row 를 skip. 신한/IBK 는 해당 패턴 없음 (현재까진).
            is_check_card_memo = (org == "woori_bank" and tx.get("memo") == "체크우리")
            if is_check_card_memo:
                cur.execute(
                    """
                    SELECT id FROM transactions
                    WHERE entity_id = %s AND date = %s AND amount = %s
                      AND source_type IN ('woori_card', 'codef_woori_card')
                    LIMIT 1
                    """,
                    [entity_id, tx["date"], float(tx["amount"])],
                )
                if cur.fetchone():
                    duplicates += 1
                    continue

            # mapping_rules cascade 시도
            mapping = auto_map_transaction(
                cur,
                entity_id=entity_id,
                counterparty=tx["counterparty"],
                description=tx["description"],
            )

            if mapping:
                auto_mapped += 1
                cur.execute(
                    """
                    INSERT INTO transactions
                        (entity_id, date, amount, currency, type, description,
                         counterparty, source_type, is_confirmed, is_cancel, note,
                         internal_account_id, standard_account_id,
                         mapping_confidence, mapping_source)
                    VALUES (%s, %s, %s, 'KRW', %s, %s, %s, %s, FALSE, FALSE, %s,
                            %s, %s, %s, %s)
                    """,
                    [
                        entity_id, tx["date"], float(tx["amount"]),
                        tx["type"], tx["description"], tx["counterparty"],
                        source_type,
                        "체크카드" if is_check_card_memo else None,
                        mapping["internal_account_id"], mapping.get("standard_account_id"),
                        mapping.get("confidence"), mapping.get("match_type"),
                    ],
                )
            else:
                cur.execute(
                    """
                    INSERT INTO transactions
                        (entity_id, date, amount, currency, type, description,
                         counterparty, source_type, is_confirmed, is_cancel, note)
                    VALUES (%s, %s, %s, 'KRW', %s, %s, %s, %s, FALSE, FALSE, %s)
                    """,
                    [
                        entity_id, tx["date"], float(tx["amount"]),
                        tx["type"], tx["description"], tx["counterparty"],
                        source_type,
                        "체크카드" if is_check_card_memo else None,
                    ],
                )
            synced += 1

        # balance_snapshots 자동 저장 — sync 한 모든 일자의 EOD 잔고 upsert
        # 이전 코드는 가장 최근 1건만 저장 → cashflow 의 월말/기초잔고가 부정확.
        # 이제 일자별 EOD snapshot 모두 INSERT → get_opening_balance 가 정확한 월초 잔고 조회 가능.
        balance_saved = False
        snapshots_upserted = 0
        if daily_balance:
            account_name = f"{ORG_LABELS.get(org, org)} 법인통장"
            for d, bal in daily_balance.items():
                cur.execute(
                    """
                    INSERT INTO balance_snapshots
                        (entity_id, date, account_name, account_type, balance, currency, source)
                    VALUES (%s, %s, %s, 'bank', %s, 'KRW', 'codef_api')
                    ON CONFLICT (entity_id, date, account_name)
                    DO UPDATE SET balance = EXCLUDED.balance, source = 'codef_api'
                    """,
                    [entity_id, d, account_name, bal],
                )
                snapshots_upserted += 1
            balance_saved = True

        cur.close()
        logger.info(
            "Codef bank sync: entity=%d, fetched=%d, synced=%d, dup=%d, auto_mapped=%d, bal=%s",
            entity_id, len(raw_list), synced, duplicates, auto_mapped, balance_saved,
        )
        return {
            "synced": synced,
            "duplicates": duplicates,
            "auto_mapped": auto_mapped,
            "unmapped": synced - auto_mapped,
            "total_fetched": len(raw_list),
            "environment": self.environment,
            "account": account,
            "balance_snapshot": {
                "saved": balance_saved,
                "snapshots_upserted": snapshots_upserted,
                "balance": float(latest_balance) if latest_balance else None,
                "date": str(latest_balance_date) if latest_balance_date else None,
            },
        }

    # ── 카드 ────────────────────────────────────────────────
    def get_card_list(self, connected_id: str, card_type: str) -> list[dict]:
        """등록된 카드 목록 조회 — 카드번호·이름·종류 포함.

        Codef 응답 예시:
            [{
                "resCardName": "CORPORATE Classic",
                "resCardNo": "5275********1840",
                "resCardType": "신용",
                "resUserNm": "주식회사 한아원",
                "resSleepYN": "N",
            }, ...]
        """
        org_code = ORG_CODES.get(card_type)
        if not org_code:
            raise CodefError(f"Unknown card type: {card_type}")
        data = self._request(
            "/v1/kr/card/b/account/card-list",
            {"connectedId": connected_id, "organization": org_code},
        )
        return data if isinstance(data, list) else []

    def get_card_approvals(
        self,
        connected_id: str,
        start_date: str,
        end_date: str,
        card_type: str = "lotte_card",
        card_no: Optional[str] = None,
    ) -> list[dict]:
        """카드 승인내역 조회.

        Args:
            card_type: ORG_CODES 키 (lotte_card 등)
            card_no: 카드번호 (마스킹 가능, 예: '5275********1840').
                     None이면 첫번째 보유카드 자동 선택.
        """
        org_code = ORG_CODES.get(card_type)
        if not org_code:
            raise CodefError(f"Unknown card type: {card_type}")

        if not card_no:
            cards = self.get_card_list(connected_id, card_type)
            if not cards:
                raise CodefError(f"{card_type} 보유 카드 없음")
            card_no = cards[0]["resCardNo"]

        data = self._request(
            "/v1/kr/card/b/account/approval-list",
            {
                "connectedId": connected_id,
                "organization": org_code,
                "startDate": start_date,
                "endDate": end_date,
                "inquiryType": "0",
                "orderBy": "0",
                "cardNo": card_no,
            },
        )
        # Codef 카드 응답: data가 list 직접이거나 dict.resApprovalList
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("resApprovalList", [])
        return []

    def get_card_billings(
        self,
        connected_id: str,
        start_month: str,
        end_month: str,
        card_type: str,
    ) -> list[dict]:
        """카드 청구서 조회 (월별 결제 명세).

        Codef endpoint: /v1/kr/card/b/account/billing-list
        Args:
            start_month / end_month: 'YYYYMM' (조회 청구월 범위)
            card_type: ORG_CODES 키 (lotte_card 등)
        """
        org_code = ORG_CODES.get(card_type)
        if not org_code:
            raise CodefError(f"Unknown card type: {card_type}")
        data = self._request(
            "/v1/kr/card/b/account/billing-list",
            {
                "connectedId": connected_id,
                "organization": org_code,
                "startMonth": start_month,
                "endMonth": end_month,
                "inquiryType": "0",
            },
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Codef 응답 구조 다양 — 일반적으로 resBillingList
            return data.get("resBillingList") or data.get("resCardBillList") or []
        return []

    def sync_card_billings(
        self,
        conn: PgConnection,
        entity_id: int,
        connected_id: str,
        start_month: str,
        end_month: str,
        card_type: str,
    ) -> dict:
        """카드 청구서를 card_billings 테이블에 동기화.

        같은 (entity, card_org, card_no_masked, billing_month) 는 UPSERT.
        """
        if card_type not in CARD_ORGS:
            raise CodefError(f"unsupported card org: {card_type}")
        billings = self.get_card_billings(
            connected_id, start_month, end_month, card_type,
        )
        cur = conn.cursor()
        upserted = 0
        for raw in billings:
            norm = _normalize_card_billing_row(raw, card_type)
            if not norm:
                continue
            cur.execute(
                """
                INSERT INTO card_billings (
                    entity_id, card_org, card_no_masked, billing_month,
                    billing_date, settlement_date,
                    total_amount, principal_amount, installment_amount, interest_amount,
                    currency, status, raw_data, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'KRW', 'pending', %s, NOW())
                ON CONFLICT (entity_id, card_org, card_no_masked, billing_month) DO UPDATE SET
                    billing_date = EXCLUDED.billing_date,
                    settlement_date = EXCLUDED.settlement_date,
                    total_amount = EXCLUDED.total_amount,
                    principal_amount = EXCLUDED.principal_amount,
                    installment_amount = EXCLUDED.installment_amount,
                    interest_amount = EXCLUDED.interest_amount,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
                """,
                [
                    entity_id, card_type, norm["card_no_masked"], norm["billing_month"],
                    norm.get("billing_date"), norm.get("settlement_date"),
                    norm["total_amount"],
                    norm.get("principal_amount"),
                    norm.get("installment_amount"),
                    norm.get("interest_amount"),
                    json.dumps(raw, ensure_ascii=False),
                ],
            )
            upserted += 1
        conn.commit()
        cur.close()
        return {
            "fetched": len(billings),
            "upserted": upserted,
            "card_org": card_type,
            "period": f"{start_month}~{end_month}",
            "environment": self.environment,
        }

    def sync_card_approvals(
        self,
        conn: PgConnection,
        entity_id: int,
        connected_id: str,
        start_date: str,
        end_date: str,
        card_type: str = "lotte_card",
    ) -> dict:
        """카드 승인내역 → transactions 동기화.

        취소건은 type='in' + is_cancel=TRUE로 삽입 (환불 처리).
        """
        if card_type not in CARD_ORGS:
            raise CodefError(f"Unknown card type: {card_type}")

        # 등록된 모든 카드 자동 발견 → 카드별 승인내역 통합
        cards = self.get_card_list(connected_id, card_type)
        if not cards:
            raise CodefError(f"{card_type}: 보유 카드 없음 (card-list 빈 응답)")

        raw_list: list[dict] = []
        cards_summary: list[dict] = []
        for card in cards:
            card_no = card.get("resCardNo", "")
            card_name = card.get("resCardName", "")
            try:
                approvals = self.get_card_approvals(
                    connected_id, start_date, end_date, card_type, card_no=card_no,
                )
            except CodefError as e:
                logger.warning("card %s (%s) approval-list 실패: %s", card_no, card_name, e)
                approvals = []
            # 각 row에 카드 식별 메타 부착
            for a in approvals:
                a["_codefCardNo"] = card_no
                a["_codefCardName"] = card_name
            raw_list.extend(approvals)
            cards_summary.append({
                "card_no": card_no, "card_name": card_name,
                "fetched": len(approvals),
            })

        source_type = f"codef_{card_type}"

        cur = conn.cursor()
        synced = 0
        duplicates = 0
        cancels = 0
        auto_mapped = 0
        check_card_cancelled = 0

        # 자동 매핑 (Excel 업로드와 동일한 후속 작업)
        from backend.services.mapping_service import auto_map_transaction

        for item in raw_list:
            tx = _normalize_card_row(item)
            if not tx:
                continue

            if _is_duplicate(cur, entity_id, tx, source_type):
                duplicates += 1
                continue

            # member_id 매칭 (이름 → 카드번호 fallback)
            member_id = None
            if tx.get("member_name"):
                cur.execute(
                    "SELECT id FROM members WHERE entity_id = %s AND name = %s LIMIT 1",
                    [entity_id, tx["member_name"]],
                )
                row = cur.fetchone()
                if row:
                    member_id = row[0]
            if member_id is None and tx.get("card_number"):
                # 1) 정확 매칭 (같은 포맷으로 등록된 케이스)
                cur.execute(
                    "SELECT id FROM members WHERE entity_id = %s AND %s = ANY(card_numbers) AND is_active = true LIMIT 1",
                    [entity_id, tx["card_number"]],
                )
                row = cur.fetchone()
                if row:
                    member_id = row[0]
                else:
                    # 2) 뒤 3자리 fallback — Codef는 '5105*********477' (뒤 3),
                    #    members는 보통 '****5477' (뒤 4) 형식으로 등록됨.
                    #    공통 접미사인 뒤 3자리로 매칭 시도.
                    card_num = tx["card_number"]
                    if card_num and len(card_num) >= 3:
                        tail3 = card_num[-3:]
                        cur.execute(
                            """
                            SELECT id FROM members
                            WHERE entity_id = %s AND is_active = true
                              AND EXISTS (
                                SELECT 1 FROM unnest(card_numbers) cn
                                WHERE RIGHT(cn, 3) = %s
                              )
                            ORDER BY id
                            LIMIT 1
                            """,
                            [entity_id, tail3],
                        )
                        row = cur.fetchone()
                        if row:
                            member_id = row[0]

            # 자동 매핑
            mapping = auto_map_transaction(
                cur,
                entity_id=entity_id,
                counterparty=tx["counterparty"],
                description=tx["description"],
            )

            if mapping:
                auto_mapped += 1
                cur.execute(
                    """
                    INSERT INTO transactions
                        (entity_id, date, amount, currency, type, description,
                         counterparty, source_type, is_confirmed,
                         card_number, parsed_member_name, is_cancel,
                         member_id, internal_account_id, standard_account_id,
                         mapping_confidence, mapping_source)
                    VALUES (%s, %s, %s, 'KRW', %s, %s, %s, %s, FALSE,
                            %s, %s, %s,
                            %s, %s, %s, %s, %s)
                    """,
                    [
                        entity_id, tx["date"], float(tx["amount"]),
                        tx["type"], tx["description"], tx["counterparty"],
                        source_type,
                        tx["card_number"], tx["member_name"], tx["is_cancel"],
                        member_id,
                        mapping["internal_account_id"], mapping.get("standard_account_id"),
                        mapping.get("confidence"), mapping.get("match_type"),
                    ],
                )
            else:
                cur.execute(
                    """
                    INSERT INTO transactions
                        (entity_id, date, amount, currency, type, description,
                         counterparty, source_type, is_confirmed,
                         card_number, parsed_member_name, is_cancel, member_id)
                    VALUES (%s, %s, %s, 'KRW', %s, %s, %s, %s, FALSE,
                            %s, %s, %s, %s)
                    """,
                    [
                        entity_id, tx["date"], float(tx["amount"]),
                        tx["type"], tx["description"], tx["counterparty"],
                        source_type,
                        tx["card_number"], tx["member_name"], tx["is_cancel"],
                        member_id,
                    ],
                )
            synced += 1
            if tx["is_cancel"]:
                cancels += 1

            # 우리카드면 같은 (date, amount)의 우리은행 '체크우리' 행 자동 취소
            # (Excel 업로더와 동일 정책)
            if card_type == "woori_card":
                cur.execute(
                    """
                    UPDATE transactions SET is_cancel = true, updated_at = NOW()
                    WHERE entity_id = %s AND date = %s AND amount = %s
                      AND source_type IN ('woori_bank', 'codef_woori_bank')
                      AND description LIKE '체크우리%%'
                      AND is_cancel IS NOT TRUE
                    """,
                    [entity_id, tx["date"], float(tx["amount"])],
                )
                check_card_cancelled += cur.rowcount

        cur.close()
        logger.info(
            "Codef card sync: entity=%d, card=%s, cards=%d, fetched=%d, synced=%d, dup=%d, cancel=%d, auto_mapped=%d, check_cancelled=%d",
            entity_id, card_type, len(cards), len(raw_list), synced, duplicates, cancels, auto_mapped, check_card_cancelled,
        )
        return {
            "card_type": card_type,
            "cards_count": len(cards),
            "cards": cards_summary,
            "synced": synced,
            "duplicates": duplicates,
            "cancels": cancels,
            "auto_mapped": auto_mapped,
            "unmapped": synced - auto_mapped,
            "check_card_cancelled": check_card_cancelled,
            "total_fetched": len(raw_list),
            "environment": self.environment,
        }

    # ── 홈택스 전자세금계산서 ───────────────────────────────────

    def get_tax_invoices(
        self,
        connected_id: str,
        start_date: str,
        end_date: str,
        *,
        query_type: str = "3",  # '1'=매출, '2'=매입, '3'=전체
    ) -> list[dict]:
        """국세청 홈택스 전자세금계산서 통합조회.

        path: /v1/kr/public/nt/tax-invoice/integrated-check-list
        organization: 0001 (국세청)

        Args:
            connected_id: 홈택스 connected_id (사업자 인증서 등록 후 발급).
            start_date / end_date: YYYYMMDD.
            query_type: 1=매출, 2=매입, 3=전체.

        Returns: list[dict] — 각 row 의 표준화 전 raw 응답.
        """
        data = self._request(
            "/v1/kr/public/nt/tax-invoice/integrated-check-list",
            {
                "connectedId": connected_id,
                "organization": ORG_CODES["hometax"],
                "startDate": start_date,
                "endDate": end_date,
                "type": query_type,  # 매출/매입/전체
                # 영세율여부, 일반/위수탁 등은 기본값 사용
            },
        )
        # Codef 응답: list 직접 또는 dict.resTaxInvoiceList
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("resTaxInvoiceList", "resInvoiceList", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def sync_tax_invoices(
        self,
        conn: PgConnection,
        entity_id: int,
        connected_id: str,
        start_date: str,
        end_date: str,
        *,
        query_type: str = "3",
        our_biz_no: Optional[str] = None,
    ) -> dict:
        """홈택스 세금계산서 → invoices 테이블 동기화.

        - direction 자동 판별: our_biz_no(우리 사업자번호) 가 공급자=sales,
          공급받는자=purchase. 미일치 → 'unknown' (사용자 결정 필요).
        - 중복 감지: (entity_id, document_no, issue_date).
        - 응답 필드는 _normalize_tax_invoice_row 가 표준화.
        """
        raw_list = self.get_tax_invoices(
            connected_id, start_date, end_date, query_type=query_type,
        )
        cur = conn.cursor()
        inserted = 0
        duplicates = 0
        skipped = 0
        unknown = 0
        try:
            for raw in raw_list:
                try:
                    norm = _normalize_tax_invoice_row(raw, our_biz_no=our_biz_no)
                except Exception as e:
                    logger.warning("tax invoice normalize failed: %s | row=%s", e, raw)
                    skipped += 1
                    continue
                if norm is None:
                    skipped += 1
                    continue

                # 중복 감지
                if norm["document_no"]:
                    cur.execute(
                        """
                        SELECT id FROM invoices
                        WHERE entity_id = %s AND document_no = %s AND issue_date = %s
                        LIMIT 1
                        """,
                        [entity_id, norm["document_no"], norm["issue_date"]],
                    )
                    if cur.fetchone():
                        duplicates += 1
                        continue

                if norm["direction"] == "unknown":
                    unknown += 1

                cur.execute(
                    """
                    INSERT INTO invoices (
                        entity_id, direction, counterparty, counterparty_biz_no,
                        issue_date, due_date, document_no,
                        amount, vat, total, currency,
                        description, status, raw_data, source_kind
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'KRW', %s, 'open', %s, 'tax_invoice')
                    """,
                    [
                        entity_id, norm["direction"], norm["counterparty"],
                        norm["counterparty_biz_no"],
                        norm["issue_date"], norm["due_date"], norm["document_no"],
                        norm["amount"], norm["vat"], norm["total"],
                        norm["description"],
                        json.dumps(raw, ensure_ascii=False),
                    ],
                )
                inserted += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

        return {
            "fetched": len(raw_list),
            "inserted": inserted,
            "duplicates": duplicates,
            "skipped": skipped,
            "unknown_direction": unknown,
            "query_type": query_type,
            "environment": self.environment,
        }


# ── Codef 응답 파싱 ─────────────────────────────────────


_SENSITIVE_KEYS = {"password", "certPassword", "accountPassword", "id"}


def _mask_sensitive(payload: dict) -> dict:
    """password·id 등 민감 필드 로그용 마스킹."""
    def mask(obj):
        if isinstance(obj, dict):
            return {k: ("***" if k in _SENSITIVE_KEYS and v else mask(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [mask(x) for x in obj]
        return obj
    try:
        return mask(payload)
    except Exception:
        return {"_masked": True}


def _parse_codef_response(raw: str) -> dict:
    """Codef API 응답 파싱 — URL-encoded JSON 특이사항 대응.

    Codef는 응답 body를 form-encoded JSON 문자열로 반환 (예: '%7B...', '+'=공백).
    unquote_plus로 '+' → 공백, '%XX' → 실제 문자 변환 후 json.loads.
    """
    if not raw:
        raise CodefError("Empty response from Codef")
    text = raw
    if text.lstrip().startswith("%"):
        text = unquote_plus(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(unquote_plus(raw))
        except json.JSONDecodeError as e:
            snippet = raw[:200]
            logger.error("Codef response not parseable: %s", snippet)
            raise CodefError(f"Codef 응답 파싱 실패: {snippet[:100]}") from e


# ── 정규화 헬퍼 ───────────────────────────────────────────


def _parse_codef_date(raw: str) -> Optional[str]:
    """YYYYMMDD → YYYY-MM-DD."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # already ISO
    if len(s) == 10 and s[4] == "-":
        return s
    return None


def _parse_amount(raw: Any) -> Decimal:
    """'1,234,567' | '1234567' | Decimal-compatible → Decimal. 음수/빈값 → 0."""
    if raw is None or raw == "":
        return Decimal("0")
    s = str(raw).replace(",", "").strip()
    if not s:
        return Decimal("0")
    try:
        return abs(Decimal(s))
    except (ValueError, ArithmeticError):
        return Decimal("0")


def _mask_card_number(raw: str) -> Optional[str]:
    """카드번호 마스킹 — 뒤 4자리만 보존."""
    if not raw:
        return None
    s = raw.strip().replace("-", "").replace("*", "")
    if len(s) < 4:
        return None
    return f"****{s[-4:]}"


def _normalize_bank_row(item: dict) -> Optional[dict]:
    """Codef 우리은행 응답 → 정규화된 dict.

    실제 Codef 응답 구조 (우리은행 기업, 0020):
        resAccountTrDate: YYYYMMDD 거래일
        resAccountTrTime: HHMMSS 거래시각
        resAccountIn:  입금액 ("0" 또는 금액 문자열)
        resAccountOut: 출금액 ("0" 또는 금액 문자열)
        resAccountDesc1: (대부분 비어있음)
        resAccountDesc2: 적요 (예: '인터넷', '체크우리') — Excel '적요'에 해당
        resAccountDesc3: 거래처명 — Excel '기재내용'에 해당
        resAccountDesc4: 영업점/지점 (예: '아크로비스타금융센터')
        resAfterTranBalance: 거래 후 잔액

    Excel 파서와 일관된 필드 매핑:
        memo = Desc2, counterparty = Desc3, description = "memo counterparty"
    """
    tx_date = _parse_codef_date(str(item.get("resAccountTrDate", "")))
    if not tx_date:
        return None

    in_amount = _parse_amount(item.get("resAccountIn", ""))
    out_amount = _parse_amount(item.get("resAccountOut", ""))

    # in/out 둘 다 0이면 의미 없음
    if in_amount == 0 and out_amount == 0:
        return None

    if in_amount > 0:
        amount = in_amount
        tx_type = "in"
    else:
        amount = out_amount
        tx_type = "out"

    desc2 = str(item.get("resAccountDesc2", "") or "").strip()  # 적요/메모
    desc3 = str(item.get("resAccountDesc3", "") or "").strip()  # 거래처
    desc4 = str(item.get("resAccountDesc4", "") or "").strip()  # 영업점

    counterparty = desc3 or desc4 or desc2 or "(미확인)"
    description = f"{desc2} {desc3}".strip() or counterparty

    balance_after = _parse_amount(item.get("resAfterTranBalance", ""))

    return {
        "date": tx_date,
        "amount": amount,
        "type": tx_type,
        "description": description[:500],
        "counterparty": counterparty[:200],
        "memo": desc2[:100] or None,
        "branch": desc4[:100] or None,
        "balance_after": float(balance_after) if balance_after > 0 else None,
    }


def _normalize_card_row(item: dict) -> Optional[dict]:
    """Codef 카드 승인내역 응답 → 정규화.

    주요 필드 (공통):
        resUsedDate: YYYYMMDD 승인일
        resUsedAmount: 승인금액 (KRW)
        resMemberStoreName: 가맹점명
        resCancelYN: "1"=취소, "0"=승인 (카드사마다 다를 수 있음)
        resCardNo: 카드번호 (masked)
        resUserName / resMemberName: 이용자명
    """
    tx_date = _parse_codef_date(str(item.get("resUsedDate", "")))
    if not tx_date:
        return None

    amount = _parse_amount(item.get("resUsedAmount"))
    if amount == 0:
        # 해외결제 — resUsedAmount USD일 수 있음. 원화 필드 fallback.
        amount = _parse_amount(item.get("resTotalAmount"))
    if amount == 0:
        return None

    # 취소 판정 — "1" | "Y" | "취소"
    cancel_raw = str(item.get("resCancelYN", "") or item.get("resCancelStatus", "")).strip().upper()
    is_cancel = cancel_raw in ("1", "Y", "취소", "CANCEL")

    counterparty = str(
        item.get("resMemberStoreName", "")
        or item.get("resMerchantName", "")
        or "(미확인)"
    ).strip()

    # 카드번호: API 응답 자체가 마스킹된 형태 (예: 5275********1840)
    raw_card = str(item.get("resCardNo") or item.get("_codefCardNo") or "").strip()
    card_no = raw_card if raw_card else None
    member = str(item.get("resUserName", "") or item.get("resMemberName", "")).strip() or None

    description = counterparty + (" (취소)" if is_cancel else "")

    return {
        "date": tx_date,
        "amount": amount,
        "type": "in" if is_cancel else "out",  # 취소 = 환불 유입
        "description": description[:500],
        "counterparty": counterparty[:200],
        "card_number": card_no,
        "member_name": member,
        "is_cancel": is_cancel,
    }


def _normalize_biz_no(s: Optional[str]) -> str:
    """사업자번호 정규화 (digits only)."""
    if not s:
        return ""
    return "".join(c for c in str(s) if c.isdigit())


def _normalize_card_billing_row(item: dict, card_type: str) -> Optional[dict]:
    """카드 청구서 row 정규화.

    Codef 카드 청구서 응답 필드는 카드사별로 다름. 공통적으로:
      - resCardNo / resCardNumber
      - resBillingMonth / resPaymentMonth (YYYYMM)
      - resBillingDate (YYYYMMDD) / resPaymentDate (출금일)
      - resTotalAmount / resPaymentAmount (청구 총액)
      - resPrincipalAmount / resInstallmentBalance / resInterest
    """
    # 카드번호 — 마스킹 4자리 추출
    raw_card = (
        item.get("resCardNo") or item.get("resCardNumber")
        or item.get("resAccount") or ""
    )
    digits = "".join(c for c in str(raw_card) if c.isdigit())
    card_no_masked = f"****{digits[-4:]}" if len(digits) >= 4 else (str(raw_card)[:20] if raw_card else "")

    # 청구월 (YYYYMM)
    bm = (
        item.get("resBillingMonth") or item.get("resPaymentMonth")
        or item.get("resBillingYear", "") + item.get("resBillingMonthOnly", "")
    )
    bm = str(bm).strip() if bm else ""
    if not bm:
        # billing_date 에서 추정
        bd = item.get("resBillingDate") or item.get("resPaymentDate") or ""
        if isinstance(bd, str) and len(bd) >= 6:
            bm = bd[:6]
    if not bm or len(bm) < 6:
        return None  # 청구월 식별 불가 → skip

    def _parse_date(v):
        if not v:
            return None
        s = str(v).strip()
        if len(s) == 8 and s.isdigit():
            try:
                return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            except ValueError:
                return None
        return None

    def _amount(v) -> Decimal:
        if v is None or v == "":
            return Decimal("0")
        try:
            return Decimal(str(v).replace(",", ""))
        except Exception:
            return Decimal("0")

    return {
        "card_no_masked": card_no_masked,
        "billing_month": bm[:6],
        "billing_date": _parse_date(item.get("resBillingDate")),
        "settlement_date": _parse_date(
            item.get("resPaymentDate") or item.get("resSettlementDate")
        ),
        "total_amount": _amount(
            item.get("resTotalAmount") or item.get("resPaymentAmount")
        ),
        "principal_amount": _amount(item.get("resPrincipalAmount")) or None,
        "installment_amount": _amount(item.get("resInstallmentBalance")) or None,
        "interest_amount": _amount(item.get("resInterest") or item.get("resFee")) or None,
    }


def _normalize_tax_invoice_row(item: dict, our_biz_no: Optional[str] = None) -> Optional[dict]:
    """홈택스 전자세금계산서 row → invoices 테이블 컬럼 매핑.

    Codef 응답 필드 (홈택스 통합조회):
    - resIssueDate / resWriteDate: 작성일자 (YYYYMMDD)
    - resApprovalNo / resIssueId: 승인번호
    - resFranchiseeRegNum / resInvoicerRegNum: 공급자 사업자번호
    - resInvoicerName / resInvoicerCorpName: 공급자 상호
    - resTrusteeRegNum / resInvoiceeRegNum: 공급받는자 사업자번호
    - resTrusteeName / resInvoiceeCorpName: 공급받는자 상호
    - resSupplyAmount / resAmount: 공급가액
    - resTaxAmount: 세액
    - resTotalAmount / resSumAmount: 합계
    - resType / resTaxInvoiceType: 종류 (사용 안 함, direction 은 our_biz_no 로 결정)

    필드명이 product 마다 다를 수 있어 fallback chain 으로 fetch.
    """
    def pick(*keys, default=""):
        for k in keys:
            v = item.get(k)
            if v is not None and str(v).strip() != "":
                return v
        return default

    issue_raw = pick("resIssueDate", "resWriteDate", "resCreateDate", "resApproveDate")
    issue_date = _parse_codef_date(str(issue_raw)) if issue_raw else None
    if not issue_date:
        return None  # 발행일 없으면 invoice 만들 수 없음

    document_no = str(pick("resApprovalNo", "resIssueId", "resInvoiceNo", "resTaxInvoiceNo") or "").strip() or None

    # 공급자/공급받는자
    seller_biz = _normalize_biz_no(str(pick(
        "resFranchiseeRegNum", "resInvoicerRegNum", "resBusinessIssuerNum",
        "resSupplierRegNum",
    )))
    buyer_biz = _normalize_biz_no(str(pick(
        "resTrusteeRegNum", "resInvoiceeRegNum", "resBusinessRecipientNum",
        "resReceiverRegNum",
    )))
    seller_name = str(pick("resInvoicerName", "resInvoicerCorpName", "resSupplierName") or "").strip()
    buyer_name = str(pick("resTrusteeName", "resInvoiceeCorpName", "resReceiverName") or "").strip()

    amount = _parse_amount(pick("resSupplyAmount", "resAmount", "resSupply", "resSupplyValue", default="0"))
    vat = _parse_amount(pick("resTaxAmount", "resVAT", default="0"))
    total = _parse_amount(pick("resTotalAmount", "resSumAmount", "resTotal", default="0"))
    if total == Decimal("0"):
        total = amount + vat
    if amount == Decimal("0") and total == Decimal("0"):
        return None  # 금액 0 — 의미 없는 row

    # direction 자동 판별
    our_clean = _normalize_biz_no(our_biz_no)
    if our_clean and seller_biz == our_clean:
        direction = "sales"
        counterparty = buyer_name or "(거래처 미상)"
        counterparty_biz = buyer_biz or None
    elif our_clean and buyer_biz == our_clean:
        direction = "purchase"
        counterparty = seller_name or "(거래처 미상)"
        counterparty_biz = seller_biz or None
    else:
        direction = "unknown"
        counterparty = (seller_name or buyer_name or "(거래처 미상)")
        counterparty_biz = seller_biz or buyer_biz or None

    description = str(pick("resItemName", "resItemList", "resRemark", "resNote") or "").strip()[:500] or None

    return {
        "direction": direction,
        "counterparty": counterparty[:200],
        "counterparty_biz_no": counterparty_biz,
        "issue_date": issue_date,
        "due_date": None,  # 홈택스 응답엔 보통 없음
        "document_no": document_no,
        "amount": float(amount),
        "vat": float(vat),
        "total": float(total),
        "description": description,
    }


def _is_duplicate(cur, entity_id: int, tx: dict, source_type: str) -> bool:
    """date + amount + counterparty + source_type 로 중복 감지."""
    cur.execute(
        """
        SELECT id FROM transactions
        WHERE entity_id = %s AND date = %s AND amount = %s
          AND counterparty = %s AND source_type = %s
          AND is_cancel = %s
        LIMIT 1
        """,
        [
            entity_id, tx["date"], float(tx["amount"]),
            tx["counterparty"], source_type, tx.get("is_cancel", False),
        ],
    )
    return cur.fetchone() is not None


# ── connected_id 설정 storage ─────────────────────────────


def get_connected_id(conn: PgConnection, entity_id: int, org: str) -> Optional[str]:
    """settings에서 connected_id 조회. 없으면 None."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT value FROM settings WHERE key = %s AND entity_id = %s",
            [SETTINGS_PREFIX + org, entity_id],
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        cur.close()


def set_connected_id(
    conn: PgConnection,
    entity_id: int,
    org: str,
    connected_id: str,
) -> None:
    """settings에 connected_id 저장 (upsert)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO settings (key, value, entity_id, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (key, entity_id) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
            """,
            [SETTINGS_PREFIX + org, connected_id, entity_id],
        )
    finally:
        cur.close()


def list_connected_ids(conn: PgConnection, entity_id: int) -> dict:
    """entity의 모든 Codef connected_id 조회. {org: connected_id}."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT key, value FROM settings WHERE key LIKE %s AND entity_id = %s",
            [SETTINGS_PREFIX + "%", entity_id],
        )
        result = {}
        for key, value in cur.fetchall():
            org = key[len(SETTINGS_PREFIX):]
            result[org] = value
        return result
    finally:
        cur.close()


def set_last_sync(conn: PgConnection, entity_id: int, org: str) -> None:
    """sync 성공 시각을 settings에 저장 (UTC ISO)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO settings (key, value, entity_id, updated_at)
            VALUES (%s, NOW()::text, %s, NOW())
            ON CONFLICT (key, entity_id) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
            """,
            [LAST_SYNC_PREFIX + org, entity_id],
        )
    finally:
        cur.close()


def list_last_syncs(conn: PgConnection, entity_id: int) -> dict:
    """entity의 모든 기관 last_sync 시각 조회. {org: ISO timestamp}."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT key, value FROM settings WHERE key LIKE %s AND entity_id = %s",
            [LAST_SYNC_PREFIX + "%", entity_id],
        )
        result = {}
        for key, value in cur.fetchall():
            org = key[len(LAST_SYNC_PREFIX):]
            result[org] = value
        return result
    finally:
        cur.close()


def delete_connected_id(conn: PgConnection, entity_id: int, org: str) -> bool:
    """connected_id 삭제. Returns True if deleted."""
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM settings WHERE key = %s AND entity_id = %s",
            [SETTINGS_PREFIX + org, entity_id],
        )
        return cur.rowcount > 0
    finally:
        cur.close()


# ── NPKI 공동인증서 로컬 탐색 ─────────────────────────

_NPKI_ROOTS = [
    "~/Library/Preferences/NPKI",
    "~/NPKI",
]


def _detect_bank_from_dn(dn: str) -> Optional[str]:
    """cert 폴더명(=DN 일부)에서 ou 키워드로 은행/기관명 추출.

    Mac APFS는 한글을 NFD로 저장 — NFC 정규화 후 매칭.
    """
    import unicodedata
    nfc = unicodedata.normalize("NFC", dn)
    for kw, label in _BANK_OU_KEYWORDS.items():
        if kw in nfc:
            return label
    return None


def discover_npki_certs() -> list[dict]:
    """Mac/Linux의 NPKI 폴더에서 공동인증서 목록 탐색.

    Returns:
        [{ca, cn, bank, path, label}] — path는 cert 폴더 (signCert.der + signPri.key 포함)
    """
    import os as _os
    from pathlib import Path

    results: list[dict] = []
    for root_spec in _NPKI_ROOTS:
        root = Path(_os.path.expanduser(root_spec))
        if not root.exists():
            continue
        for ca_dir in root.iterdir():
            if not ca_dir.is_dir():
                continue
            user_dir = ca_dir / "USER"
            if not user_dir.exists():
                continue
            for cert_dir in user_dir.iterdir():
                if not cert_dir.is_dir():
                    continue
                sign_cert = cert_dir / "signCert.der"
                sign_key = cert_dir / "signPri.key"
                if not (sign_cert.exists() and sign_key.exists()):
                    continue
                import unicodedata
                # Mac APFS는 NFD 저장 — UI/매칭 일관성 위해 NFC 정규화
                dir_name = unicodedata.normalize("NFC", cert_dir.name)
                cn = dir_name
                if dir_name.startswith("cn="):
                    cn_raw = dir_name.split(",", 1)[0][3:]
                    cn = cn_raw.strip()
                bank = _detect_bank_from_dn(dir_name)
                # 라벨: [은행명] CN (CA)
                label_parts = []
                if bank:
                    label_parts.append(f"[{bank}]")
                label_parts.append(cn)
                label_parts.append(f"({ca_dir.name})")
                results.append({
                    "ca": ca_dir.name,
                    "cn": cn,
                    "bank": bank or "",
                    "path": str(cert_dir),
                    "label": " ".join(label_parts),
                })
    # bank → CN 순서로 정렬 (은행 같은 것끼리 묶이게)
    results.sort(key=lambda x: (x.get("bank") or "z", x["cn"]))
    return results


def load_npki_cert_files(cert_path: str) -> tuple[str, str]:
    """cert 폴더에서 signCert.der + signPri.key 읽어 base64 반환.

    Args:
        cert_path: 인증서 폴더 절대경로
    Returns:
        (der_file_b64, key_file_b64)
    Raises:
        CodefError: 파일 없음/범위 밖 경로.
    """
    import os as _os
    from pathlib import Path

    allowed_roots = [Path(_os.path.expanduser(r)).resolve() for r in _NPKI_ROOTS]
    target = Path(cert_path).resolve()
    # 허용된 NPKI 루트 하위 경로만 허용 (디렉토리 traversal 방지)
    if not any(
        str(target).startswith(str(root)) for root in allowed_roots if root.exists()
    ):
        raise CodefError(f"Cert path outside allowed NPKI roots: {cert_path}")

    der = target / "signCert.der"
    key = target / "signPri.key"
    if not der.exists() or not key.exists():
        raise CodefError(f"signCert.der 또는 signPri.key 없음: {cert_path}")

    der_b64 = base64.b64encode(der.read_bytes()).decode("ascii")
    key_b64 = base64.b64encode(key.read_bytes()).decode("ascii")
    return der_b64, key_b64

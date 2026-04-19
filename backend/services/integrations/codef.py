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
from urllib.parse import unquote_plus

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
ORG_CODES = {
    "woori_bank": "0020",
    "ibk_bank": "0003",
    "lotte_card": "0301",
    "woori_card": "0315",
    "shinhan_card": "0309",
}

# UI 표시명
ORG_LABELS = {
    "woori_bank": "우리은행",
    "ibk_bank": "IBK기업은행",
    "lotte_card": "롯데카드",
    "woori_card": "우리카드",
    "shinhan_card": "신한카드",
}

# 은행/카드 타입 → source_type (mapping rules와 일관성 유지)
BANK_ORGS = {"woori_bank", "ibk_bank"}
CARD_ORGS = {"lotte_card", "woori_card", "shinhan_card"}

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
        raise CodefError(f"Codef 공개키 처리 실패: {type(e).__name__}")


class CodefError(Exception):
    pass


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

    def _request(self, endpoint: str, params: dict) -> dict:
        token = self._get_token()
        resp = self.client.post(
            endpoint,
            json=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401:
            self._token = None
            token = self._get_token()
            resp = self.client.post(
                endpoint,
                json=params,
                headers={"Authorization": f"Bearer {token}"},
            )

        resp.raise_for_status()
        data = _parse_codef_response(resp.text)

        result = data.get("result", {})
        result_code = result.get("code", "")
        body = data.get("data", {})

        # /v1/account/create 는 부분 성공 가능 — errorList에 실패 기관별 사유
        # result.code=CF-00000이어도 errorList에 내용 있을 수 있음 (부분 성공)
        error_list = body.get("errorList") if isinstance(body, dict) else None
        if error_list:
            first = error_list[0]
            item_code = first.get("code", "")
            item_msg = first.get("message", "")
            item_extra = first.get("extraMessage", "")
            masked_params = _mask_sensitive(params)
            logger.warning(
                "Codef per-account error: code=%s msg=%s extra=%s payload=%s",
                item_code, item_msg, item_extra, masked_params,
            )
            # 전체 응답도 실패로 취급
            full = f"{item_code} - {item_msg}"
            if item_extra:
                full += f" | {item_extra}"
            raise CodefError(f"Codef 계정 등록 실패: {full}")

        if result_code != "CF-00000":
            msg = result.get("message", "")
            extra = result.get("extraMessage", "") or result.get("extraInfo", "")
            masked_params = _mask_sensitive(params)
            logger.warning(
                "Codef non-OK response: code=%s msg=%s extra=%s endpoint=%s payload=%s data=%s",
                result_code, msg, extra, endpoint, masked_params, body,
            )
            full_msg = f"{result_code} - {msg}"
            if extra:
                full_msg += f" | {extra}"
            raise CodefError(f"Codef error: {full_msg}")
        return body if isinstance(body, dict) else {}

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
    def get_bank_account_list(self, connected_id: str) -> dict:
        """우리은행 보유계좌 조회. 첫 호출로 계좌번호 확보 후 거래내역 조회 가능."""
        return self._request(
            "/v1/kr/bank/b/account/account-list",
            {"connectedId": connected_id, "organization": ORG_CODES["woori_bank"]},
        )

    def get_bank_transactions(
        self,
        connected_id: str,
        start_date: str,
        end_date: str,
        account: str,
        order_by: str = "0",
        inquiry_type: str = "1",
    ) -> list[dict]:
        """우리은행 법인 거래내역 조회 (YYYYMMDD).

        Args:
            account: 계좌번호 (하이픈 제거 13자리)
            order_by: '0'=오래된순, '1'=최신순
            inquiry_type: '1'=일반조회 (default)
        """
        return self._request(
            "/v1/kr/bank/b/account/transaction-list",
            {
                "connectedId": connected_id,
                "organization": ORG_CODES["woori_bank"],
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
    ) -> dict:
        """우리은행 거래를 transactions 테이블에 동기화.

        account 미지정 시 계좌목록 조회 후 첫 KRW 입출금 계좌 자동 사용.
        """
        if not account:
            acct_list = self.get_bank_account_list(connected_id)
            deposit = acct_list.get("resDepositTrust", [])
            if not deposit:
                raise CodefError("등록된 입출금 계좌 없음")
            account = deposit[0]["resAccount"]

        raw_list = self.get_bank_transactions(
            connected_id, start_date, end_date, account=account,
        )
        cur = conn.cursor()
        synced = 0
        duplicates = 0
        auto_mapped = 0

        # 자동 매핑 (lazy import — 순환 회피)
        from backend.services.mapping_service import auto_map_transaction

        for item in raw_list:
            tx = _normalize_bank_row(item)
            if not tx:
                continue

            if _is_duplicate(cur, entity_id, tx, "codef_woori_bank"):
                duplicates += 1
                continue

            is_check_card_memo = tx.get("memo") == "체크우리"

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
                    VALUES (%s, %s, %s, 'KRW', %s, %s, %s, 'codef_woori_bank', FALSE, FALSE, %s,
                            %s, %s, %s, %s)
                    """,
                    [
                        entity_id, tx["date"], float(tx["amount"]),
                        tx["type"], tx["description"], tx["counterparty"],
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
                    VALUES (%s, %s, %s, 'KRW', %s, %s, %s, 'codef_woori_bank', FALSE, FALSE, %s)
                    """,
                    [
                        entity_id, tx["date"], float(tx["amount"]),
                        tx["type"], tx["description"], tx["counterparty"],
                        "체크카드" if is_check_card_memo else None,
                    ],
                )
            synced += 1

        cur.close()
        logger.info(
            "Codef bank sync: entity=%d, fetched=%d, synced=%d, dup=%d, auto_mapped=%d",
            entity_id, len(raw_list), synced, duplicates, auto_mapped,
        )
        return {
            "synced": synced,
            "duplicates": duplicates,
            "auto_mapped": auto_mapped,
            "unmapped": synced - auto_mapped,
            "total_fetched": len(raw_list),
            "environment": self.environment,
            "account": account,
        }

    # ── 카드 ────────────────────────────────────────────────
    def get_card_approvals(
        self,
        connected_id: str,
        start_date: str,
        end_date: str,
        card_type: str = "lotte_card",
    ) -> list[dict]:
        """카드 승인내역 조회 (롯데/우리/신한).

        Args:
            card_type: "lotte_card" | "woori_card" | "shinhan_card"
        """
        org_code = ORG_CODES.get(card_type)
        if not org_code:
            raise CodefError(f"Unknown card type: {card_type}")

        return self._request(
            "/v1/kr/card/b/account/approval-list",
            {
                "connectedId": connected_id,
                "organization": org_code,
                "startDate": start_date,
                "endDate": end_date,
            },
        ).get("resApprovalList", [])

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

        raw_list = self.get_card_approvals(connected_id, start_date, end_date, card_type)
        source_type = f"codef_{card_type}"

        cur = conn.cursor()
        synced = 0
        duplicates = 0
        cancels = 0

        for item in raw_list:
            tx = _normalize_card_row(item)
            if not tx:
                continue

            if _is_duplicate(cur, entity_id, tx, source_type):
                duplicates += 1
                continue

            cur.execute(
                """
                INSERT INTO transactions
                    (entity_id, date, amount, currency, type, description,
                     counterparty, source_type, is_confirmed,
                     card_number, parsed_member_name, is_cancel)
                VALUES (%s, %s, %s, 'KRW', %s, %s, %s, %s, FALSE,
                        %s, %s, %s)
                """,
                [
                    entity_id, tx["date"], float(tx["amount"]),
                    tx["type"], tx["description"], tx["counterparty"],
                    source_type,
                    tx["card_number"], tx["member_name"], tx["is_cancel"],
                ],
            )
            synced += 1
            if tx["is_cancel"]:
                cancels += 1

        cur.close()
        logger.info(
            "Codef card sync: entity=%d, card=%s, fetched=%d, synced=%d, dup=%d, cancels=%d",
            entity_id, card_type, len(raw_list), synced, duplicates, cancels,
        )
        return {
            "card_type": card_type,
            "synced": synced,
            "duplicates": duplicates,
            "cancels": cancels,
            "total_fetched": len(raw_list),
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

    card_no = _mask_card_number(str(item.get("resCardNo", "")))
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

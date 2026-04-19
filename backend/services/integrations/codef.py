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
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import httpx
from psycopg2.extensions import connection as PgConnection

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
    "lotte_card": "0301",
    "woori_card": "0315",
    "shinhan_card": "0309",
}

# 은행/카드 타입 → source_type (mapping rules와 일관성 유지)
BANK_ORGS = {"woori_bank"}
CARD_ORGS = {"lotte_card", "woori_card", "shinhan_card"}

SETTINGS_PREFIX = "codef_connected_id_"  # e.g., codef_connected_id_woori_bank


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
        data = resp.json()

        result_code = data.get("result", {}).get("code", "")
        if result_code != "CF-00000":
            raise CodefError(
                f"Codef error: {result_code} - {data.get('result', {}).get('message', '')}"
            )
        return data.get("data", {})

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
    def get_bank_transactions(
        self,
        connected_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """우리은행 법인 거래내역 조회 (YYYYMMDD)."""
        return self._request(
            "/v1/kr/bank/b/account/transaction-list",
            {
                "connectedId": connected_id,
                "organization": ORG_CODES["woori_bank"],
                "startDate": start_date,
                "endDate": end_date,
                "clientType": "B",
            },
        ).get("resTrHistoryList", [])

    def sync_bank_transactions(
        self,
        conn: PgConnection,
        entity_id: int,
        connected_id: str,
        start_date: str,
        end_date: str,
    ) -> dict:
        """우리은행 거래를 transactions 테이블에 동기화."""
        raw_list = self.get_bank_transactions(connected_id, start_date, end_date)
        cur = conn.cursor()
        synced = 0
        duplicates = 0

        for item in raw_list:
            tx = _normalize_bank_row(item)
            if not tx:
                continue

            if _is_duplicate(cur, entity_id, tx, "codef_woori_bank"):
                duplicates += 1
                continue

            cur.execute(
                """
                INSERT INTO transactions
                    (entity_id, date, amount, currency, type, description,
                     counterparty, source_type, is_confirmed, is_cancel)
                VALUES (%s, %s, %s, 'KRW', %s, %s, %s, 'codef_woori_bank', FALSE, FALSE)
                """,
                [
                    entity_id, tx["date"], float(tx["amount"]),
                    tx["type"], tx["description"], tx["counterparty"],
                ],
            )
            synced += 1

        cur.close()
        logger.info(
            "Codef bank sync: entity=%d, fetched=%d, synced=%d, duplicates=%d",
            entity_id, len(raw_list), synced, duplicates,
        )
        return {
            "synced": synced,
            "duplicates": duplicates,
            "total_fetched": len(raw_list),
            "environment": self.environment,
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
    """Codef 은행 응답 → 정규화된 dict.

    주요 필드:
        resAccountTrDate: YYYYMMDD 거래일
        resAccountIn:  입금액 (non-empty면 입금)
        resAccountOut: 출금액
        resAccountTrAmount: 거래금액 (in 또는 out 중 값 있는 쪽)
        resAccountDesc:  적요
        resAccountDesc1/2/3: 상세 적요 (counterparty 후보)
    """
    tx_date = _parse_codef_date(str(item.get("resAccountTrDate", "")))
    if not tx_date:
        return None

    in_raw = item.get("resAccountIn", "") or ""
    out_raw = item.get("resAccountOut", "") or ""
    amount_raw = item.get("resAccountTrAmount", "") or in_raw or out_raw

    amount = _parse_amount(amount_raw)
    if amount == 0:
        return None

    # 입금/출금 결정 — in 필드에 값이 있으면 입금
    in_amount = _parse_amount(in_raw)
    tx_type = "in" if in_amount > 0 else "out"

    # 적요 우선순위: Desc1 > Desc > Desc2
    desc1 = str(item.get("resAccountDesc1", "")).strip()
    desc = str(item.get("resAccountDesc", "")).strip()
    desc2 = str(item.get("resAccountDesc2", "")).strip()
    desc3 = str(item.get("resAccountDesc3", "")).strip()

    description = desc1 or desc or desc2 or desc3 or "(적요 없음)"
    counterparty = desc1 or desc2 or desc or "(미확인)"

    return {
        "date": tx_date,
        "amount": amount,
        "type": tx_type,
        "description": description[:500],
        "counterparty": counterparty[:200],
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

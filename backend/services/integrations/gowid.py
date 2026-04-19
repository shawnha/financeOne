"""Gowid Open API 연동 — 법인카드 거래 자동 pull (차선책).

Codef 롯데카드 직접 연결이 차단될 때 우회로. 고위드는 ExpenseOne과 같은
원천 데이터를 보유하지만 자체 API로 별도 sync 가능.

env vars:
    GOWID_API_KEY: Authorization 헤더에 그대로 들어가는 raw API key

Reference: https://teamgowid.notion.site/Gowid-Open-API-9-...
Base URL : https://openapi.gowid.com
인증     : Authorization: <API_KEY> (prefix 없음)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import httpx
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

GOWID_BASE_URL = "https://openapi.gowid.com"
SETTINGS_KEY_PREFIX = "gowid_api_key"

# Gowid 출처 fallback (카드사 식별 안 될 때만 사용)
DEFAULT_SOURCE_TYPE = "gowid_card"

# shortCardNumber 형식 "롯데 0742" → 카드사 추출
_CARD_ISSUER_PATTERN = re.compile(r"^(\S+)\s+(\d{4})$")

# Gowid 카드사 한글 → ORG 키 (FinanceOne 분류용 — Codef와 동일 명명 따름)
GOWID_ISSUER_TO_ORG = {
    "롯데": "lotte_card",
    "우리": "woori_card",
    "신한": "shinhan_card",
    "삼성": "samsung_card",
    "현대": "hyundai_card",
    "국민": "kb_card",
    "하나": "hana_card",
    "BC": "bc_card",
    "농협": "nh_card",
}


class GowidError(Exception):
    pass


def get_api_key(conn: PgConnection, entity_id: int) -> Optional[str]:
    """entity_id에 등록된 Gowid API key 조회.
    settings(key='gowid_api_key', entity_id=N).value 에 저장."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT value FROM settings WHERE key = %s AND entity_id = %s",
            [SETTINGS_KEY_PREFIX, entity_id],
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        cur.close()


def set_api_key(conn: PgConnection, entity_id: int, api_key: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO settings (key, value, entity_id, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (key, entity_id) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
            """,
            [SETTINGS_KEY_PREFIX, api_key, entity_id],
        )
    finally:
        cur.close()


def delete_api_key(conn: PgConnection, entity_id: int) -> bool:
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM settings WHERE key = %s AND entity_id = %s",
            [SETTINGS_KEY_PREFIX, entity_id],
        )
        return cur.rowcount > 0
    finally:
        cur.close()


class GowidClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(base_url=GOWID_BASE_URL, timeout=30.0)

    def close(self):
        self.client.close()

    def _request(self, method: str, path: str, params: Optional[dict] = None) -> dict:
        resp = self.client.request(
            method, path,
            params=params,
            headers={"Authorization": self.api_key},
        )
        resp.raise_for_status()
        body = resp.json()
        result = body.get("result", {}) if isinstance(body, dict) else {}
        if result.get("code") != 20000000:
            raise GowidError(
                f"Gowid {result.get('code')}: {result.get('desc', '')}"
            )
        return body.get("data") or {}

    def health(self) -> bool:
        """Health 체크 — /v1/members 호출 성공 여부로 대체.
        (actuator/health는 401 반환)"""
        try:
            self._request("GET", "/v1/members")
            return True
        except Exception:
            return False

    def get_members(self) -> list[dict]:
        data = self._request("GET", "/v1/members")
        return data if isinstance(data, list) else []

    def get_expenses(
        self,
        start_date: str,
        end_date: str,
        page: int = 0,
        size: int = 100,
    ) -> dict:
        """지출 목록 조회 (paginated).

        Args:
            start_date: ISO YYYY-MM-DD
            end_date:   ISO YYYY-MM-DD
        """
        return self._request(
            "GET", "/v1/expenses",
            params={
                "startDate": start_date,
                "endDate": end_date,
                "page": page,
                "size": size,
            },
        )

    def iter_expenses(self, start_date: str, end_date: str, page_size: int = 100):
        """페이징 자동 처리 — 모든 expenses iterator."""
        page = 0
        while True:
            data = self.get_expenses(start_date, end_date, page=page, size=page_size)
            content = data.get("content", []) if isinstance(data, dict) else []
            for item in content:
                yield item
            if not content or data.get("last", True):
                return
            page += 1

    def sync_expenses(
        self,
        conn: PgConnection,
        entity_id: int,
        start_date: str,
        end_date: str,
    ) -> dict:
        """고위드 거래 → transactions INSERT.

        - source_type = 'gowid_card'
        - shortCardNumber = '카드사명 끝4자리' → counterparty와 별개로 card_number에 저장
        - krwAmount(원화 환산) 우선, 없으면 useAmount + currency
        - 자동 매핑 cascade 적용
        """
        from backend.services.mapping_service import auto_map_transaction

        cur = conn.cursor()
        synced = 0
        duplicates = 0
        auto_mapped = 0
        skipped = 0
        per_issuer: dict[str, int] = {}

        for item in self.iter_expenses(start_date, end_date):
            tx = _normalize_expense(item)
            if not tx:
                skipped += 1
                continue

            gowid_id = item.get("expenseId")
            id_marker = f"gowid_id:{gowid_id}"
            # 출처 = 카드사별 (Excel 업로드와 같은 source_type) — fallback gowid_card
            source_type = tx.get("issuer_org") or DEFAULT_SOURCE_TYPE

            # 중복 감지 — gowid_id marker로 모든 source_type 가로질러 검색
            cur.execute(
                """
                SELECT id FROM transactions
                WHERE entity_id = %s AND note LIKE %s
                LIMIT 1
                """,
                [entity_id, f"{id_marker}%"],
            )
            if cur.fetchone():
                duplicates += 1
                continue

            # member_id 자동 매칭: 카드번호 → 이름 fallback (Codef와 동일 패턴)
            member_id = None
            if tx.get("card_number"):
                cur.execute(
                    "SELECT id FROM members WHERE entity_id = %s AND %s = ANY(card_numbers) AND is_active = true LIMIT 1",
                    [entity_id, tx["card_number"]],
                )
                row = cur.fetchone()
                if row:
                    member_id = row[0]
            if member_id is None and tx.get("card_alias"):
                cur.execute(
                    "SELECT id FROM members WHERE entity_id = %s AND name = %s AND is_active = true LIMIT 1",
                    [entity_id, tx["card_alias"]],
                )
                row = cur.fetchone()
                if row:
                    member_id = row[0]

            mapping = auto_map_transaction(
                cur, entity_id=entity_id,
                counterparty=tx["counterparty"],
                description=tx["description"],
            )

            note_with_id = f"{id_marker} | gowid"
            if tx.get("note"):
                note_with_id += f" | {tx['note']}"

            cur.execute(
                """
                INSERT INTO transactions
                    (entity_id, date, amount, currency, type, description,
                     counterparty, source_type, is_confirmed, is_cancel,
                     card_number, parsed_member_name, member_id,
                     internal_account_id, standard_account_id,
                     mapping_confidence, mapping_source,
                     note, created_at, updated_at)
                VALUES (%s, %s, %s, 'KRW', 'out', %s, %s, %s, FALSE, FALSE,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, NOW(), NOW())
                """,
                [
                    entity_id, tx["date"], float(tx["amount"]),
                    tx["description"], tx["counterparty"], source_type,
                    tx["card_number"], tx["card_alias"], member_id,
                    mapping["internal_account_id"] if mapping else None,
                    mapping.get("standard_account_id") if mapping else None,
                    mapping.get("confidence") if mapping else None,
                    mapping.get("match_type") if mapping else None,
                    note_with_id,
                ],
            )
            synced += 1
            if mapping:
                auto_mapped += 1
            issuer = tx.get("issuer") or "미상"
            per_issuer[issuer] = per_issuer.get(issuer, 0) + 1

        cur.close()
        logger.info(
            "Gowid sync: entity=%d, synced=%d, dup=%d, auto_mapped=%d, skipped=%d, by_issuer=%s",
            entity_id, synced, duplicates, auto_mapped, skipped, per_issuer,
        )
        return {
            "synced": synced,
            "duplicates": duplicates,
            "auto_mapped": auto_mapped,
            "unmapped": synced - auto_mapped,
            "skipped": skipped,
            "by_issuer": per_issuer,
        }


# ── 정규화 ────────────────────────────────────────


def _parse_yyyymmdd(s: Any) -> Optional[str]:
    if not s:
        return None
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 10 and s[4] == "-":
        return s
    return None


def _parse_short_card(short: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """'롯데 0742' → ('롯데', '0742', 'lotte_card')"""
    if not short:
        return None, None, None
    m = _CARD_ISSUER_PATTERN.match(short.strip())
    if not m:
        return None, None, None
    issuer_kr = m.group(1)
    last4 = m.group(2)
    org = GOWID_ISSUER_TO_ORG.get(issuer_kr)
    return issuer_kr, last4, org


def _normalize_expense(item: dict) -> Optional[dict]:
    """Gowid expense → transactions row dict."""
    tx_date = _parse_yyyymmdd(item.get("expenseDate"))
    if not tx_date:
        return None

    krw = item.get("krwAmount")
    use_amt = item.get("useAmount")
    currency = item.get("currency", "KRW")
    # 원화 우선, 없으면 useAmount(KRW)
    if krw is None and currency == "KRW":
        krw = use_amt
    try:
        amount = Decimal(str(krw or 0))
    except Exception:
        amount = Decimal(0)
    if amount <= 0:
        return None

    short_card = item.get("shortCardNumber") or ""
    issuer_kr, last4, org = _parse_short_card(short_card)
    card_label = f"****{last4}" if last4 else None

    store = (item.get("storeName") or "").strip()
    counterparty = store or short_card or "(미상)"
    description = store or "(고위드 거래)"

    note_parts = []
    if issuer_kr:
        note_parts.append(f"{issuer_kr}카드")
    if currency and currency != "KRW":
        note_parts.append(f"{currency} {use_amt}")
    note = " | ".join(note_parts) if note_parts else None

    return {
        "date": tx_date,
        "amount": amount,
        "description": description[:500],
        "counterparty": counterparty[:200],
        "card_number": card_label,
        "card_alias": (item.get("cardAlias") or "").strip() or None,
        "issuer": issuer_kr,
        "issuer_org": org,
        "note": note,
    }

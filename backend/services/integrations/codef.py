"""Codef.io API 연동 — 한국 법인 은행/카드 (SANDBOX ONLY)

데모 신청 후 승인 필요. 프로덕션 전환 시 공동인증서 필수.
"""

import logging
from decimal import Decimal

import httpx
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

CODEF_SANDBOX_URL = "https://development.codef.io"
CODEF_TOKEN_URL = "https://oauth.codef.io/oauth/token"

# 기관 코드
ORG_CODES = {
    "woori_bank": "0020",
    "lotte_card": "0301",
    "woori_card": "0315",
    "shinhan_card": "0309",
}


class CodefError(Exception):
    pass


class CodefClient:
    """Codef 샌드박스 클라이언트. 프로덕션 사용 금지."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self.client = httpx.Client(
            base_url=CODEF_SANDBOX_URL,
            timeout=30.0,
        )

    def close(self):
        self.client.close()

    def _get_token(self) -> str:
        """OAuth2 client_credentials 토큰 발급."""
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
        """Codef API 요청."""
        token = self._get_token()
        resp = self.client.post(
            endpoint,
            json=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401:
            # 토큰 만료 → 재발급
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

    def get_bank_transactions(
        self,
        connected_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """우리은행 법인 거래내역 조회.

        Args:
            connected_id: Codef connected ID
            start_date: "YYYYMMDD"
            end_date: "YYYYMMDD"
        """
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
            amount = abs(Decimal(str(item.get("resAccountTrAmount", "0").replace(",", ""))))
            tx_type = "in" if item.get("resAccountIn") else "out"
            tx_date = item.get("resAccountTrDate", "")
            if len(tx_date) == 8:
                tx_date = f"{tx_date[:4]}-{tx_date[4:6]}-{tx_date[6:8]}"
            description = item.get("resAccountDesc", "")
            counterparty = item.get("resAccountDesc", "")

            if not tx_date or amount == 0:
                continue

            cur.execute(
                """
                SELECT id FROM transactions
                WHERE entity_id = %s AND date = %s AND amount = %s
                  AND counterparty = %s AND source_type = 'codef_api'
                LIMIT 1
                """,
                [entity_id, tx_date, float(amount), counterparty],
            )
            if cur.fetchone():
                duplicates += 1
                continue

            cur.execute(
                """
                INSERT INTO transactions
                    (entity_id, date, amount, currency, type, description,
                     counterparty, source_type, is_confirmed)
                VALUES (%s, %s, %s, 'KRW', %s, %s, %s, 'codef_api', FALSE)
                """,
                [entity_id, tx_date, float(amount), tx_type, description, counterparty],
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
        }

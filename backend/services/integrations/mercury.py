"""Mercury API 연동 — HOI USD 거래 Read-only

Mercury Dashboard > Settings > API > Read-only 토큰 발급
"""

import logging
import os
from datetime import date
from decimal import Decimal

import httpx
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

MERCURY_BASE_URL = "https://api.mercury.com/api/v1"
HOI_ENTITY_ID = int(os.environ.get("HOI_ENTITY_ID", "1"))


class MercuryError(Exception):
    pass


class MercuryClient:
    def __init__(self, api_token: str):
        self.headers = {"Authorization": f"Bearer {api_token}"}
        self.client = httpx.Client(
            base_url=MERCURY_BASE_URL,
            headers=self.headers,
            timeout=30.0,
        )

    def close(self):
        self.client.close()

    def get_accounts(self) -> list[dict]:
        """Mercury 계좌 목록 + 잔고 조회."""
        resp = self.client.get("/accounts")
        if resp.status_code == 401:
            raise MercuryError("Invalid API token")
        resp.raise_for_status()
        data = resp.json()
        return data.get("accounts", [])

    def get_transactions(
        self,
        account_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """Mercury 거래 내역 조회 (paginated)."""
        params: dict = {"limit": limit, "offset": offset}
        if start_date:
            params["start"] = start_date
        if end_date:
            params["end"] = end_date

        resp = self.client.get(f"/account/{account_id}/transactions", params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("transactions", [])

    def sync_transactions(
        self,
        conn: PgConnection,
        account_id: str,
    ) -> dict:
        """Mercury 거래를 transactions 테이블에 동기화.

        Returns:
            {"synced": int, "duplicates": int, "total_fetched": int}
        """
        all_transactions = []
        offset = 0
        limit = 500

        # 페이지네이션으로 전체 조회
        while True:
            batch = self.get_transactions(account_id, limit=limit, offset=offset)
            if not batch:
                break
            all_transactions.extend(batch)
            if len(batch) < limit:
                break
            offset += limit

        cur = conn.cursor()
        synced = 0
        duplicates = 0

        for tx in all_transactions:
            mercury_amount = abs(Decimal(str(tx.get("amount", 0))))
            tx_type = "in" if tx.get("kind") == "credit" else "out"
            tx_date = tx.get("createdAt", "")[:10]  # YYYY-MM-DD
            counterparty = tx.get("counterpartyName", "") or tx.get("bankDescription", "")
            description = tx.get("bankDescription", "") or tx.get("counterpartyName", "")

            if not tx_date or mercury_amount == 0:
                continue

            # 중복 감지: (entity_id, date, amount, counterparty, source_type)
            cur.execute(
                """
                SELECT id FROM transactions
                WHERE entity_id = %s AND date = %s AND amount = %s
                  AND counterparty = %s AND source_type = 'mercury_api'
                LIMIT 1
                """,
                [HOI_ENTITY_ID, tx_date, float(mercury_amount), counterparty],
            )
            if cur.fetchone():
                duplicates += 1
                continue

            cur.execute(
                """
                INSERT INTO transactions
                    (entity_id, date, amount, currency, type, description,
                     counterparty, source_type, is_confirmed)
                VALUES (%s, %s, %s, 'USD', %s, %s, %s, 'mercury_api', FALSE)
                """,
                [HOI_ENTITY_ID, tx_date, float(mercury_amount), tx_type, description, counterparty],
            )
            synced += 1

        cur.close()

        logger.info(
            "Mercury sync: fetched=%d, synced=%d, duplicates=%d",
            len(all_transactions), synced, duplicates,
        )

        return {
            "synced": synced,
            "duplicates": duplicates,
            "total_fetched": len(all_transactions),
        }

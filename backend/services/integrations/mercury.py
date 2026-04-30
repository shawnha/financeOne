"""Mercury API 연동 — HOI USD 거래 Read-only

Mercury Dashboard > Settings > API > Read-only 토큰 발급
"""

import logging
import os
from collections import defaultdict
from datetime import date, timedelta
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

    def sync_historical_balances(self, conn: PgConnection) -> dict:
        """Mercury 거래 + 현재 잔고 → 일별 historical balance_snapshots 자동 reconstruction.

        Mercury API 는 historical balance metadata 를 제공 안 함. 그러나:
          anchor_balance(가장 오래된 거래 직전) = current_balance - Σ signed_transactions
          → 일별 누적으로 매 일자 EOD 잔고 자동 계산.

        가정: HOI 의 mercury_api 거래 = 잔고 최대인 primary account (보통 Checking).
        다른 account 가 0 잔고 + 거래 없으면 안전. (multi-account 분리는 향후)
        """
        accounts = self.get_accounts()
        cur = conn.cursor()

        # 잔고 최대 account = primary
        def acc_balance(acc):
            v = acc.get("currentBalance")
            if v is None:
                v = acc.get("availableBalance")
            return Decimal(str(v or 0))

        if not accounts:
            cur.close()
            return {"snapshots_upserted": 0, "primary_account": None}

        primary = max(accounts, key=acc_balance)
        primary_name = primary.get("name") or primary.get("nickname") or primary.get("id", "Mercury Primary")
        current = acc_balance(primary)
        primary_kind = primary.get("kind") or primary.get("type") or "checking"

        # 모든 mercury_api 거래 (DB sync 된 것)
        cur.execute(
            """
            SELECT date, type, amount FROM financeone.transactions
            WHERE entity_id = %s
              AND source_type = 'mercury_api'
              AND (is_cancel IS NOT TRUE)
            ORDER BY date, id
            """,
            [HOI_ENTITY_ID],
        )
        rows = cur.fetchall()

        upserted = 0

        if not rows:
            # 거래 없으면 오늘 잔고만 upsert
            cur.execute(
                """
                INSERT INTO financeone.balance_snapshots
                    (entity_id, date, account_name, account_type, balance, currency, source)
                VALUES (%s, %s, %s, %s, %s, 'USD', 'mercury_api')
                ON CONFLICT (entity_id, date, account_name) DO UPDATE
                  SET balance = EXCLUDED.balance, source = 'mercury_api'
                """,
                [HOI_ENTITY_ID, date.today(), primary_name, primary_kind, float(current)],
            )
            cur.close()
            return {"snapshots_upserted": 1, "primary_account": primary_name, "current_balance": float(current)}

        # 일별 net 합산
        daily_net: dict = defaultdict(lambda: Decimal(0))
        for d, t, a in rows:
            sign = Decimal(1) if t == 'in' else Decimal(-1)
            daily_net[d] += Decimal(str(a)) * sign

        total_signed = sum(daily_net.values(), Decimal(0))
        anchor_balance = current - total_signed
        earliest = min(daily_net.keys())
        anchor_date = earliest - timedelta(days=1)

        # 일별 closing balance: anchor → 누적
        sorted_dates = sorted(daily_net.keys())
        running = anchor_balance

        # anchor_date 잔고 INSERT (가장 오래된 거래 직전 잔고)
        cur.execute(
            """
            INSERT INTO financeone.balance_snapshots
                (entity_id, date, account_name, account_type, balance, currency, source)
            VALUES (%s, %s, %s, %s, %s, 'USD', 'mercury_api_historical')
            ON CONFLICT (entity_id, date, account_name) DO UPDATE
              SET balance = EXCLUDED.balance, source = 'mercury_api_historical'
            """,
            [HOI_ENTITY_ID, anchor_date, primary_name, primary_kind, float(anchor_balance)],
        )
        upserted += 1

        for d in sorted_dates:
            running += daily_net[d]
            cur.execute(
                """
                INSERT INTO financeone.balance_snapshots
                    (entity_id, date, account_name, account_type, balance, currency, source)
                VALUES (%s, %s, %s, %s, %s, 'USD', 'mercury_api_historical')
                ON CONFLICT (entity_id, date, account_name) DO UPDATE
                  SET balance = EXCLUDED.balance, source = 'mercury_api_historical'
                """,
                [HOI_ENTITY_ID, d, primary_name, primary_kind, float(running)],
            )
            upserted += 1

        # 오늘 잔고 = current (anchor + total_signed 와 동치, 검증)
        today = date.today()
        if today not in daily_net:
            cur.execute(
                """
                INSERT INTO financeone.balance_snapshots
                    (entity_id, date, account_name, account_type, balance, currency, source)
                VALUES (%s, %s, %s, %s, %s, 'USD', 'mercury_api')
                ON CONFLICT (entity_id, date, account_name) DO UPDATE
                  SET balance = EXCLUDED.balance, source = 'mercury_api'
                """,
                [HOI_ENTITY_ID, today, primary_name, primary_kind, float(current)],
            )
            upserted += 1

        cur.close()
        logger.info(
            "Mercury historical: account=%s upserted=%d anchor=%s anchor_bal=%s current=%s diff=%s",
            primary_name, upserted, anchor_date, anchor_balance, current, running - current,
        )
        return {
            "snapshots_upserted": upserted,
            "primary_account": primary_name,
            "anchor_date": str(anchor_date),
            "anchor_balance": float(anchor_balance),
            "current_balance": float(current),
            "reconstruction_drift": float(running - current),  # 0 이어야 정확
        }

    def sync_balance_snapshot(self, conn: PgConnection) -> dict:
        """Mercury accounts API → balance_snapshots 오늘 날짜 upsert.

        cashflow 의 기초잔고 / 기말잔고 계산이 balance_snapshots 를 의존하므로
        Mercury sync 시 매번 갱신해야 정확. 가장 자주 갱신되는 entity_id=HOI 의
        잔고가 stale 이 되는 것을 막음.

        Returns:
            {"upserted": int, "accounts": [{"name": ..., "balance": ...}]}
        """
        accounts = self.get_accounts()
        cur = conn.cursor()
        upserted = 0
        snapshots = []
        snapshot_date = date.today()

        for acc in accounts:
            name = acc.get("name") or acc.get("nickname") or acc.get("id", "Unknown")
            # Mercury API: currentBalance (settled) / availableBalance (settled - pending)
            balance = acc.get("currentBalance")
            if balance is None:
                balance = acc.get("availableBalance")
            if balance is None:
                continue

            cur.execute(
                """
                INSERT INTO balance_snapshots
                    (entity_id, date, account_name, account_type, balance, currency, source)
                VALUES (%s, %s, %s, %s, %s, 'USD', 'mercury_api')
                ON CONFLICT (entity_id, date, account_name) DO UPDATE
                    SET balance = EXCLUDED.balance,
                        source = 'mercury_api',
                        account_type = EXCLUDED.account_type
                """,
                [
                    HOI_ENTITY_ID, snapshot_date, name,
                    acc.get("kind") or acc.get("type") or "checking",
                    float(Decimal(str(balance))),
                ],
            )
            upserted += 1
            snapshots.append({"name": name, "balance": float(Decimal(str(balance)))})

        cur.close()
        logger.info("Mercury balance snapshot: upserted=%d accounts=%s", upserted, [s["name"] for s in snapshots])
        return {"upserted": upserted, "accounts": snapshots, "date": str(snapshot_date)}

    def sync_transactions(
        self,
        conn: PgConnection,
        account_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Mercury 거래를 transactions 테이블에 동기화.

        Args:
            start_date / end_date: ISO 8601 (YYYY-MM-DD). 미지정 시 Mercury API default (최근).

        Returns:
            {"synced": int, "duplicates": int, "total_fetched": int}
        """
        all_transactions = []
        offset = 0
        limit = 500

        # 페이지네이션으로 전체 조회
        while True:
            batch = self.get_transactions(account_id, start_date=start_date,
                                          end_date=end_date, limit=limit, offset=offset)
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
            raw_amount = Decimal(str(tx.get("amount", 0)))
            mercury_amount = abs(raw_amount)
            # Mercury API: amount 부호로 in/out 결정 (음수 = 지출, 양수 = 입금)
            tx_type = "in" if raw_amount > 0 else "out"
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

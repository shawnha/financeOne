"""QuickBooks Online 연동 — HOI USD 거래 Read-only

OAuth 2.0 3-legged flow + QBO Query API.
Chart of Accounts + 라인 레벨 거래 pull → mapping_rules 자동 시드.
"""

import base64
import difflib
import logging
import os
import re
import secrets
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

QBO_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_SCOPE = "com.intuit.quickbooks.accounting"

# sandbox (dev keys) vs production — Intuit Developer 앱 상태에 따라 분기
QBO_ENVIRONMENT = os.environ.get("QBO_ENVIRONMENT", "sandbox").lower()
QBO_API_BASE = (
    "https://sandbox-quickbooks.api.intuit.com"
    if QBO_ENVIRONMENT == "sandbox"
    else "https://quickbooks.api.intuit.com"
)

HOI_ENTITY_ID = int(os.environ.get("HOI_ENTITY_ID", "1"))

# QBO account taxonomy → gaap_mapping.us_gaap_name
QBO_TO_USGAAP: dict[tuple[str, str | None], str] = {
    ("Expense", "AdvertisingPromotional"): "Advertising Expense",
    ("Expense", "OfficeGeneralAdministrativeExpenses"): "Professional Fees",
    ("Expense", "OtherMiscellaneousServiceCost"): "Professional Fees",
    ("Expense", "RentOrLeaseOfBuildings"): "Rent Expense",
    ("Expense", "Utilities"): "Utilities Expense",
    ("Expense", "Insurance"): "Insurance Expense",
    ("Expense", "PayrollExpenses"): "Salaries & Wages",
    ("Expense", "TravelExpenses"): "Travel Expense",
    ("Expense", "Travel"): "Travel Expense",
    ("Expense", "Meals"): "Meals & Entertainment",
    ("Expense", "EntertainmentMeals"): "Meals & Entertainment",
    ("Expense", "LegalProfessionalFees"): "Professional Fees",
    ("Expense", "OfficeExpenses"): "Office Supplies",
    ("Expense", "OtherBusinessExpenses"): "Professional Fees",
    ("Expense", "Auto"): "Auto Expense",
    ("Expense", "TaxesPaid"): "Tax Expense",
    ("Bank", None): "Cash and Cash Equivalents",
    ("Accounts Receivable", None): "Accounts Receivable",
    ("Accounts Payable", None): "Accounts Payable",
    ("Other Current Asset", None): "Prepaid Expenses",
    ("Other Current Liability", None): "Accrued Liabilities",
    ("Credit Card", None): "Credit Card Payable",
    ("Income", None): "Revenue",
    ("Other Income", None): "Other Income",
    ("Other Expense", None): "Other Expense",
    ("Cost of Goods Sold", None): "Cost of Goods Sold",
    ("Equity", None): "Retained Earnings",
    ("Fixed Asset", None): "Property & Equipment",
    ("Long Term Liability", None): "Long-term Debt",
}

# Category-level fallback (when sub_type not in map)
QBO_CATEGORY_FALLBACK: dict[str, str] = {
    "Expense": "Professional Fees",
    "Bank": "Cash and Cash Equivalents",
    "Income": "Revenue",
    "Other Income": "Other Income",
    "Other Expense": "Other Expense",
    "Accounts Receivable": "Accounts Receivable",
    "Accounts Payable": "Accounts Payable",
    "Other Current Asset": "Prepaid Expenses",
    "Other Current Liability": "Accrued Liabilities",
    "Credit Card": "Credit Card Payable",
    "Cost of Goods Sold": "Cost of Goods Sold",
    "Equity": "Retained Earnings",
    "Fixed Asset": "Property & Equipment",
    "Long Term Liability": "Long-term Debt",
}


class QBOError(Exception):
    pass


def _normalize_payee(name: str) -> str:
    """Payee 이름 정규화: lowercase, 접미사 제거, 공백 정리."""
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r"\b(inc|llc|corp|ltd|co|company|limited)\b\.?", "", n)
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _normalize_qbo_account_type(account_type: str, account_sub_type: str | None) -> str | None:
    """QBO account taxonomy → gaap_mapping.us_gaap_name 변환."""
    key = (account_type, account_sub_type)
    if key in QBO_TO_USGAAP:
        return QBO_TO_USGAAP[key]
    # Sub-type wildcard fallback
    key_wild = (account_type, None)
    if key_wild in QBO_TO_USGAAP:
        return QBO_TO_USGAAP[key_wild]
    # Category-level fallback
    return QBO_CATEGORY_FALLBACK.get(account_type)


class QBOClient:
    """QuickBooks Online read-only 클라이언트."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.client = httpx.Client(timeout=30.0)

    def close(self):
        self.client.close()

    # ── OAuth ────────────────────────────────────────────────

    def get_auth_url(self, state: str) -> str:
        """OAuth authorize URL 생성."""
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": QBO_SCOPE,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{QBO_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, realm_id: str) -> dict:
        """Authorization code → access/refresh token 교환."""
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        resp = self.client.post(
            QBO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp.status_code != 200:
            logger.error("QBO token exchange failed: %d %s", resp.status_code, resp.text)
            raise QBOError(f"Token exchange failed: {resp.status_code}")

        data = resp.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "realm_id": realm_id,
            "expires_in": data.get("expires_in", 3600),
        }

    def refresh_tokens(self, refresh_token: str) -> dict:
        """Refresh token → 새 access/refresh token."""
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        resp = self.client.post(
            QBO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp.status_code != 200:
            logger.error("QBO token refresh failed: %d %s", resp.status_code, resp.text)
            raise QBOError(f"Token refresh failed: {resp.status_code}")

        data = resp.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_in": data.get("expires_in", 3600),
        }

    # ── API 호출 ─────────────────────────────────────────────

    def _request(
        self,
        method: str,
        endpoint: str,
        realm_id: str,
        access_token: str,
        refresh_token: str | None = None,
        conn: PgConnection | None = None,
        entity_id: int = HOI_ENTITY_ID,
    ) -> dict:
        """QBO API 호출 + 401 자동 refresh + 429 backoff."""
        url = f"{QBO_API_BASE}/v3/company/{realm_id}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        for attempt in range(3):
            resp = self.client.request(method, url, headers=headers)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 401 and refresh_token and attempt == 0:
                logger.info("QBO 401 — refreshing tokens")
                tokens = self.refresh_tokens(refresh_token)
                access_token = tokens["access_token"]
                headers["Authorization"] = f"Bearer {access_token}"
                # settings 테이블 업데이트
                if conn:
                    _save_tokens(conn, entity_id, tokens)
                continue

            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("QBO 429 — backoff %ds", wait)
                time.sleep(wait)
                continue

            resp.raise_for_status()

        raise QBOError("QBO API request failed after retries")

    # ── Read ─────────────────────────────────────────────────

    def get_accounts(
        self, realm_id: str, access_token: str, refresh_token: str,
        conn: PgConnection, entity_id: int = HOI_ENTITY_ID,
    ) -> list[dict]:
        """QBO Chart of Accounts 조회."""
        data = self._request(
            "GET",
            "query?query=SELECT * FROM Account MAXRESULTS 1000",
            realm_id, access_token, refresh_token, conn, entity_id,
        )
        return data.get("QueryResponse", {}).get("Account", [])

    def get_transactions(
        self, realm_id: str, access_token: str, refresh_token: str,
        conn: PgConnection, entity_id: int = HOI_ENTITY_ID,
        start_date: str | None = None,
    ) -> list[dict]:
        """QBO Purchase + JournalEntry + Bill 조회 (라인 레벨 추출)."""
        all_lines: list[dict] = []

        for txn_type in ("Purchase", "JournalEntry", "Bill"):
            offset = 1
            while True:
                where = f"WHERE MetaData.LastUpdatedTime > '{start_date}'" if start_date else ""
                query = f"SELECT * FROM {txn_type} {where} STARTPOSITION {offset} MAXRESULTS 1000"
                data = self._request(
                    "GET", f"query?query={query}",
                    realm_id, access_token, refresh_token, conn, entity_id,
                )
                items = data.get("QueryResponse", {}).get(txn_type, [])
                if not items:
                    break

                for item in items:
                    lines = self._extract_lines(item, txn_type)
                    all_lines.extend(lines)

                if len(items) < 1000:
                    break
                offset += 1000

        return all_lines

    def _extract_lines(self, item: dict, txn_type: str) -> list[dict]:
        """QBO 거래에서 라인 레벨 데이터 추출."""
        lines = []
        txn_id = item.get("Id", "")
        txn_date = item.get("TxnDate", "")

        if txn_type == "Purchase":
            payee = (
                item.get("EntityRef", {}).get("name", "")
                if item.get("EntityRef") else ""
            )
            for i, line in enumerate(item.get("Line", []), 1):
                detail = line.get("AccountBasedExpenseLineDetail", {})
                account_ref = detail.get("AccountRef", {})
                lines.append({
                    "qbo_txn_id": txn_id,
                    "txn_type": txn_type,
                    "txn_date": txn_date,
                    "payee": payee,
                    "account_name": account_ref.get("name", ""),
                    "qbo_account_id": account_ref.get("value", ""),
                    "line_number": i,
                    "memo": line.get("Description", ""),
                    "amount": abs(float(line.get("Amount", 0))),
                })
        elif txn_type == "JournalEntry":
            for i, line in enumerate(item.get("Line", []), 1):
                detail = line.get("JournalEntryLineDetail", {})
                account_ref = detail.get("AccountRef", {})
                entity_ref = detail.get("Entity", {})
                lines.append({
                    "qbo_txn_id": txn_id,
                    "txn_type": txn_type,
                    "txn_date": txn_date,
                    "payee": entity_ref.get("name", "") if entity_ref else "",
                    "account_name": account_ref.get("name", ""),
                    "qbo_account_id": account_ref.get("value", ""),
                    "line_number": i,
                    "memo": line.get("Description", ""),
                    "amount": abs(float(line.get("Amount", 0))),
                })
        elif txn_type == "Bill":
            payee = (
                item.get("VendorRef", {}).get("name", "")
                if item.get("VendorRef") else ""
            )
            for i, line in enumerate(item.get("Line", []), 1):
                detail = line.get("AccountBasedExpenseLineDetail", {})
                if not detail:
                    detail = line.get("ItemBasedExpenseLineDetail", {})
                account_ref = detail.get("AccountRef", {})
                lines.append({
                    "qbo_txn_id": txn_id,
                    "txn_type": txn_type,
                    "txn_date": txn_date,
                    "payee": payee,
                    "account_name": account_ref.get("name", ""),
                    "qbo_account_id": account_ref.get("value", ""),
                    "line_number": i,
                    "memo": line.get("Description", ""),
                    "amount": abs(float(line.get("Amount", 0))),
                })

        return lines

    # ── Sync ─────────────────────────────────────────────────

    def sync_accounts(self, conn: PgConnection, entity_id: int = HOI_ENTITY_ID) -> dict:
        """QBO accounts → qbo_accounts 테이블 동기화 (UPSERT)."""
        realm_id, access_token, refresh_token = _load_tokens(conn, entity_id)
        accounts = self.get_accounts(realm_id, access_token, refresh_token, conn, entity_id)

        cur = conn.cursor()
        synced = 0
        for acct in accounts:
            cur.execute(
                """
                INSERT INTO qbo_accounts (entity_id, qbo_id, name, account_type, account_sub_type, full_name, synced_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (entity_id, qbo_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    account_type = EXCLUDED.account_type,
                    account_sub_type = EXCLUDED.account_sub_type,
                    full_name = EXCLUDED.full_name,
                    synced_at = NOW()
                """,
                [
                    entity_id,
                    acct.get("Id", ""),
                    acct.get("Name", ""),
                    acct.get("AccountType", ""),
                    acct.get("AccountSubType", ""),
                    acct.get("FullyQualifiedName", ""),
                ],
            )
            synced += 1
        cur.close()

        logger.info("QBO sync_accounts: entity=%d, synced=%d", entity_id, synced)
        return {"synced": synced, "total": len(accounts)}

    def sync_transactions(
        self, conn: PgConnection, entity_id: int = HOI_ENTITY_ID,
        start_date: str | None = None,
    ) -> dict:
        """QBO transactions → qbo_transaction_lines 동기화 (UPSERT)."""
        realm_id, access_token, refresh_token = _load_tokens(conn, entity_id)
        lines = self.get_transactions(realm_id, access_token, refresh_token, conn, entity_id, start_date)

        cur = conn.cursor()
        synced = 0
        duplicates = 0
        for line in lines:
            cur.execute(
                """
                INSERT INTO qbo_transaction_lines
                    (entity_id, qbo_txn_id, txn_type, txn_date, payee,
                     account_name, qbo_account_id, line_number, memo, amount, synced_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (entity_id, qbo_txn_id, qbo_account_id, line_number)
                DO UPDATE SET
                    payee = EXCLUDED.payee,
                    account_name = EXCLUDED.account_name,
                    memo = EXCLUDED.memo,
                    amount = EXCLUDED.amount,
                    synced_at = NOW()
                """,
                [
                    entity_id,
                    line["qbo_txn_id"],
                    line["txn_type"],
                    line["txn_date"] or None,
                    line["payee"],
                    line["account_name"],
                    line["qbo_account_id"],
                    line["line_number"],
                    line["memo"],
                    line["amount"],
                ],
            )
            synced += 1
        cur.close()

        logger.info(
            "QBO sync_transactions: entity=%d, synced=%d, total=%d",
            entity_id, synced, len(lines),
        )
        return {"synced": synced, "duplicates": duplicates, "total_fetched": len(lines)}

    # ── Seed ─────────────────────────────────────────────────

    def seed_mapping_rules(self, conn: PgConnection, entity_id: int = HOI_ENTITY_ID) -> dict:
        """QBO 거래 기반 mapping_rules 자동 시드 (80% 룰 + gaap_mapping 경유).

        Returns:
            {seeded, skipped, unmapped: list, validation: {total, matched, unmatched, match_rate}}
        """
        cur = conn.cursor()

        # 1. gaap_mapping 검증: QBO accounts와 매칭률 확인
        validation = self._validate_gaap_coverage(cur, entity_id)

        # 2. Payee 빈도 분석
        cur.execute(
            """
            SELECT payee, account_name, qbo_account_id, COUNT(*) as cnt
            FROM qbo_transaction_lines
            WHERE entity_id = %s AND payee IS NOT NULL AND payee != ''
            GROUP BY payee, account_name, qbo_account_id
            ORDER BY payee, cnt DESC
            """,
            [entity_id],
        )
        rows = cur.fetchall()

        # payee별 총 건수 및 지배적 계정
        payee_totals: dict[str, int] = {}
        payee_top: dict[str, tuple] = {}  # payee → (account_name, qbo_account_id, count)
        for payee, account_name, qbo_account_id, cnt in rows:
            payee_totals[payee] = payee_totals.get(payee, 0) + cnt
            if payee not in payee_top or cnt > payee_top[payee][2]:
                payee_top[payee] = (account_name, qbo_account_id, cnt)

        # 3. gaap_mapping → standard_account_id 매핑 로드
        cur.execute(
            """
            SELECT gm.us_gaap_name, gm.standard_account_id
            FROM gaap_mapping gm
            WHERE gm.standard_account_id IS NOT NULL
            """
        )
        gaap_map: dict[str, int] = {}
        for us_name, std_id in cur.fetchall():
            gaap_map[us_name.lower()] = std_id

        # 4. QBO account → account_type/sub_type 로드
        cur.execute(
            "SELECT qbo_id, account_type, account_sub_type FROM qbo_accounts WHERE entity_id = %s",
            [entity_id],
        )
        qbo_acct_types: dict[str, tuple] = {}
        for qbo_id, acct_type, sub_type in cur.fetchall():
            qbo_acct_types[qbo_id] = (acct_type, sub_type)

        # 5. Mercury counterparty 목록 (fuzzy matching용)
        cur.execute(
            "SELECT DISTINCT counterparty FROM transactions WHERE entity_id = %s AND counterparty IS NOT NULL",
            [entity_id],
        )
        mercury_counterparties = [r[0] for r in cur.fetchall()]

        seeded = 0
        skipped = 0
        unmapped: list[dict] = []

        for payee, (account_name, qbo_account_id, top_cnt) in payee_top.items():
            total = payee_totals[payee]

            # 80% 룰: 3건 이상 & 80% 이상
            if total < 3 or (top_cnt / total) < 0.80:
                skipped += 1
                continue

            # QBO account → US GAAP → standard_account_id
            acct_info = qbo_acct_types.get(qbo_account_id, ("", ""))
            us_gaap_name = _normalize_qbo_account_type(acct_info[0], acct_info[1])
            if not us_gaap_name:
                unmapped.append({"payee": payee, "account_name": account_name, "reason": "no_gaap_mapping"})
                skipped += 1
                continue

            std_id = gaap_map.get(us_gaap_name.lower())
            if not std_id:
                unmapped.append({"payee": payee, "account_name": account_name, "us_gaap": us_gaap_name, "reason": "gaap_not_in_db"})
                skipped += 1
                continue

            # standard_account_id → internal_account_id
            cur.execute(
                "SELECT id FROM internal_accounts WHERE entity_id = %s AND standard_account_id = %s AND is_active = TRUE LIMIT 1",
                [entity_id, std_id],
            )
            row = cur.fetchone()
            if not row:
                unmapped.append({"payee": payee, "account_name": account_name, "standard_account_id": std_id, "reason": "no_internal_account"})
                skipped += 1
                continue
            internal_id = row[0]

            # 기존 confirmed 규칙 확인 — 있으면 스킵
            normalized = _normalize_payee(payee)
            if not normalized:
                skipped += 1
                continue

            cur.execute(
                """
                SELECT id FROM mapping_rules
                WHERE entity_id = %s AND counterparty_pattern = %s AND hit_count >= 3
                LIMIT 1
                """,
                [entity_id, normalized],
            )
            if cur.fetchone():
                skipped += 1
                continue

            # Fuzzy matching: 가장 유사한 Mercury counterparty 찾기
            best_counterparty = normalized
            if mercury_counterparties:
                norm_mercury = [(cp, _normalize_payee(cp)) for cp in mercury_counterparties]
                for orig_cp, norm_cp in norm_mercury:
                    if norm_cp and difflib.SequenceMatcher(None, normalized, norm_cp).ratio() >= 0.8:
                        best_counterparty = orig_cp.lower().strip()
                        break

            confidence = round(top_cnt / total, 2)

            # INSERT or UPDATE
            cur.execute(
                """
                INSERT INTO mapping_rules
                    (entity_id, counterparty_pattern, standard_account_id, internal_account_id,
                     confidence, vendor, category, source, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'qbo_seed', NOW(), NOW())
                ON CONFLICT (entity_id, counterparty_pattern)
                    WHERE source = 'qbo_seed'
                DO UPDATE SET
                    standard_account_id = EXCLUDED.standard_account_id,
                    internal_account_id = EXCLUDED.internal_account_id,
                    confidence = EXCLUDED.confidence,
                    vendor = EXCLUDED.vendor,
                    category = EXCLUDED.category,
                    updated_at = NOW()
                """,
                [entity_id, best_counterparty, std_id, internal_id, confidence, payee, acct_info[0]],
            )
            seeded += 1

        cur.close()
        logger.info(
            "QBO seed_mapping_rules: entity=%d, seeded=%d, skipped=%d, unmapped=%d",
            entity_id, seeded, skipped, len(unmapped),
        )
        return {
            "seeded": seeded,
            "skipped": skipped,
            "unmapped": unmapped,
            "validation": validation,
        }

    def _validate_gaap_coverage(self, cur, entity_id: int) -> dict:
        """QBO accounts vs gaap_mapping 매칭률 검증."""
        cur.execute(
            "SELECT qbo_id, name, account_type, account_sub_type FROM qbo_accounts WHERE entity_id = %s",
            [entity_id],
        )
        qbo_accounts = cur.fetchall()

        cur.execute("SELECT LOWER(us_gaap_name) FROM gaap_mapping WHERE standard_account_id IS NOT NULL")
        gaap_names = {r[0] for r in cur.fetchall()}

        total = len(qbo_accounts)
        matched = 0
        unmatched_list = []

        for qbo_id, name, acct_type, sub_type in qbo_accounts:
            us_gaap = _normalize_qbo_account_type(acct_type, sub_type)
            if us_gaap and us_gaap.lower() in gaap_names:
                matched += 1
            else:
                unmatched_list.append({"qbo_id": qbo_id, "name": name, "type": acct_type, "sub_type": sub_type})

        match_rate = (matched / total * 100) if total > 0 else 0
        if match_rate < 70:
            logger.warning(
                "QBO gaap_mapping coverage LOW: %d/%d (%.0f%%) — seeding may be incomplete",
                matched, total, match_rate,
            )

        return {
            "total": total,
            "matched": matched,
            "unmatched": len(unmatched_list),
            "match_rate": round(match_rate, 1),
            "unmatched_accounts": unmatched_list[:10],
        }


# ── Token helpers ────────────────────────────────────────────

def _load_tokens(conn: PgConnection, entity_id: int) -> tuple[str, str, str]:
    """settings 테이블에서 QBO OAuth 토큰 로드."""
    cur = conn.cursor()
    tokens = {}
    for key in ("qbo_realm_id", "qbo_access_token", "qbo_refresh_token"):
        cur.execute(
            "SELECT value FROM settings WHERE key = %s AND entity_id = %s",
            [key, entity_id],
        )
        row = cur.fetchone()
        tokens[key] = row[0] if row else ""
    cur.close()

    if not tokens["qbo_access_token"]:
        raise QBOError("QBO not connected — no access token found")

    return tokens["qbo_realm_id"], tokens["qbo_access_token"], tokens["qbo_refresh_token"]


def _save_tokens(conn: PgConnection, entity_id: int, tokens: dict) -> None:
    """settings 테이블에 QBO OAuth 토큰 저장."""
    cur = conn.cursor()
    for key, value in [
        ("qbo_access_token", tokens.get("access_token", "")),
        ("qbo_refresh_token", tokens.get("refresh_token", "")),
        ("qbo_realm_id", tokens.get("realm_id", "")),
    ]:
        if not value:
            continue
        cur.execute(
            """
            INSERT INTO settings (key, value, entity_id, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (key, entity_id) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            [key, value, entity_id],
        )
    cur.close()


def generate_csrf_state(entity_id: int) -> str:
    """CSRF 방지용 OAuth state 생성."""
    return f"{entity_id}:{secrets.token_urlsafe(32)}"


def validate_csrf_state(state: str, stored_state: str) -> tuple[bool, int]:
    """OAuth state 검증. Returns (valid, entity_id)."""
    if not state or not stored_state or state != stored_state:
        return False, 0
    parts = state.split(":", 1)
    if len(parts) != 2:
        return False, 0
    try:
        return True, int(parts[0])
    except ValueError:
        return False, 0

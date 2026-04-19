"""ExpenseOne 연동 — 승인된 경비를 FinanceOne transactions로 Smart Pull + Auto-Map

- Supabase SERVICE_ROLE_KEY로 PostgREST 직접 조회
- expense_id 기반 중복 감지 + 날짜/금액 fuzzy match로 기존 거래 보강
- mapping_rules 캐스케이드 + category → internal_account 이름 매칭
- 한아원코리아 (entity_id=2) 전용 (설계 기준)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional

import httpx
from psycopg2.extensions import connection as PgConnection

from backend.services.mapping_service import auto_map_transaction

logger = logging.getLogger(__name__)

# 한아원코리아 entity_id (설계 상수)
EXPENSEONE_ENTITY_ID = int(os.environ.get("EXPENSEONE_ENTITY_ID", "2"))

# CORPORATE_CARD → 카드 출금, DEPOSIT_REQUEST → 은행 출금
SOURCE_TYPE_CARD = "expenseone_card"
SOURCE_TYPE_DEPOSIT = "expenseone_deposit"

# 프리셋 카테고리 (INTEGRATION.md) — 내부계정 이름 fallback 매핑
PRESET_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "ODD": ("ODD", "용역비", "외주"),
    "MART_PHARMACY": ("마트", "약국", "마트/약국"),
    "마트/약국": ("마트", "약국", "마트/약국"),
    "OTHER": (),
    "기타": (),
}


class ExpenseOneError(Exception):
    pass


class ExpenseOneClient:
    """ExpenseOne Supabase 읽기 클라이언트 + FinanceOne sync."""

    def __init__(self, supabase_url: str, service_role_key: str):
        if not supabase_url or not service_role_key:
            raise ExpenseOneError("ExpenseOne credentials missing")
        self.base_url = supabase_url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Accept": "application/json",
        }
        self.client = httpx.Client(timeout=30.0, headers=self.headers)

    def close(self) -> None:
        self.client.close()

    # ── Fetch ────────────────────────────────────────────────

    def fetch_approved(self, since_date: Optional[str] = None) -> list[dict]:
        """승인된 경비 조회 (+제출자 이름 join).

        ExpenseOne: expenses.status='APPROVED', 선택적으로 approvedAt ≥ since_date
        제출자는 users.name을 left-join으로 가져옴.
        """
        params: dict[str, Any] = {
            "select": "*,submitter:users!expenses_submittedById_fkey(id,name,email)",
            "status": "eq.APPROVED",
            "order": "approvedAt.asc",
            "limit": "1000",
        }
        if since_date:
            params["approvedAt"] = f"gte.{since_date}"

        resp = self.client.get(f"{self.base_url}/expenses", params=params)
        if resp.status_code != 200:
            logger.error("ExpenseOne fetch failed: %d %s", resp.status_code, resp.text[:200])
            raise ExpenseOneError(f"fetch failed: HTTP {resp.status_code}")
        return resp.json()

    def check_connection(self) -> dict:
        """연결 상태 확인 (expenses 테이블 접근 가능 여부)."""
        resp = self.client.get(
            f"{self.base_url}/expenses",
            params={"select": "id", "limit": "1"},
        )
        if resp.status_code != 200:
            return {
                "connected": False,
                "error": f"HTTP {resp.status_code}",
            }
        return {"connected": True}

    # ── Sync ─────────────────────────────────────────────────

    def sync_to_financeone(
        self,
        conn: PgConnection,
        entity_id: int,
        expenses: list[dict],
    ) -> dict:
        """승인된 경비를 transactions에 INSERT (중복은 SKIP/UPDATE).

        Returns:
            {total_fetched, inserted, enriched, duplicates, unmapped, errors}
        """
        cur = conn.cursor()

        inserted = 0
        enriched = 0
        duplicates = 0
        unmapped = 0
        errors: list[dict] = []

        # 내부계정 이름 → id 캐시 (카테고리 fallback 용)
        cur.execute(
            """
            SELECT id, name, standard_account_id
            FROM internal_accounts
            WHERE entity_id = %s AND is_active = TRUE
            """,
            [entity_id],
        )
        name_to_account = {}
        for iid, name, std_id in cur.fetchall():
            name_to_account[name.lower()] = (iid, std_id)

        for exp in expenses:
            try:
                result = self._upsert_expense(cur, entity_id, exp, name_to_account)
                if result == "inserted":
                    inserted += 1
                elif result == "enriched":
                    enriched += 1
                elif result == "duplicate":
                    duplicates += 1
                elif result == "unmapped":
                    unmapped += 1
                    inserted += 1  # 여전히 insert되긴 함
            except Exception as e:
                logger.exception("expense sync failed: id=%s", exp.get("id"))
                errors.append({"expense_id": exp.get("id"), "error": str(e)})

        cur.close()

        summary = {
            "total_fetched": len(expenses),
            "inserted": inserted,
            "enriched": enriched,
            "duplicates": duplicates,
            "unmapped": unmapped,
            "errors": errors,
        }
        logger.info("ExpenseOne sync: %s", summary)
        return summary

    def _upsert_expense(
        self,
        cur,
        entity_id: int,
        exp: dict,
        name_to_account: dict[str, tuple[int, int | None]],
    ) -> str:
        """단일 경비 처리. Returns 'inserted'|'enriched'|'duplicate'|'unmapped'."""
        expense_id = exp.get("id")
        exp_type = exp.get("type") or ""
        amount_val = exp.get("amount") or 0
        txn_date_raw = exp.get("transactionDate") or exp.get("approvedAt") or ""
        txn_date = _parse_date(txn_date_raw)
        if not txn_date or amount_val <= 0:
            raise ExpenseOneError(f"invalid date/amount: date={txn_date_raw}, amount={amount_val}")

        merchant = exp.get("merchantName") or ""
        account_holder = exp.get("accountHolder") or ""
        title = exp.get("title") or ""
        description_text = exp.get("description") or title
        category = exp.get("category") or ""
        submitter = exp.get("submitter") or {}
        submitted_by = submitter.get("name") or submitter.get("email") or ""

        if exp_type == "CORPORATE_CARD":
            source_type = SOURCE_TYPE_CARD
            counterparty = merchant or title
        elif exp_type == "DEPOSIT_REQUEST":
            source_type = SOURCE_TYPE_DEPOSIT
            counterparty = account_holder or merchant or title
        else:
            source_type = "expenseone"
            counterparty = merchant or account_holder or title

        note_parts = []
        if category:
            note_parts.append(f"category={category}")
        if exp.get("isPrePaid") and exp.get("prePaidPercentage"):
            note_parts.append(f"선지급 {exp['prePaidPercentage']}%")
        if exp.get("isUrgent"):
            note_parts.append("긴급")
        note = " | ".join(note_parts) if note_parts else None

        # Level 1: expense_id 정확 매칭
        cur.execute(
            "SELECT id FROM transactions WHERE expense_id = %s LIMIT 1",
            [expense_id],
        )
        if cur.fetchone():
            return "duplicate"

        # Level 2: 날짜(±1일) + 금액 + description/counterparty ILIKE merchant fuzzy
        fuzzy_row = None
        if merchant:
            cur.execute(
                """
                SELECT id FROM transactions
                WHERE entity_id = %s
                  AND expense_id IS NULL
                  AND date BETWEEN (%s::date - INTERVAL '1 day') AND (%s::date + INTERVAL '1 day')
                  AND amount = %s
                  AND (description ILIKE %s OR counterparty ILIKE %s)
                ORDER BY date DESC
                LIMIT 1
                """,
                [entity_id, txn_date, txn_date, amount_val,
                 f"%{merchant}%", f"%{merchant}%"],
            )
            fuzzy_row = cur.fetchone()

        if fuzzy_row:
            # 기존 거래에 ExpenseOne 메타데이터 보강
            cur.execute(
                """
                UPDATE transactions
                SET expense_id = %s,
                    expense_submitted_by = %s,
                    expense_title = %s,
                    note = COALESCE(note, '') ||
                           CASE WHEN note IS NULL OR note = '' THEN '' ELSE ' | ' END ||
                           COALESCE(%s, ''),
                    updated_at = NOW()
                WHERE id = %s
                """,
                [expense_id, submitted_by, title, note, fuzzy_row[0]],
            )
            return "enriched"

        # 자동 매핑 (mapping_rules 캐스케이드)
        mapping = auto_map_transaction(
            cur,
            entity_id=entity_id,
            counterparty=counterparty,
            description=description_text,
        )

        # category fallback: 프리셋 힌트 + 카테고리 직접매칭
        if not mapping and category:
            mapping = _category_fallback(cur, entity_id, category, name_to_account)

        internal_account_id = mapping["internal_account_id"] if mapping else None
        standard_account_id = mapping.get("standard_account_id") if mapping else None
        confidence = mapping.get("confidence") if mapping else None
        match_type = mapping.get("match_type", "expenseone_category") if mapping else None

        cur.execute(
            """
            INSERT INTO transactions
                (entity_id, date, amount, currency, type,
                 description, counterparty, source_type,
                 internal_account_id, standard_account_id,
                 mapping_confidence, mapping_source,
                 expense_id, expense_submitted_by, expense_title,
                 note, created_at, updated_at)
            VALUES (%s, %s, %s, 'KRW', 'out',
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, NOW(), NOW())
            """,
            [
                entity_id, txn_date, amount_val,
                description_text or title, counterparty, source_type,
                internal_account_id, standard_account_id,
                confidence, match_type,
                expense_id, submitted_by, title,
                note,
            ],
        )

        return "unmapped" if internal_account_id is None else "inserted"


# ── Helpers ──────────────────────────────────────────────────


def _parse_date(raw: str) -> Optional[str]:
    """ExpenseOne date (YYYY-MM-DD 또는 ISO) → date string."""
    if not raw:
        return None
    # 이미 date 형식
    if len(raw) == 10 and raw[4] == "-":
        return raw
    # ISO timestamp
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _category_fallback(
    cur,
    entity_id: int,
    category: str,
    name_to_account: dict[str, tuple[int, int | None]],
) -> dict | None:
    """category → internal_account 이름 매칭.

    1. PRESET_CATEGORY_HINTS의 힌트 순회
    2. category 자체와 내부계정 이름 direct 매칭
    """
    candidates: list[str] = []
    hints = PRESET_CATEGORY_HINTS.get(category, ())
    candidates.extend(hints)
    candidates.append(category)

    for cand in candidates:
        if not cand:
            continue
        key = cand.lower()
        if key in name_to_account:
            iid, std_id = name_to_account[key]
            return {
                "internal_account_id": iid,
                "standard_account_id": std_id,
                "confidence": 0.6,
                "match_type": "expenseone_category",
            }

    # 부분 일치 (ILIKE)
    cur.execute(
        """
        SELECT id, standard_account_id
        FROM internal_accounts
        WHERE entity_id = %s AND is_active = TRUE
          AND name ILIKE %s
        ORDER BY length(name)
        LIMIT 1
        """,
        [entity_id, f"%{category}%"],
    )
    row = cur.fetchone()
    if row:
        return {
            "internal_account_id": row[0],
            "standard_account_id": row[1],
            "confidence": 0.55,
            "match_type": "expenseone_category",
        }

    return None


def load_credentials() -> tuple[str, str]:
    """환경변수에서 ExpenseOne 인증정보 로드."""
    url = os.environ.get("EXPENSEONE_SUPABASE_URL", "")
    key = os.environ.get("EXPENSEONE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise ExpenseOneError(
            "EXPENSEONE_SUPABASE_URL / EXPENSEONE_SERVICE_ROLE_KEY not configured in .env"
        )
    return url, key

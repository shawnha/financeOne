"""ExpenseOne 연동 — 같은 Supabase 프로젝트의 expenseone 스키마 직접 조회

- FinanceOne과 동일 Supabase 프로젝트 (kxsofwbwzoovnwgxiwgi)
- expenseone.expenses, expenseone.users 직접 SELECT (SERVICE_ROLE_KEY 불필요)
- expense_id 기반 중복 감지 + 날짜/금액 fuzzy match로 기존 거래 보강
- mapping_rules 캐스케이드 + category → internal_account 이름 매칭
- 한아원코리아 (entity_id=2) 전용 (설계 기준)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any, Optional

from psycopg2.extensions import connection as PgConnection

from backend.services.mapping_service import auto_map_transaction

logger = logging.getLogger(__name__)

EXPENSEONE_ENTITY_ID = int(os.environ.get("EXPENSEONE_ENTITY_ID", "2"))

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


def check_connection(conn: PgConnection) -> dict:
    """expenseone 스키마 접근 가능 여부 확인."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'expenseone' AND table_name = 'expenses'"
        )
        row = cur.fetchone()
        if not row or row[0] == 0:
            return {"connected": False, "error": "expenseone.expenses 테이블 없음"}
        return {"connected": True}
    except Exception as e:
        logger.exception("expenseone connection check failed")
        return {"connected": False, "error": str(e)[:100]}
    finally:
        cur.close()


def fetch_approved(conn: PgConnection, since_date: Optional[str] = None) -> list[dict]:
    """승인된 경비 조회 (+ 제출자 이름 join).

    expenseone.expenses WHERE status='APPROVED' [AND approved_at >= since_date].
    """
    cur = conn.cursor()
    try:
        where = ["e.status = 'APPROVED'"]
        params: list[Any] = []
        if since_date:
            where.append("e.approved_at >= %s")
            params.append(since_date)

        sql = f"""
            SELECT
                e.id, e.type, e.status, e.title, e.description, e.amount, e.category,
                e.merchant_name, e.transaction_date, e.card_last_four,
                e.bank_name, e.account_holder,
                e.is_urgent, e.is_pre_paid, e.pre_paid_percentage,
                e.approved_at, e.created_at, e.company_id,
                u.name AS submitter_name, u.email AS submitter_email
            FROM expenseone.expenses e
            LEFT JOIN expenseone.users u ON e.submitted_by_id = u.id
            WHERE {' AND '.join(where)}
            ORDER BY e.approved_at ASC
        """
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def get_synced_stats(conn: PgConnection, entity_id: int) -> dict:
    """동기화 통계 — transactions.expense_id 기준."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*), MAX(updated_at)
            FROM transactions
            WHERE entity_id = %s AND expense_id IS NOT NULL
            """,
            [entity_id],
        )
        row = cur.fetchone()
        synced_count = row[0] if row else 0
        last_sync = row[1].isoformat() if row and row[1] else None
        return {"synced_count": synced_count, "last_sync": last_sync}
    finally:
        cur.close()


def sync_to_financeone(
    conn: PgConnection,
    entity_id: int,
    expenses: list[dict],
) -> dict:
    """승인 경비 → 카드/은행 거래에 매칭만 (transactions INSERT 안 함).

    expense.company_id → entity_id 자동 라우팅 (한아원코리아=2, 한아원리테일=3, HOI=1).
    entity_id 인자는 무시 (기존 호환용 — 모든 회사 자동 처리).

    매칭 성공: transaction_expenseone_match에 link
    매칭 실패: unmatched (별도 매칭 메뉴에서 수동 처리)
    entity 미매핑: skip + 에러 로그

    Returns:
        {total_fetched, matched_card, matched_deposit, unmatched, already_linked,
         no_entity_mapping, errors, by_entity}
    """
    from backend.services.expenseone_matcher import (
        find_card_match, find_deposit_match, insert_match, get_entity_for_company,
    )

    cur = conn.cursor()
    matched_card = 0
    matched_deposit = 0
    unmatched = 0
    already_linked = 0
    no_entity_mapping = 0
    by_entity: dict[int, int] = {}
    errors: list[dict] = []

    # company_id → entity_id 캐시
    entity_cache: dict[str, Optional[int]] = {}

    for exp in expenses:
        expense_id = str(exp.get("id"))
        try:
            # 이미 매칭 있으면 skip
            cur.execute(
                "SELECT 1 FROM transaction_expenseone_match WHERE expense_id = %s LIMIT 1",
                [expense_id],
            )
            if cur.fetchone():
                already_linked += 1
                continue

            company_id = str(exp.get("company_id") or "")
            if company_id and company_id not in entity_cache:
                entity_cache[company_id] = get_entity_for_company(cur, company_id)
            target_entity = entity_cache.get(company_id)
            if not target_entity:
                no_entity_mapping += 1
                continue

            exp_type = exp.get("type") or ""
            amount = exp.get("amount") or 0
            txn_date_raw = exp.get("transaction_date") or exp.get("approved_at") or ""
            txn_date = _parse_date(txn_date_raw)
            if not txn_date or amount <= 0:
                continue

            match = None
            if exp_type == "CORPORATE_CARD":
                match = find_card_match(
                    cur, target_entity,
                    expense_date=txn_date, amount=amount,
                    card_last4=exp.get("card_last_four"),
                    merchant=exp.get("merchant_name") or exp.get("title"),
                )
                if match:
                    matched_card += 1
            elif exp_type == "DEPOSIT_REQUEST":
                approved_date = _parse_date(exp.get("approved_at")) or txn_date
                match = find_deposit_match(
                    cur, target_entity,
                    approved_date=approved_date, amount=amount,
                    account_holder=exp.get("account_holder"),
                )
                if match:
                    matched_deposit += 1

            if match:
                insert_match(
                    cur,
                    transaction_id=match["transaction_id"],
                    expense_id=expense_id,
                    expense_type=exp_type,
                    confidence=match["confidence"],
                    method=match["method"],
                    reasoning=f"entity={target_entity} | {match['reasoning']}",
                )
                by_entity[target_entity] = by_entity.get(target_entity, 0) + 1
            else:
                unmatched += 1
        except Exception as e:
            logger.exception("expense match failed: id=%s", expense_id)
            errors.append({"expense_id": expense_id, "error": str(e)[:200]})

    cur.close()
    summary = {
        "total_fetched": len(expenses),
        "matched_card": matched_card,
        "matched_deposit": matched_deposit,
        "unmatched": unmatched,
        "already_linked": already_linked,
        "no_entity_mapping": no_entity_mapping,
        "by_entity": by_entity,
        "errors": errors,
    }
    logger.info("ExpenseOne match: %s", summary)
    return summary


def _upsert_expense(
    cur,
    entity_id: int,
    exp: dict,
    name_to_account: dict[str, tuple[int, int | None]],
) -> str:
    """단일 경비 처리. Returns 'inserted'|'enriched'|'duplicate'|'unmapped'."""
    expense_id = exp.get("id")
    exp_type = exp.get("type") or ""
    amount_val = exp.get("amount") or 0
    txn_date_raw = exp.get("transaction_date") or exp.get("approved_at") or ""
    txn_date = _parse_date(txn_date_raw)
    if not txn_date or amount_val <= 0:
        raise ExpenseOneError(f"invalid date/amount: date={txn_date_raw}, amount={amount_val}")

    merchant = exp.get("merchant_name") or ""
    account_holder = exp.get("account_holder") or ""
    title = exp.get("title") or ""
    description_text = exp.get("description") or title
    category = exp.get("category") or ""
    submitted_by = exp.get("submitter_name") or exp.get("submitter_email") or ""

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
    if exp.get("is_pre_paid") and exp.get("pre_paid_percentage"):
        note_parts.append(f"선지급 {exp['pre_paid_percentage']}%")
    if exp.get("is_urgent"):
        note_parts.append("긴급")
    note = " | ".join(note_parts) if note_parts else None

    # Level 1: expense_id 정확 매칭
    cur.execute(
        "SELECT id FROM transactions WHERE expense_id = %s LIMIT 1",
        [str(expense_id)],
    )
    if cur.fetchone():
        return "duplicate"

    # Level 2: 날짜(±1일) + 금액 + description/counterparty ILIKE merchant
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
            [str(expense_id), submitted_by, title, note, fuzzy_row[0]],
        )
        return "enriched"

    # 자동 매핑 (cascade)
    mapping = auto_map_transaction(
        cur,
        entity_id=entity_id,
        counterparty=counterparty,
        description=description_text,
    )

    # category fallback
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
            str(expense_id), submitted_by, title,
            note,
        ],
    )

    return "unmapped" if internal_account_id is None else "inserted"


# ── Helpers ──────────────────────────────────────────────


def _parse_date(raw) -> Optional[str]:
    """date/datetime/string → YYYY-MM-DD string."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw.isoformat()
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if not isinstance(raw, str):
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
    """category → internal_account 이름 매칭."""
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

"""ExpenseOne ↔ 거래 자동 매칭 서비스.

ExpenseOne 거래는 transactions 테이블에 INSERT 안 함.
대신 카드 거래(lotte_card 등) 또는 은행 출금(woori_bank)에 매칭하여
transaction_expenseone_match join 테이블에 link.

매칭 로직:
- 카드 (CORPORATE_CARD):
    1) date(±1) + amount + card_last4 → confidence 0.95
    2) date(±3) + amount + 가맹점명 ILIKE merchant → confidence 0.75
- 입금요청 (DEPOSIT_REQUEST):
    1) date(±3) + amount + counterparty ILIKE account_holder → confidence 0.90
    2) date(±7) + amount → confidence 0.60
"""

from __future__ import annotations

import logging
from typing import Optional

from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)


# ── ExpenseOne company_id ↔ FinanceOne entity_id ─────────
# 회사명 기반 자동 매핑 (companies 테이블 + entities 테이블 join)
def get_entity_for_company(cur, company_id: str) -> Optional[int]:
    """ExpenseOne company_id → FinanceOne entity_id 매핑.

    매칭 규칙: companies.name이 entities.name에 포함되거나 반대로 포함되면 같은 회사.
    예: '한아원코리아' ↔ '주식회사 한아원코리아', 'HOI' ↔ 'HOI Inc.'
    """
    if not company_id:
        return None
    cur.execute(
        """
        SELECT ent.id
        FROM expenseone.companies c
        JOIN financeone.entities ent
          ON ent.name LIKE '%%' || c.name || '%%' OR c.name LIKE '%%' || ent.name || '%%'
        WHERE c.id = %s AND ent.is_active = TRUE
        LIMIT 1
        """,
        [company_id],
    )
    row = cur.fetchone()
    return row[0] if row else None


# ── 카드 매칭 ──────────────────────────────────────


def find_card_match(
    cur,
    entity_id: int,
    expense_date: str,          # 'YYYY-MM-DD'
    amount,                     # numeric
    card_last4: Optional[str],  # 'XXXX' (4자리)
    merchant: Optional[str] = None,
) -> Optional[dict]:
    """ExpenseOne 카드 expense → 카드 거래 1건 자동 매칭 시도.

    Returns: {transaction_id, confidence, method, reasoning} or None.
    """
    if not amount or amount <= 0:
        return None

    # 1) 정확 매칭 — 날짜 ±1일, 같은 금액, 같은 카드 끝4자리
    if card_last4:
        masked = f"****{card_last4}"
        cur.execute(
            """
            SELECT id, date, amount, counterparty
            FROM transactions
            WHERE entity_id = %s
              AND source_type IN ('lotte_card','woori_card','shinhan_card',
                                  'codef_lotte_card','codef_woori_card','codef_shinhan_card')
              AND date BETWEEN (%s::date - INTERVAL '1 day') AND (%s::date + INTERVAL '1 day')
              AND amount = %s
              AND card_number = %s
              AND id NOT IN (SELECT transaction_id FROM transaction_expenseone_match)
            ORDER BY ABS(date - %s::date) ASC
            LIMIT 1
            """,
            [entity_id, expense_date, expense_date, amount, masked, expense_date],
        )
        row = cur.fetchone()
        if row:
            return {
                "transaction_id": row[0],
                "confidence": 0.95,
                "method": "auto_card_exact",
                "reasoning": f"date±1 + amount + card={masked}",
            }

    # 2) 가맹점명 fuzzy — 날짜 ±3일, 같은 금액, counterparty ILIKE merchant
    if merchant and len(merchant) >= 2:
        cur.execute(
            """
            SELECT id, date, counterparty
            FROM transactions
            WHERE entity_id = %s
              AND source_type IN ('lotte_card','woori_card','shinhan_card',
                                  'codef_lotte_card','codef_woori_card','codef_shinhan_card')
              AND date BETWEEN (%s::date - INTERVAL '3 day') AND (%s::date + INTERVAL '3 day')
              AND amount = %s
              AND counterparty ILIKE %s
              AND id NOT IN (SELECT transaction_id FROM transaction_expenseone_match)
            LIMIT 1
            """,
            [entity_id, expense_date, expense_date, amount, f"%{merchant}%"],
        )
        row = cur.fetchone()
        if row:
            return {
                "transaction_id": row[0],
                "confidence": 0.75,
                "method": "auto_card_fuzzy",
                "reasoning": f"date±3 + amount + cp~{merchant[:20]}",
            }

    return None


# ── 입금요청 매칭 ──────────────────────────────────


def find_deposit_match(
    cur,
    entity_id: int,
    approved_date: str,             # 'YYYY-MM-DD' — 승인된 시점
    amount,
    account_holder: Optional[str],
) -> Optional[dict]:
    """ExpenseOne 입금요청 expense → 우리은행 출금 거래 자동 매칭."""
    if not amount or amount <= 0:
        return None

    # 1) 정확 매칭 — 승인일 이후 ±3일, 같은 금액, counterparty ILIKE account_holder
    if account_holder and len(account_holder) >= 2:
        cur.execute(
            """
            SELECT id, date, counterparty
            FROM transactions
            WHERE entity_id = %s
              AND source_type IN ('woori_bank','codef_woori_bank','codef_ibk_bank')
              AND type = 'out'
              AND date BETWEEN (%s::date - INTERVAL '3 day') AND (%s::date + INTERVAL '7 day')
              AND amount = %s
              AND counterparty ILIKE %s
              AND id NOT IN (SELECT transaction_id FROM transaction_expenseone_match)
            ORDER BY ABS(date - %s::date) ASC
            LIMIT 1
            """,
            [entity_id, approved_date, approved_date, amount, f"%{account_holder}%", approved_date],
        )
        row = cur.fetchone()
        if row:
            return {
                "transaction_id": row[0],
                "confidence": 0.90,
                "method": "auto_deposit_exact",
                "reasoning": f"date±3~7 + amount + cp~{account_holder[:15]}",
            }

    # 2) 금액만 매칭 — 약한 신뢰도 (수동 확인 필요)
    cur.execute(
        """
        SELECT id, date, counterparty
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank','codef_woori_bank','codef_ibk_bank')
          AND type = 'out'
          AND date BETWEEN (%s::date - INTERVAL '3 day') AND (%s::date + INTERVAL '7 day')
          AND amount = %s
          AND id NOT IN (SELECT transaction_id FROM transaction_expenseone_match)
        ORDER BY ABS(date - %s::date) ASC
        LIMIT 1
        """,
        [entity_id, approved_date, approved_date, amount, approved_date],
    )
    row = cur.fetchone()
    if row:
        return {
            "transaction_id": row[0],
            "confidence": 0.60,
            "method": "auto_deposit_fuzzy",
            "reasoning": "date±3~7 + amount only (수동 확인 권장)",
        }

    return None


# ── Match 저장 ─────────────────────────────────────


def insert_match(
    cur,
    transaction_id: int,
    expense_id: str,
    expense_type: str,
    confidence: float,
    method: str,
    reasoning: str,
    is_manual: bool = False,
    is_confirmed: bool = False,
) -> int:
    """transaction_expenseone_match에 link INSERT (expense_id 기준 unique)."""
    cur.execute(
        """
        INSERT INTO transaction_expenseone_match
            (transaction_id, expense_id, expense_type, match_confidence,
             match_method, is_manual, is_confirmed, ai_reasoning, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (expense_id) DO UPDATE
            SET transaction_id = EXCLUDED.transaction_id,
                match_confidence = EXCLUDED.match_confidence,
                match_method = EXCLUDED.match_method,
                ai_reasoning = EXCLUDED.ai_reasoning,
                updated_at = NOW()
        RETURNING id
        """,
        [transaction_id, expense_id, expense_type, confidence,
         method, is_manual, is_confirmed, reasoning],
    )
    return cur.fetchone()[0]


def get_match_by_transaction(cur, transaction_id: int) -> Optional[dict]:
    """거래 id로 매칭된 ExpenseOne expense 조회 (있으면 metadata 포함)."""
    cur.execute(
        """
        SELECT m.id, m.expense_id, m.expense_type, m.match_confidence,
               m.match_method, m.is_manual, m.is_confirmed, m.ai_reasoning,
               e.title, e.description, e.merchant_name, e.amount, e.category,
               e.account_holder, e.transaction_date, e.approved_at,
               u.name as submitter_name
        FROM transaction_expenseone_match m
        LEFT JOIN expenseone.expenses e ON m.expense_id = e.id
        LEFT JOIN expenseone.users u ON e.submitted_by_id = u.id
        WHERE m.transaction_id = %s
        LIMIT 1
        """,
        [transaction_id],
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "match_id": row[0],
        "expense_id": str(row[1]),
        "expense_type": row[2],
        "confidence": float(row[3]) if row[3] is not None else None,
        "method": row[4],
        "is_manual": row[5],
        "is_confirmed": row[6],
        "reasoning": row[7],
        "expense": {
            "title": row[8],
            "description": row[9],
            "merchant_name": row[10],
            "amount": int(row[11]) if row[11] else None,
            "category": row[12],
            "account_holder": row[13],
            "transaction_date": row[14].isoformat() if row[14] else None,
            "approved_at": row[15].isoformat() if row[15] else None,
            "submitter_name": row[16],
        },
    }

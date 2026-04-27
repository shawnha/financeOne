"""복식부기 엔진 — 분개 생성, 잔액 조회, 시산표 검증

모든 함수는 conn.commit()을 하지 않음. 호출자가 트랜잭션 제어.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from psycopg2.extensions import connection as PgConnection


DEFAULT_CASH_ACCOUNT_CODE = "10100"
ACCOUNTS_PAYABLE_CODE = "26200"  # 미지급비용 — 카드 사용 시 발생주의 부채

# 카드 source_type → 카드 사용 분개는 (차)비용/(대)미지급비용
CARD_SOURCE_TYPES = {
    "lotte_card", "woori_card", "shinhan_card",
    "codef_lotte_card", "codef_woori_card", "codef_shinhan_card",
    "expenseone_card", "gowid_api",
}

# 은행 거래 중 카드대금 결제로 식별되는 counterparty 패턴.
# 매칭되면 (차)미지급비용/(대)보통예금 으로 분개 (기존: (차)카드대금 비용/(대)현금).
CARD_PAYMENT_COUNTERPARTY_PATTERNS = (
    "롯데카드", "우리카드", "신한카드", "삼성카드", "현대카드",
    "kb국민카드", "국민카드", "하나카드", "비씨카드", "bc카드",
    "농협카드", "nh카드", "카드결제",
)


def get_cash_account_code(conn) -> str:
    """settings 테이블에서 현금 계정 코드 조회. 없으면 기본값 사용."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'cash_account_code' AND entity_id IS NULL")
        row = cur.fetchone()
        cur.close()
        if row and isinstance(row[0], str):
            return row[0]
    except Exception:
        pass
    return DEFAULT_CASH_ACCOUNT_CODE


def _get_cash_account_id(cur) -> int:
    """현금및현금성자산 계정 ID 조회."""
    cur.execute(
        "SELECT id FROM standard_accounts WHERE code = %s",
        [DEFAULT_CASH_ACCOUNT_CODE],
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Cash account {DEFAULT_CASH_ACCOUNT_CODE} not found in standard_accounts")
    return row[0]


def _get_accounts_payable_id(cur) -> int:
    """미지급비용(26200) standard_account ID."""
    cur.execute(
        "SELECT id FROM standard_accounts WHERE code = %s",
        [ACCOUNTS_PAYABLE_CODE],
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Accounts payable account {ACCOUNTS_PAYABLE_CODE} not found")
    return row[0]


def _is_card_payment(counterparty: str | None) -> bool:
    """은행 거래의 counterparty 가 카드대금 결제 패턴인지."""
    if not counterparty:
        return False
    name = counterparty.lower().replace(" ", "")
    return any(pat.lower().replace(" ", "") in name for pat in CARD_PAYMENT_COUNTERPARTY_PATTERNS)


def _quantize(amount) -> Decimal:
    """NUMERIC(18,2) 정밀도로 반올림."""
    return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def create_journal_entry(
    conn: PgConnection,
    entity_id: int,
    lines: list[dict],
    entry_date: date,
    description: str = "",
    transaction_id: int | None = None,
    is_adjusting: bool = False,
    is_closing: bool = False,
) -> int:
    """분개 생성. sum(debit)==sum(credit) 검증 후 INSERT.

    Args:
        lines: [{"standard_account_id": int, "debit_amount": Decimal, "credit_amount": Decimal, "description": str}]

    Returns:
        journal_entry.id

    Raises:
        ValueError: debit != credit 또는 라인 없음
    """
    if not lines:
        raise ValueError("Journal entry must have at least one line")

    total_debit = sum(_quantize(line.get("debit_amount", 0)) for line in lines)
    total_credit = sum(_quantize(line.get("credit_amount", 0)) for line in lines)

    if total_debit != total_credit:
        raise ValueError(
            f"Journal entry imbalanced: debit={total_debit}, credit={total_credit}, "
            f"difference={total_debit - total_credit}"
        )

    if total_debit == 0:
        raise ValueError("Journal entry total cannot be zero")

    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO journal_entries
            (entity_id, transaction_id, entry_date, description, is_adjusting, is_closing)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        [entity_id, transaction_id, entry_date, description, is_adjusting, is_closing],
    )
    je_id = cur.fetchone()[0]

    for i, line in enumerate(lines):
        debit = _quantize(line.get("debit_amount", 0))
        credit = _quantize(line.get("credit_amount", 0))

        cur.execute(
            """
            INSERT INTO journal_entry_lines
                (journal_entry_id, standard_account_id, debit_amount, credit_amount, description, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [je_id, line["standard_account_id"], debit, credit, line.get("description", ""), i + 1],
        )

    cur.close()
    return je_id


def create_journal_from_transaction(
    conn: PgConnection,
    transaction_id: int,
) -> int:
    """확정된 거래 → 분개 자동 생성.

    - type='out' (지출): 차변 비용계정, 대변 현금
    - type='in' (수입): 차변 현금, 대변 수익계정

    Returns:
        journal_entry.id

    Raises:
        ValueError: 미확정, 미매핑, 이미 분개 존재
    """
    cur = conn.cursor()

    cur.execute(
        """
        SELECT t.id, t.entity_id, t.date, t.amount, t.type, t.description,
               t.counterparty, t.standard_account_id, t.is_confirmed, t.source_type
        FROM transactions t
        WHERE t.id = %s
          AND (t.is_cancel IS NOT TRUE)
        """,
        [transaction_id],
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise ValueError(f"Transaction {transaction_id} not found")

    (tx_id, entity_id, tx_date, amount, tx_type, desc, counterparty,
     std_account_id, is_confirmed, source_type) = row

    if not is_confirmed:
        cur.close()
        raise ValueError(f"Transaction {transaction_id} is not confirmed")

    if not std_account_id:
        cur.close()
        raise ValueError(f"Transaction {transaction_id} has no standard_account_id")

    # 이미 분개가 있는지 확인
    cur.execute(
        "SELECT id FROM journal_entries WHERE transaction_id = %s",
        [transaction_id],
    )
    if cur.fetchone():
        cur.close()
        raise ValueError(f"Journal entry already exists for transaction {transaction_id}")

    cash_account_id = _get_cash_account_id(cur)
    amount = _quantize(amount)
    je_desc = f"{counterparty or ''} - {desc}".strip(" -")

    # P3-1: 발생주의 분개 분기.
    # 1) 카드 사용 (out)        : (차) 비용/std        / (대) 미지급비용 26200
    # 2) 카드 환불/취소 (in)    : (차) 미지급비용 26200 / (대) 비용/std (역분개)
    # 3) 은행→카드사 결제 (out): (차) 미지급비용 26200 / (대) 현금
    # 4) 그 외                  : 기존 (차)std/(대)현금 또는 (차)현금/(대)std
    is_card_source = source_type in CARD_SOURCE_TYPES
    is_bank_card_payment = (
        not is_card_source
        and tx_type == "out"
        and _is_card_payment(counterparty)
    )

    if is_card_source:
        ap_id = _get_accounts_payable_id(cur)
        if tx_type == "out":
            lines = [
                {"standard_account_id": std_account_id, "debit_amount": amount, "credit_amount": Decimal("0")},
                {"standard_account_id": ap_id,         "debit_amount": Decimal("0"), "credit_amount": amount},
            ]
        else:  # in: 카드 환불 = 미지급비용 감소 + 비용 reverse
            lines = [
                {"standard_account_id": ap_id,         "debit_amount": amount, "credit_amount": Decimal("0")},
                {"standard_account_id": std_account_id, "debit_amount": Decimal("0"), "credit_amount": amount},
            ]
    elif is_bank_card_payment:
        # 카드대금 출금: (차) 미지급비용 / (대) 현금
        ap_id = _get_accounts_payable_id(cur)
        lines = [
            {"standard_account_id": ap_id,           "debit_amount": amount, "credit_amount": Decimal("0")},
            {"standard_account_id": cash_account_id, "debit_amount": Decimal("0"), "credit_amount": amount},
        ]
    elif tx_type == "out":
        lines = [
            {"standard_account_id": std_account_id, "debit_amount": amount, "credit_amount": Decimal("0")},
            {"standard_account_id": cash_account_id, "debit_amount": Decimal("0"), "credit_amount": amount},
        ]
    else:  # 'in'
        lines = [
            {"standard_account_id": cash_account_id, "debit_amount": amount, "credit_amount": Decimal("0")},
            {"standard_account_id": std_account_id, "debit_amount": Decimal("0"), "credit_amount": amount},
        ]

    cur.close()

    return create_journal_entry(
        conn=conn,
        entity_id=entity_id,
        lines=lines,
        entry_date=tx_date,
        description=je_desc,
        transaction_id=transaction_id,
    )


def bulk_create_journals(
    conn: PgConnection,
    entity_id: int,
    transaction_ids: list[int],
) -> dict:
    """벌크 분개 생성. 이미 분개가 있거나 미매핑인 거래는 건너뜀.

    Returns:
        {"created": [id, ...], "skipped": [id, ...], "errors": [{"id": id, "reason": str}, ...]}
    """
    created = []
    skipped = []
    errors = []

    for tx_id in transaction_ids:
        try:
            je_id = create_journal_from_transaction(conn, tx_id)
            created.append({"transaction_id": tx_id, "journal_entry_id": je_id})
        except ValueError as e:
            reason = str(e)
            if "already exists" in reason or "not confirmed" in reason or "no standard_account_id" in reason:
                skipped.append({"transaction_id": tx_id, "reason": reason})
            else:
                errors.append({"transaction_id": tx_id, "reason": reason})

    return {"created": created, "skipped": skipped, "errors": errors}


def validate_trial_balance(
    conn: PgConnection,
    entity_id: int,
    as_of_date: date | None = None,
) -> dict:
    """시산표 균형 검증.

    Returns:
        {"total_debit": Decimal, "total_credit": Decimal, "is_balanced": bool, "difference": Decimal}
    """
    cur = conn.cursor()

    date_clause = "AND je.entry_date <= %s" if as_of_date else ""
    params = [entity_id]
    if as_of_date:
        params.append(as_of_date)

    cur.execute(
        f"""
        SELECT
            COALESCE(SUM(jel.debit_amount), 0) AS total_debit,
            COALESCE(SUM(jel.credit_amount), 0) AS total_credit
        FROM journal_entry_lines jel
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE je.entity_id = %s AND je.status = 'posted'
          {date_clause}
        """,
        params,
    )
    row = cur.fetchone()
    cur.close()

    total_debit = Decimal(str(row[0]))
    total_credit = Decimal(str(row[1]))
    difference = total_debit - total_credit

    return {
        "total_debit": float(total_debit),
        "total_credit": float(total_credit),
        "is_balanced": difference == 0,
        "difference": float(difference),
    }


def get_account_balance(
    conn: PgConnection,
    entity_id: int,
    standard_account_id: int,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """계정별 잔액 조회. normal_side에 따라 잔액 부호 결정."""
    cur = conn.cursor()

    date_clauses = []
    params: list = [entity_id, standard_account_id]

    if from_date:
        date_clauses.append("AND je.entry_date >= %s")
        params.append(from_date)
    if to_date:
        date_clauses.append("AND je.entry_date <= %s")
        params.append(to_date)

    date_sql = " ".join(date_clauses)

    cur.execute(
        f"""
        SELECT
            sa.code, sa.name, sa.category, sa.normal_side,
            COALESCE(SUM(jel.debit_amount), 0) AS debit_total,
            COALESCE(SUM(jel.credit_amount), 0) AS credit_total
        FROM standard_accounts sa
        LEFT JOIN journal_entry_lines jel ON jel.standard_account_id = sa.id
        LEFT JOIN journal_entries je ON jel.journal_entry_id = je.id
            AND je.entity_id = %s AND je.status = 'posted' {date_sql}
        WHERE sa.id = %s
        GROUP BY sa.id, sa.code, sa.name, sa.category, sa.normal_side
        """,
        params,
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return {"account_id": standard_account_id, "balance": 0.0}

    code, name, category, normal_side, debit_total, credit_total = row
    debit_total = Decimal(str(debit_total))
    credit_total = Decimal(str(credit_total))

    if normal_side == "debit":
        balance = debit_total - credit_total
    else:
        balance = credit_total - debit_total

    return {
        "account_id": standard_account_id,
        "code": code,
        "name": name,
        "category": category,
        "normal_side": normal_side,
        "debit_total": float(debit_total),
        "credit_total": float(credit_total),
        "balance": float(balance),
    }


def get_all_account_balances(
    conn: PgConnection,
    entity_id: int,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict]:
    """전체 계정 잔액 조회 (활동이 있는 계정만)."""
    cur = conn.cursor()

    date_clauses = []
    params: list = [entity_id]

    if from_date:
        date_clauses.append("AND je.entry_date >= %s")
        params.append(from_date)
    if to_date:
        date_clauses.append("AND je.entry_date <= %s")
        params.append(to_date)

    date_sql = " ".join(date_clauses)

    cur.execute(
        f"""
        SELECT
            sa.id, sa.code, sa.name, sa.category, sa.subcategory, sa.normal_side,
            COALESCE(SUM(jel.debit_amount), 0) AS debit_total,
            COALESCE(SUM(jel.credit_amount), 0) AS credit_total
        FROM standard_accounts sa
        JOIN journal_entry_lines jel ON jel.standard_account_id = sa.id
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE je.entity_id = %s AND je.status = 'posted'
          {date_sql}
        GROUP BY sa.id, sa.code, sa.name, sa.category, sa.subcategory, sa.normal_side
        HAVING SUM(jel.debit_amount) != 0 OR SUM(jel.credit_amount) != 0
        ORDER BY sa.sort_order
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    result = []
    for row in rows:
        account_id, code, name, category, subcategory, normal_side, debit_total, credit_total = row
        debit_total = Decimal(str(debit_total))
        credit_total = Decimal(str(credit_total))

        if normal_side == "debit":
            balance = debit_total - credit_total
        else:
            balance = credit_total - debit_total

        result.append({
            "account_id": account_id,
            "code": code,
            "name": name,
            "category": category,
            "subcategory": subcategory,
            "normal_side": normal_side,
            "debit_total": float(debit_total),
            "credit_total": float(credit_total),
            "balance": float(balance),
        })

    return result

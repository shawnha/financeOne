"""재무제표 생성 헬퍼 — 예외 클래스 및 공용 유틸리티 함수."""


class StatementImbalanceError(Exception):
    """재무상태표 항등식 불균형."""
    pass


class CashFlowLoopError(Exception):
    """현금흐름 루프 검증 실패."""
    pass


# --- 내부 헬퍼 ---

def _get_or_create_statement(
    cur,
    entity_id: int,
    fiscal_year: int,
    start_month: int,
    end_month: int,
) -> int:
    """financial_statements 헤더 조회 또는 생성. 반환: statement_id."""
    cur.execute(
        """
        SELECT id FROM financial_statements
        WHERE entity_id = %s AND fiscal_year = %s
          AND start_month = %s AND end_month = %s
          AND is_consolidated = FALSE
        """,
        [entity_id, fiscal_year, start_month, end_month],
    )
    row = cur.fetchone()
    if row:
        stmt_id = row[0]
        # 기존 라인 삭제 (재생성)
        cur.execute(
            "DELETE FROM financial_statement_line_items WHERE statement_id = %s",
            [stmt_id],
        )
        cur.execute(
            "UPDATE financial_statements SET status = 'draft', updated_at = NOW() WHERE id = %s",
            [stmt_id],
        )
        return stmt_id

    cur.execute(
        """
        INSERT INTO financial_statements
            (entity_id, fiscal_year, start_month, end_month, status)
        VALUES (%s, %s, %s, %s, 'draft')
        RETURNING id
        """,
        [entity_id, fiscal_year, start_month, end_month],
    )
    return cur.fetchone()[0]


def _insert_line_item(cur, stmt_id: int, item: dict):
    """financial_statement_line_items에 한 행 삽입."""
    cur.execute(
        """
        INSERT INTO financial_statement_line_items
            (statement_id, statement_type, account_code, line_key, label,
             sort_order, is_section_header, auto_amount, auto_debit, auto_credit)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            stmt_id,
            item["statement_type"],
            item.get("account_code"),
            item["line_key"],
            item["label"],
            item["sort_order"],
            item.get("is_section_header", False),
            item.get("auto_amount", 0),
            item.get("auto_debit", 0),
            item.get("auto_credit", 0),
        ],
    )


def _section_header(stmt_type: str, key: str, label: str, order: int) -> dict:
    return {
        "statement_type": stmt_type,
        "line_key": key,
        "label": label,
        "sort_order": order,
        "is_section_header": True,
        "auto_amount": 0,
        "auto_debit": 0,
        "auto_credit": 0,
    }

"""재무제표 API"""

from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all
from backend.services.statement_generator import generate_all_statements, generate_consolidated_statements
from backend.services.statements.i18n import translate_label, load_name_en_map
from backend.services.export import export_statement_excel


class GenerateRequest(BaseModel):
    entity_id: int
    fiscal_year: int
    start_month: int = 1
    end_month: int = 12

    @classmethod
    def __get_validators__(cls):
        yield cls._validate

    @staticmethod
    def _validate(v):
        return v

    def model_post_init(self, __context) -> None:
        if not (1 <= self.start_month <= 12):
            raise ValueError("start_month must be 1-12")
        if not (1 <= self.end_month <= 12):
            raise ValueError("end_month must be 1-12")
        if self.start_month > self.end_month:
            raise ValueError("start_month must be <= end_month")


class LineItemUpdate(BaseModel):
    manual_amount: Optional[float] = None
    manual_debit: Optional[float] = None
    manual_credit: Optional[float] = None
    note: Optional[str] = None

router = APIRouter(prefix="/api/statements", tags=["statements"])


@router.get("")
def list_statements(
    entity_id: Optional[int] = None,
    fiscal_year: Optional[int] = None,
    is_consolidated: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []

    if entity_id is not None:
        where.append("fs.entity_id = %s")
        params.append(entity_id)
    if fiscal_year is not None:
        where.append("fs.fiscal_year = %s")
        params.append(fiscal_year)
    if is_consolidated is not None:
        where.append("fs.is_consolidated = %s")
        params.append(is_consolidated)

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(f"SELECT COUNT(*) FROM financial_statements fs WHERE {where_clause}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT fs.id, fs.entity_id, fs.fiscal_year, fs.ki_num,
               fs.start_month, fs.end_month,
               fs.is_consolidated, fs.status, fs.auditor_name, fs.notes,
               e.name AS entity_name
        FROM financial_statements fs
        LEFT JOIN entities e ON fs.entity_id = e.id
        WHERE {where_clause}
        ORDER BY fs.fiscal_year DESC, fs.ki_num DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    rows = fetch_all(cur)
    cur.close()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    }


@router.get("/{stmt_id}")
def get_statement(
    stmt_id: int,
    lang: str = Query("ko", pattern="^(ko|en)$"),
    conn: PgConnection = Depends(get_db),
):
    """재무제표 상세. lang=en이면 라벨을 영문으로 번역 (name_en 활용)."""
    cur = conn.cursor()

    cur.execute(
        """
        SELECT fs.*, e.name AS entity_name, e.currency AS entity_currency
        FROM financial_statements fs
        LEFT JOIN entities e ON fs.entity_id = e.id
        WHERE fs.id = %s
        """,
        [stmt_id],
    )
    header_cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Statement not found")
    header = dict(zip(header_cols, row))

    cur.execute(
        """
        SELECT li.id, li.statement_id, li.statement_type, li.account_code,
               li.line_key, li.label, li.sort_order, li.is_section_header,
               li.auto_amount, li.auto_debit, li.auto_credit,
               li.manual_amount, li.manual_debit, li.manual_credit, li.note
        FROM financial_statement_line_items li
        WHERE li.statement_id = %s
        ORDER BY li.statement_type, li.sort_order
        """,
        [stmt_id],
    )
    line_items = fetch_all(cur)

    if lang == "en":
        name_en_map = load_name_en_map(cur)
        for item in line_items:
            item["label_ko"] = item["label"]
            item["label"] = translate_label(item["label"], item.get("account_code"), name_en_map)

    cur.close()

    header["line_items"] = line_items
    header["lang"] = lang
    # frontend 가 currency 표시할 때 우선순위: base_currency (consolidated) > entity_currency
    if not header.get("base_currency") or header.get("base_currency") == "KRW":
        if not header.get("is_consolidated") and header.get("entity_currency"):
            header["base_currency"] = header["entity_currency"]
    return header


@router.post("/generate")
def generate_statements(
    body: GenerateRequest,
    conn: PgConnection = Depends(get_db),
):
    """5종 재무제표 일괄 생성. status='finalized' 면 거부."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, status FROM financial_statements
           WHERE entity_id = %s AND fiscal_year = %s
             AND start_month = %s AND end_month = %s
             AND is_consolidated = false""",
        [body.entity_id, body.fiscal_year, body.start_month, body.end_month],
    )
    existing = cur.fetchone()
    cur.close()
    if existing and existing[1] == "finalized":
        raise HTTPException(
            409,
            f"Statement {existing[0]} 은 finalized 상태 — 자동 재생성 불가. 먼저 status 를 'draft' 로 변경하세요.",
        )

    try:
        result = generate_all_statements(
            conn=conn,
            entity_id=body.entity_id,
            fiscal_year=body.fiscal_year,
            start_month=body.start_month,
            end_month=body.end_month,
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


@router.delete("/{stmt_id}")
def delete_statement(
    stmt_id: int,
    force: bool = Query(False, description="finalized 도 강제 삭제"),
    conn: PgConnection = Depends(get_db),
):
    """Statement 1건 삭제. line_items CASCADE."""
    cur = conn.cursor()
    cur.execute("SELECT status FROM financial_statements WHERE id = %s", [stmt_id])
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Statement not found")
    status = row[0]
    if status == "finalized" and not force:
        cur.close()
        raise HTTPException(
            409,
            f"Statement {stmt_id} 는 finalized — 강제 삭제하려면 ?force=true 추가",
        )
    try:
        cur.execute(
            "DELETE FROM financial_statement_line_items WHERE statement_id = %s",
            [stmt_id],
        )
        line_count = cur.rowcount
        cur.execute("DELETE FROM financial_statements WHERE id = %s", [stmt_id])
        conn.commit()
        cur.close()
        return {"deleted": True, "statement_id": stmt_id, "line_items_deleted": line_count}
    except Exception:
        conn.rollback()
        raise


class StatementStatusUpdate(BaseModel):
    status: str  # 'draft' | 'finalized'


@router.patch("/{stmt_id}/status")
def update_statement_status(
    stmt_id: int,
    body: StatementStatusUpdate,
    conn: PgConnection = Depends(get_db),
):
    """Statement 상태 변경 (draft / finalized)."""
    if body.status not in ("draft", "finalized"):
        raise HTTPException(400, "status must be 'draft' or 'finalized'")
    cur = conn.cursor()
    cur.execute(
        "UPDATE financial_statements SET status = %s, updated_at = NOW() WHERE id = %s RETURNING id",
        [body.status, stmt_id],
    )
    row = cur.fetchone()
    if not row:
        conn.rollback()
        cur.close()
        raise HTTPException(404, "Statement not found")
    conn.commit()
    cur.close()
    return {"id": stmt_id, "status": body.status}


@router.patch("/lines/{line_id}")
def update_line_item(
    line_id: int,
    body: LineItemUpdate,
    conn: PgConnection = Depends(get_db),
):
    """line_item 의 manual_amount/manual_debit/manual_credit/note 수정.

    finalized statement 는 거부. NULL 입력 시 manual 값 초기화 (auto 값 사용).
    """
    cur = conn.cursor()

    cur.execute(
        """SELECT li.id, fs.status, fs.id as stmt_id
           FROM financial_statement_line_items li
           JOIN financial_statements fs ON fs.id = li.statement_id
           WHERE li.id = %s""",
        [line_id],
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Line item not found")
    if row[1] == "finalized":
        cur.close()
        raise HTTPException(409, f"Statement {row[2]} 는 finalized — 수정 불가")

    fields = []
    params = []
    if body.manual_amount is not None:
        fields.append("manual_amount = %s")
        params.append(body.manual_amount)
    elif "manual_amount" in body.model_fields_set:
        fields.append("manual_amount = NULL")
    if body.manual_debit is not None:
        fields.append("manual_debit = %s")
        params.append(body.manual_debit)
    elif "manual_debit" in body.model_fields_set:
        fields.append("manual_debit = NULL")
    if body.manual_credit is not None:
        fields.append("manual_credit = %s")
        params.append(body.manual_credit)
    elif "manual_credit" in body.model_fields_set:
        fields.append("manual_credit = NULL")
    if body.note is not None:
        fields.append("note = %s")
        params.append(body.note)
    elif "note" in body.model_fields_set:
        fields.append("note = NULL")

    if not fields:
        cur.close()
        raise HTTPException(400, "No fields to update")

    params.append(line_id)
    try:
        cur.execute(
            f"UPDATE financial_statement_line_items SET {', '.join(fields)} WHERE id = %s "
            f"RETURNING id, manual_amount, manual_debit, manual_credit, note, auto_amount, auto_debit, auto_credit",
            params,
        )
        result_row = cur.fetchone()
        conn.commit()
        cur.close()
        return {
            "id": result_row[0],
            "manual_amount": float(result_row[1]) if result_row[1] is not None else None,
            "manual_debit": float(result_row[2]) if result_row[2] is not None else None,
            "manual_credit": float(result_row[3]) if result_row[3] is not None else None,
            "note": result_row[4],
            "auto_amount": float(result_row[5]),
            "auto_debit": float(result_row[6]),
            "auto_credit": float(result_row[7]),
        }
    except Exception:
        conn.rollback()
        raise


@router.post("/lines/{line_id}/reset")
def reset_line_item(
    line_id: int,
    conn: PgConnection = Depends(get_db),
):
    """manual_* 모두 NULL → auto 값 사용으로 복원."""
    cur = conn.cursor()
    cur.execute(
        """SELECT li.id, fs.status FROM financial_statement_line_items li
           JOIN financial_statements fs ON fs.id = li.statement_id
           WHERE li.id = %s""",
        [line_id],
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Line item not found")
    if row[1] == "finalized":
        cur.close()
        raise HTTPException(409, "finalized statement — 수정 불가")

    try:
        cur.execute(
            """UPDATE financial_statement_line_items
               SET manual_amount = NULL, manual_debit = NULL, manual_credit = NULL, note = NULL
               WHERE id = %s""",
            [line_id],
        )
        conn.commit()
        cur.close()
        return {"id": line_id, "reset": True}
    except Exception:
        conn.rollback()
        raise


class ConsolidatedGenerateRequest(BaseModel):
    fiscal_year: int
    start_month: int = 1
    end_month: int = 12
    base_currency: str = "USD"

    def model_post_init(self, __context) -> None:
        if not (1 <= self.start_month <= 12):
            raise ValueError("start_month must be 1-12")
        if not (1 <= self.end_month <= 12):
            raise ValueError("end_month must be 1-12")
        if self.start_month > self.end_month:
            raise ValueError("start_month must be <= end_month")
        if self.base_currency.upper() not in ("USD", "KRW"):
            raise ValueError("base_currency must be USD or KRW")


@router.post("/generate-consolidated")
def generate_consolidated(
    body: ConsolidatedGenerateRequest,
    conn: PgConnection = Depends(get_db),
):
    """연결재무제표 생성 (USD: US GAAP / KRW: K-GAAP)."""
    try:
        result = generate_consolidated_statements(
            conn=conn,
            fiscal_year=body.fiscal_year,
            start_month=body.start_month,
            end_month=body.end_month,
            base_currency=body.base_currency.upper(),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


@router.get("/{stmt_id}/validate")
def validate_statement(stmt_id: int, conn: PgConnection = Depends(get_db)):
    """저장된 재무제표의 항등식 검증."""
    cur = conn.cursor()

    # 재무상태표 검증: 자산 = 부채 + 자본
    cur.execute(
        """
        SELECT line_key, auto_amount, manual_amount
        FROM financial_statement_line_items
        WHERE statement_id = %s AND statement_type = 'balance_sheet'
          AND line_key IN ('total_assets', 'total_liabilities', 'total_equity')
        """,
        [stmt_id],
    )
    bs_totals = {}
    for row in cur.fetchall():
        key = row[0]
        amount = row[2] if row[2] is not None else row[1]
        bs_totals[key] = float(amount or 0)

    bs_balanced = True
    bs_diff = 0.0
    if bs_totals:
        assets = bs_totals.get("total_assets", 0)
        liab_eq = bs_totals.get("total_liabilities", 0) + bs_totals.get("total_equity", 0)
        bs_diff = assets - liab_eq
        bs_balanced = abs(bs_diff) < 0.01

    # 시산표 검증: 차변 합 == 대변 합
    cur.execute(
        """
        SELECT auto_debit, auto_credit, manual_debit, manual_credit
        FROM financial_statement_line_items
        WHERE statement_id = %s AND statement_type = 'trial_balance'
          AND line_key = 'tb_total'
        """,
        [stmt_id],
    )
    tb_row = cur.fetchone()
    tb_balanced = True
    tb_diff = 0.0
    if tb_row:
        tb_debit = float(tb_row[2] if tb_row[2] is not None else tb_row[0] or 0)
        tb_credit = float(tb_row[3] if tb_row[3] is not None else tb_row[1] or 0)
        tb_diff = tb_debit - tb_credit
        tb_balanced = abs(tb_diff) < 0.01

    cur.close()

    return {
        "balance_sheet": {"is_balanced": bs_balanced, "difference": bs_diff},
        "trial_balance": {"is_balanced": tb_balanced, "difference": tb_diff},
    }


@router.patch("/{stmt_id}/line-items/{item_id}")
def update_line_item(
    stmt_id: int,
    item_id: int,
    body: LineItemUpdate,
    conn: PgConnection = Depends(get_db),
):
    """수동 오버라이드 업데이트."""
    cur = conn.cursor()
    try:
        ALLOWED_FIELDS = {"manual_amount", "manual_debit", "manual_credit", "note"}
        data = body.model_dump(exclude_none=True)
        if not data:
            raise HTTPException(400, "No fields to update")

        sets = []
        params: list = []
        for key, val in data.items():
            if key not in ALLOWED_FIELDS:
                raise HTTPException(400, f"Invalid field: {key}")
            sets.append(f"{key} = %s")
            params.append(val)

        params.extend([item_id, stmt_id])
        cur.execute(
            f"""
            UPDATE financial_statement_line_items
            SET {', '.join(sets)}
            WHERE id = %s AND statement_id = %s
            RETURNING id
            """,
            params,
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Line item not found")
        conn.commit()
        cur.close()
        return {"id": row[0], "updated": True}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise


@router.get("/{stmt_id}/export")
def export_statement(
    stmt_id: int,
    format: str = Query("excel"),
    type: Optional[str] = Query(None),
    conn: PgConnection = Depends(get_db),
):
    """재무제표 Excel 다운로드."""
    try:
        data = export_statement_excel(conn, stmt_id, statement_type=type)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=statement_{stmt_id}.xlsx"},
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

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
        SELECT fs.*, e.name AS entity_name
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
    return header


@router.post("/generate")
def generate_statements(
    body: GenerateRequest,
    conn: PgConnection = Depends(get_db),
):
    """5종 재무제표 일괄 생성."""
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


class ConsolidatedGenerateRequest(BaseModel):
    fiscal_year: int
    start_month: int = 1
    end_month: int = 12

    def model_post_init(self, __context) -> None:
        if not (1 <= self.start_month <= 12):
            raise ValueError("start_month must be 1-12")
        if not (1 <= self.end_month <= 12):
            raise ValueError("end_month must be 1-12")
        if self.start_month > self.end_month:
            raise ValueError("start_month must be <= end_month")


@router.post("/generate-consolidated")
def generate_consolidated(
    body: ConsolidatedGenerateRequest,
    conn: PgConnection = Depends(get_db),
):
    """연결재무제표 생성 (US GAAP, USD)."""
    try:
        result = generate_consolidated_statements(
            conn=conn,
            fiscal_year=body.fiscal_year,
            start_month=body.start_month,
            end_month=body.end_month,
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

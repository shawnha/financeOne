"""재무제표 Excel/PDF Export"""

import io
from psycopg2.extensions import connection as PgConnection
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill


STATEMENT_LABELS = {
    "balance_sheet": "재무상태표",
    "income_statement": "손익계산서",
    "cash_flow": "현금흐름표",
    "trial_balance": "합계잔액시산표",
    "deficit_treatment": "결손금처리계산서",
}

thin_border = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
header_font = Font(name="맑은 고딕", bold=True, size=11, color="FFFFFF")
section_font = Font(name="맑은 고딕", bold=True, size=10)
normal_font = Font(name="맑은 고딕", size=10)
amount_font = Font(name="Consolas", size=10)


def export_statement_excel(
    conn: PgConnection,
    statement_id: int,
    statement_type: str | None = None,
) -> bytes:
    """재무제표를 Excel로 Export.

    Args:
        statement_type: None이면 전체, 지정하면 해당 유형만

    Returns:
        Excel 파일 바이트
    """
    cur = conn.cursor()

    # 헤더 정보
    cur.execute(
        """
        SELECT fs.fiscal_year, fs.start_month, fs.end_month,
               e.name AS entity_name
        FROM financial_statements fs
        LEFT JOIN entities e ON fs.entity_id = e.id
        WHERE fs.id = %s
        """,
        [statement_id],
    )
    header = cur.fetchone()
    if not header:
        cur.close()
        raise ValueError(f"Statement {statement_id} not found")

    fiscal_year, start_month, end_month, entity_name = header

    # 라인 아이템
    type_filter = "AND li.statement_type = %s" if statement_type else ""
    params = [statement_id]
    if statement_type:
        params.append(statement_type)

    cur.execute(
        f"""
        SELECT li.statement_type, li.account_code, li.label,
               li.is_section_header,
               COALESCE(li.manual_amount, li.auto_amount) AS amount,
               COALESCE(li.manual_debit, li.auto_debit) AS debit,
               COALESCE(li.manual_credit, li.auto_credit) AS credit
        FROM financial_statement_line_items li
        WHERE li.statement_id = %s {type_filter}
        ORDER BY li.statement_type, li.sort_order
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    # Group by statement type
    grouped: dict[str, list] = {}
    for row in rows:
        st = row[0]
        if st not in grouped:
            grouped[st] = []
        grouped[st].append(row)

    wb = Workbook()
    wb.remove(wb.active)  # Remove default sheet

    for st_type, items in grouped.items():
        label = STATEMENT_LABELS.get(st_type, st_type)
        ws = wb.create_sheet(title=label[:31])  # Excel sheet name limit

        # Title
        ws.merge_cells("A1:D1")
        ws["A1"] = f"{entity_name} — {label}"
        ws["A1"].font = Font(name="맑은 고딕", bold=True, size=14)
        ws["A2"] = f"{fiscal_year}년 {start_month}월~{end_month}월"
        ws["A2"].font = Font(name="맑은 고딕", size=10, color="888888")

        is_tb = st_type == "trial_balance"

        # Headers
        row_num = 4
        ws.cell(row=row_num, column=1, value="계정과목").font = header_font
        ws.cell(row=row_num, column=1).fill = header_fill
        ws.cell(row=row_num, column=1).border = thin_border

        if is_tb:
            ws.cell(row=row_num, column=2, value="차변").font = header_font
            ws.cell(row=row_num, column=2).fill = header_fill
            ws.cell(row=row_num, column=2).border = thin_border
            ws.cell(row=row_num, column=2).alignment = Alignment(horizontal="right")
            ws.cell(row=row_num, column=3, value="대변").font = header_font
            ws.cell(row=row_num, column=3).fill = header_fill
            ws.cell(row=row_num, column=3).border = thin_border
            ws.cell(row=row_num, column=3).alignment = Alignment(horizontal="right")
        else:
            ws.cell(row=row_num, column=2, value="금액").font = header_font
            ws.cell(row=row_num, column=2).fill = header_fill
            ws.cell(row=row_num, column=2).border = thin_border
            ws.cell(row=row_num, column=2).alignment = Alignment(horizontal="right")

        # Data rows
        for item in items:
            row_num += 1
            _, account_code, item_label, is_header, amount, debit, credit = item

            cell_label = ws.cell(row=row_num, column=1, value=item_label)
            cell_label.font = section_font if is_header else normal_font
            cell_label.border = thin_border

            if is_tb:
                cell_d = ws.cell(row=row_num, column=2, value=float(debit) if debit else None)
                cell_d.font = amount_font
                cell_d.number_format = '#,##0'
                cell_d.alignment = Alignment(horizontal="right")
                cell_d.border = thin_border

                cell_c = ws.cell(row=row_num, column=3, value=float(credit) if credit else None)
                cell_c.font = amount_font
                cell_c.number_format = '#,##0'
                cell_c.alignment = Alignment(horizontal="right")
                cell_c.border = thin_border
            else:
                cell_a = ws.cell(row=row_num, column=2, value=float(amount) if amount else None)
                cell_a.font = amount_font
                cell_a.number_format = '#,##0'
                cell_a.alignment = Alignment(horizontal="right")
                cell_a.border = thin_border

        # Column widths
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 20
        if is_tb:
            ws.column_dimensions["C"].width = 20

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

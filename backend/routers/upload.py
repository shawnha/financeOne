"""파일 업로드 API -- multi-format (xls, xlsx, csv) with auto-detection."""

from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Depends
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.parsers import detect_parser

router = APIRouter(prefix="/api/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}


@router.post("")
async def upload_transactions(
    file: UploadFile = File(...),
    entity_id: int = Query(..., description="법인 ID (필수)"),
    conn: PgConnection = Depends(get_db),
):
    # Validate extension
    filename = file.filename or "unknown"
    ext = ""
    for allowed in ALLOWED_EXTENSIONS:
        if filename.lower().endswith(allowed):
            ext = allowed
            break
    if not ext:
        raise HTTPException(400, f"지원하지 않는 파일 형식입니다. 허용: {', '.join(ALLOWED_EXTENSIONS)}")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "빈 파일입니다.")

    # Auto-detect parser
    parser = detect_parser(file_bytes, filename)
    if parser is None:
        raise HTTPException(400, "파일 형식을 인식할 수 없습니다. 지원: 롯데카드, 우리카드, 우리은행, CSV")

    # Parse transactions
    parsed = parser.parse(file_bytes, filename)
    if not parsed:
        raise HTTPException(400, "파싱된 거래가 없습니다. 파일 내용을 확인해주세요.")

    source_type = parsed[0].source_type if parsed else "unknown"

    cur = conn.cursor()
    try:
        # Insert uploaded_files record
        cur.execute(
            """
            INSERT INTO uploaded_files (entity_id, filename, source_type, file_path, row_count, status)
            VALUES (%s, %s, %s, %s, %s, 'processing')
            RETURNING id
            """,
            [entity_id, filename, source_type, f"uploads/{filename}", len(parsed)],
        )
        file_id = cur.fetchone()[0]

        inserted_count = 0
        duplicate_count = 0

        for tx in parsed:
            # Duplicate detection: check existing (entity_id, date, amount, counterparty)
            cur.execute(
                """
                SELECT id FROM transactions
                WHERE entity_id = %s AND date = %s AND amount = %s AND counterparty = %s
                LIMIT 1
                """,
                [entity_id, tx.date, tx.amount, tx.counterparty],
            )
            existing = cur.fetchone()
            is_dup = existing is not None

            # Check card dedup: if is_check_card, also mark as duplicate
            if tx.is_check_card:
                is_dup = True

            if is_dup:
                duplicate_count += 1

            # Resolve member_id from member_name if provided
            member_id = None
            if tx.member_name:
                cur.execute(
                    "SELECT id FROM members WHERE entity_id = %s AND name = %s LIMIT 1",
                    [entity_id, tx.member_name],
                )
                member_row = cur.fetchone()
                if member_row:
                    member_id = member_row[0]

            cur.execute(
                """
                INSERT INTO transactions
                    (entity_id, file_id, date, amount, currency, type,
                     description, counterparty, source_type, member_id,
                     is_duplicate, duplicate_of_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    entity_id, file_id, tx.date, tx.amount, tx.currency, tx.type,
                    tx.description, tx.counterparty, tx.source_type, member_id,
                    is_dup, existing[0] if existing else None,
                ],
            )
            inserted_count += 1

        # Update uploaded_files with final counts
        cur.execute(
            """
            UPDATE uploaded_files
            SET status = 'completed', row_count = %s
            WHERE id = %s
            """,
            [inserted_count, file_id],
        )

        conn.commit()
        cur.close()

        return {
            "file_id": file_id,
            "filename": filename,
            "source_type": source_type,
            "uploaded": inserted_count,
            "duplicates": duplicate_count,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        # Mark upload as failed if file record was created
        try:
            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE uploaded_files SET status = 'failed' WHERE id = %s",
                [file_id],
            )
            conn.commit()
            cur2.close()
        except Exception:
            pass
        raise HTTPException(500, f"업로드 처리 중 오류: {e}")


@router.get("/history")
def upload_history(
    entity_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn: PgConnection = Depends(get_db),
):
    """List uploaded files with metadata."""
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []
    if entity_id is not None:
        where.append("uf.entity_id = %s")
        params.append(entity_id)

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(
        f"SELECT COUNT(*) FROM uploaded_files uf WHERE {where_clause}",
        params,
    )
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT uf.id, uf.entity_id, uf.filename, uf.source_type,
               uf.row_count, uf.status, uf.uploaded_at,
               e.name AS entity_name,
               (SELECT COUNT(*) FROM transactions t WHERE t.file_id = uf.id AND t.is_duplicate = true) AS duplicate_count
        FROM uploaded_files uf
        LEFT JOIN entities e ON uf.entity_id = e.id
        WHERE {where_clause}
        ORDER BY uf.uploaded_at DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    }

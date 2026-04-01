"""파일 업로드 API -- multi-format (xls, xlsx, csv) with auto-detection."""

from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all
from backend.services.parsers import detect_parser
from backend.services.parsers.woori_bank import WooriBankParser
from backend.services.dedup_service import build_file_key_counts, is_file_duplicate
from backend.services.mapping_service import auto_map_transaction

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
        raise HTTPException(400, f"파일 형식을 인식할 수 없습니다. 지원: 롯데카드, 우리카드, 우리은행, CSV (파일명: {filename}, 크기: {len(file_bytes)}bytes)")

    # Parse transactions
    try:
        parsed = parser.parse(file_bytes, filename)
    except Exception as parse_err:
        raise HTTPException(400, f"파싱 중 오류: {type(parser).__name__} - {parse_err}")
    if not parsed:
        raise HTTPException(400, f"파싱된 거래가 없습니다. (파서: {type(parser).__name__}, 파일: {filename}, 크기: {len(file_bytes)}bytes)")

    source_type = parsed[0].source_type if parsed else "unknown"

    # 우리은행: 잔액 파싱
    bank_closing_balance = None
    bank_opening_balance = None
    bank_balance_date = None
    if isinstance(parser, WooriBankParser):
        result = parser.parse_with_balance(file_bytes, filename)
        bank_closing_balance = result.closing_balance
        bank_opening_balance = result.opening_balance
        bank_balance_date = result.balance_date

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
        cancel_count = 0
        auto_mapped_count = 0

        cumulative = build_file_key_counts(parsed)

        for i, tx in enumerate(parsed):
            # 중복 감지: O(1) set 기반
            cur.execute(
                """
                SELECT COUNT(*) FROM transactions
                WHERE entity_id = %s AND date = %s AND amount = %s
                  AND counterparty = %s AND description = %s AND source_type = %s
                """,
                [entity_id, tx.date, tx.amount, tx.counterparty, tx.description, tx.source_type],
            )
            db_count = cur.fetchone()[0]

            if is_file_duplicate(i, cumulative, db_count):
                duplicate_count += 1
                continue  # DB에 이미 충분히 있으면 건너뜀

            # 체크카드 중복: 은행 거래가 DB에 존재할 때만
            is_dup = False
            if tx.is_check_card:
                cur.execute(
                    """
                    SELECT id FROM transactions
                    WHERE entity_id = %s AND date = %s AND amount = %s
                      AND source_type = 'woori_bank'
                      AND description LIKE '체크우리%%'
                    LIMIT 1
                    """,
                    [entity_id, tx.date, tx.amount],
                )
                is_dup = cur.fetchone() is not None

            if is_dup:
                duplicate_count += 1
                continue

            # 취소 건 카운트
            if tx.is_cancel:
                cancel_count += 1

            # Resolve member_id
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
                     is_duplicate, duplicate_of_id, is_cancel, parsed_member_name, card_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, NULL, %s, %s, %s)
                """,
                [
                    entity_id, file_id, tx.date, tx.amount, tx.currency, tx.type,
                    tx.description, tx.counterparty, tx.source_type, member_id,
                    tx.is_cancel, tx.member_name, tx.card_number,
                ],
            )
            inserted_count += 1

            # 자동 매핑: 5단계 캐스케이드 (exact → similar → keyword → AI → manual)
            mapping = auto_map_transaction(cur, entity_id=entity_id, counterparty=tx.counterparty, description=tx.description)
            if mapping:
                cur.execute(
                    """
                    UPDATE transactions
                    SET internal_account_id = %s, standard_account_id = %s,
                        mapping_source = %s, mapping_confidence = %s
                    WHERE id = (
                        SELECT id FROM transactions
                        WHERE entity_id = %s AND file_id = %s AND date = %s
                          AND amount = %s AND counterparty = %s AND description = %s
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    [
                        mapping["internal_account_id"],
                        mapping["standard_account_id"],
                        mapping.get("match_type", "rule"),
                        mapping["confidence"],
                        entity_id, file_id, tx.date, tx.amount, tx.counterparty, tx.description,
                    ],
                )
                auto_mapped_count += 1

        # Update uploaded_files
        cur.execute(
            "UPDATE uploaded_files SET status = 'completed', row_count = %s WHERE id = %s",
            [inserted_count, file_id],
        )

        # 우리은행 잔액 → balance_snapshots 자동 저장 (기말 + 기초)
        verification = None
        if bank_closing_balance is not None and bank_balance_date is not None:
            cur.execute(
                """
                INSERT INTO balance_snapshots
                    (entity_id, date, account_name, account_type, balance, currency, source)
                VALUES (%s, %s, '우리은행 법인통장', 'bank', %s, 'KRW', 'excel_parsed')
                ON CONFLICT (entity_id, date, account_name)
                DO UPDATE SET balance = EXCLUDED.balance, source = 'excel_parsed'
                """,
                [entity_id, bank_balance_date, bank_closing_balance],
            )

            # 기초잔고도 저장 (해당 월 1일 기준)
            if bank_opening_balance is not None and parsed:
                earliest_date = min(tx.date for tx in parsed)
                opening_date = earliest_date.replace(day=1)
                cur.execute(
                    """
                    INSERT INTO balance_snapshots
                        (entity_id, date, account_name, account_type, balance, currency, source, note)
                    VALUES (%s, %s, '우리은행 법인통장', 'bank', %s, 'KRW', 'excel_parsed', 'opening_balance')
                    ON CONFLICT (entity_id, date, account_name)
                    DO UPDATE SET balance = EXCLUDED.balance, source = 'excel_parsed', note = 'opening_balance'
                    """,
                    [entity_id, opening_date, bank_opening_balance],
                )

            # 파싱 검증: 파싱된 합계 vs 잔액 비교
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0)
                FROM transactions
                WHERE entity_id = %s AND source_type = 'woori_bank' AND file_id = %s
                """,
                [entity_id, file_id],
            )
            parsed_net = float(cur.fetchone()[0])
            verification = {
                "bank_closing_balance": bank_closing_balance,
                "balance_date": str(bank_balance_date),
                "parsed_net_flow": parsed_net,
                "balance_saved": True,
            }

        conn.commit()
        cur.close()

        return {
            "file_id": file_id,
            "filename": filename,
            "file": filename,
            "source_type": source_type,
            "uploaded": inserted_count,
            "duplicates": duplicate_count,
            "errors": [],
            "stats": {
                "total_parsed": len(parsed),
                "inserted": inserted_count,
                "duplicates_skipped": duplicate_count,
                "cancellations": cancel_count,
                "auto_mapped": auto_mapped_count,
            },
            "verification": verification,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
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


class ResetRequest(BaseModel):
    entity_id: int
    confirm: bool = False


@router.post("/reset")
def reset_transactions(
    body: ResetRequest,
    conn: PgConnection = Depends(get_db),
):
    """법인 거래 초기화 (관리자 전용). confirm=True 필수."""
    if not body.confirm:
        # 건수만 반환
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE entity_id = %s",
            [body.entity_id],
        )
        count = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM uploaded_files WHERE entity_id = %s",
            [body.entity_id],
        )
        file_count = cur.fetchone()[0]
        cur.close()
        return {
            "entity_id": body.entity_id,
            "transactions_count": count,
            "files_count": file_count,
            "confirmed": False,
            "message": f"{count}건 거래와 {file_count}개 업로드 이력이 삭제됩니다. confirm=true로 재요청하세요.",
        }

    cur = conn.cursor()
    try:
        # 분개 먼저 삭제 (FK)
        cur.execute(
            """
            DELETE FROM journal_entry_lines WHERE journal_entry_id IN (
                SELECT id FROM journal_entries WHERE entity_id = %s
            )
            """,
            [body.entity_id],
        )
        cur.execute("DELETE FROM journal_entries WHERE entity_id = %s", [body.entity_id])

        # 거래 삭제
        cur.execute("DELETE FROM transactions WHERE entity_id = %s RETURNING id", [body.entity_id])
        tx_deleted = cur.rowcount

        # 업로드 이력 삭제
        cur.execute("DELETE FROM uploaded_files WHERE entity_id = %s", [body.entity_id])
        files_deleted = cur.rowcount

        # 잔고 스냅샷 삭제 (excel_parsed 소스만)
        cur.execute(
            "DELETE FROM balance_snapshots WHERE entity_id = %s AND source = 'excel_parsed'",
            [body.entity_id],
        )

        conn.commit()
        cur.close()

        return {
            "entity_id": body.entity_id,
            "confirmed": True,
            "transactions_deleted": tx_deleted,
            "files_deleted": files_deleted,
            "message": "초기화 완료. Excel 파일을 다시 업로드하세요.",
        }
    except Exception:
        conn.rollback()
        raise


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
               e.name AS entity_name
        FROM uploaded_files uf
        LEFT JOIN entities e ON uf.entity_id = e.id
        WHERE {where_clause}
        ORDER BY uf.uploaded_at DESC
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


@router.delete("/file/{file_id}")
def delete_uploaded_file(
    file_id: int,
    conn: PgConnection = Depends(get_db),
):
    """업로드 파일과 연관 거래 삭제."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, entity_id, filename, row_count FROM uploaded_files WHERE id = %s", [file_id])
        file_row = cur.fetchone()
        if not file_row:
            raise HTTPException(404, "업로드 파일을 찾을 수 없습니다.")

        entity_id = file_row[1]

        # 분개 삭제 (FK: journal_entry_lines → journal_entries → transactions)
        cur.execute("""
            DELETE FROM journal_entry_lines WHERE journal_entry_id IN (
                SELECT je.id FROM journal_entries je
                JOIN transactions t ON je.transaction_id = t.id
                WHERE t.file_id = %s
            )
        """, [file_id])

        cur.execute("""
            DELETE FROM journal_entries WHERE transaction_id IN (
                SELECT id FROM transactions WHERE file_id = %s
            )
        """, [file_id])

        # 거래 삭제
        cur.execute("DELETE FROM transactions WHERE file_id = %s", [file_id])
        tx_deleted = cur.rowcount

        # 잔고 스냅샷 삭제 (해당 파일 업로드 시 생성된 것)
        cur.execute(
            "DELETE FROM balance_snapshots WHERE entity_id = %s AND source = 'excel_parsed'",
            [entity_id],
        )

        # 업로드 이력 삭제
        cur.execute("DELETE FROM uploaded_files WHERE id = %s", [file_id])

        conn.commit()
        cur.close()
        return {
            "id": file_id,
            "status": "deleted",
            "transactions_deleted": tx_deleted,
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"삭제 실패: {e}")


@router.post("/file/{file_id}/rematch")
def rematch_file_transactions(
    file_id: int,
    conn: PgConnection = Depends(get_db),
):
    """파일의 거래에 멤버/계정 매핑을 재적용."""
    cur = conn.cursor()
    try:
        # 파일 확인
        cur.execute("SELECT id, entity_id, source_type FROM uploaded_files WHERE id = %s", [file_id])
        file_row = cur.fetchone()
        if not file_row:
            raise HTTPException(404, "업로드 파일을 찾을 수 없습니다.")
        entity_id = file_row[1]

        # 1. 멤버 재매칭: parsed_member_name → members 테이블 조회
        cur.execute(
            """
            SELECT t.id, t.parsed_member_name
            FROM transactions t
            WHERE t.file_id = %s AND t.parsed_member_name IS NOT NULL
            """,
            [file_id],
        )
        tx_rows = cur.fetchall()

        member_matched = 0
        member_cache: dict[str, int | None] = {}
        for tx_id, parsed_name in tx_rows:
            if parsed_name not in member_cache:
                cur.execute(
                    "SELECT id FROM members WHERE entity_id = %s AND name = %s LIMIT 1",
                    [entity_id, parsed_name],
                )
                row = cur.fetchone()
                member_cache[parsed_name] = row[0] if row else None

            mid = member_cache[parsed_name]
            if mid is not None:
                cur.execute(
                    "UPDATE transactions SET member_id = %s WHERE id = %s AND (member_id IS NULL OR member_id != %s)",
                    [mid, tx_id, mid],
                )
                if cur.rowcount > 0:
                    member_matched += 1

        # 2. 계정 재매칭: mapping_service 사용
        cur.execute(
            """
            SELECT t.id, t.counterparty, t.description
            FROM transactions t
            WHERE t.file_id = %s AND t.internal_account_id IS NULL
              AND (t.counterparty IS NOT NULL OR t.description IS NOT NULL)
            """,
            [file_id],
        )
        unmapped_rows = cur.fetchall()

        account_matched = 0
        for tx_id, counterparty, description in unmapped_rows:
            mapping = auto_map_transaction(cur, entity_id=entity_id, counterparty=counterparty, description=description)
            if mapping:
                cur.execute(
                    """
                    UPDATE transactions
                    SET internal_account_id = %s, standard_account_id = %s,
                        mapping_source = %s, mapping_confidence = %s
                    WHERE id = %s
                    """,
                    [mapping["internal_account_id"], mapping["standard_account_id"],
                     mapping.get("match_type", "rule"), mapping["confidence"], tx_id],
                )
                account_matched += 1

        conn.commit()
        cur.close()

        total_tx = len(tx_rows) + len(unmapped_rows)
        return {
            "file_id": file_id,
            "total_transactions": total_tx,
            "member_matched": member_matched,
            "account_matched": account_matched,
            "member_unmatched": len([n for n in member_cache.values() if n is None]),
            "unmatched_names": [n for n, mid in member_cache.items() if mid is None],
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"재매칭 실패: {e}")

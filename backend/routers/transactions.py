"""거래내역 API"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import date
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all
from backend.services.bookkeeping_engine import create_journal_from_transaction
from backend.services.mapping_service import learn_mapping_rule, auto_map_transaction

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionUpdate(BaseModel):
    internal_account_id: Optional[int] = None
    standard_account_id: Optional[int] = None
    is_confirmed: Optional[bool] = None
    note: Optional[str] = None


class BulkConfirm(BaseModel):
    ids: list[int]


@router.get("")
def list_transactions(
    entity_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    source_type: Optional[str] = None,
    is_confirmed: Optional[bool] = None,
    search: Optional[str] = None,
    member_id: Optional[int] = None,
    standard_account_id: Optional[int] = None,
    internal_account_id: Optional[int] = None,
    tx_type: Optional[str] = None,
    mapping_source: Optional[str] = None,
    recently_mapped: Optional[bool] = None,
    slack_matched: Optional[bool] = None,
    unclassified: Optional[bool] = None,
    unconfirmed: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []

    if entity_id is not None:
        where.append("t.entity_id = %s")
        params.append(entity_id)
    if date_from is not None:
        where.append("t.date >= %s")
        params.append(date_from)
    if date_to is not None:
        where.append("t.date <= %s")
        params.append(date_to)
    if source_type is not None:
        where.append("t.source_type = %s")
        params.append(source_type)
    if is_confirmed is not None:
        where.append("t.is_confirmed = %s")
        params.append(is_confirmed)
    if member_id is not None:
        where.append("t.member_id = %s")
        params.append(member_id)
    if standard_account_id is not None:
        where.append("t.standard_account_id = %s")
        params.append(standard_account_id)
    if internal_account_id is not None:
        where.append("t.internal_account_id = %s")
        params.append(internal_account_id)
    if tx_type in ("in", "out"):
        where.append("t.type = %s")
        params.append(tx_type)
        where.append("t.is_cancel = false")
    if mapping_source:
        where.append("t.mapping_source = %s")
        params.append(mapping_source)
    if recently_mapped:
        where.append("t.internal_account_id IS NOT NULL AND t.updated_at >= NOW() - INTERVAL '24 hours'")
    if slack_matched:
        where.append("EXISTS (SELECT 1 FROM transaction_slack_match tsm WHERE tsm.transaction_id = t.id AND tsm.is_confirmed = true)")
    if unclassified:
        where.append("t.is_confirmed = false AND t.internal_account_id IS NULL")
    if unconfirmed:
        where.append("t.is_confirmed = false AND t.internal_account_id IS NOT NULL")
    need_join_for_search = False
    if search:
        # 숫자만이면 금액 검색 (±3%), 아니면 텍스트 검색 (내역/거래처/메모/내부계정명/날짜)
        clean = search.replace(",", "").strip()
        need_join_for_search = True
        try:
            amount_val = float(clean)
            lo = round(amount_val * 0.97, 2)
            hi = round(amount_val * 1.03, 2)
            where.append("(t.amount BETWEEN %s AND %s OR t.description ILIKE %s OR t.counterparty ILIKE %s OR t.note ILIKE %s OR ia.name ILIKE %s OR CAST(t.date AS TEXT) ILIKE %s)")
            q = f"%{search}%"
            params.extend([lo, hi, q, q, q, q, q])
        except ValueError:
            where.append("(t.description ILIKE %s OR t.counterparty ILIKE %s OR t.note ILIKE %s OR ia.name ILIKE %s OR CAST(t.date AS TEXT) ILIKE %s)")
            q = f"%{search}%"
            params.extend([q, q, q, q, q])

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    # Count
    count_from = "transactions t LEFT JOIN internal_accounts ia ON t.internal_account_id = ia.id" if need_join_for_search else "transactions t"
    cur.execute(f"SELECT COUNT(*) FROM {count_from} WHERE {where_clause}", params)
    total = cur.fetchone()[0]

    # Data with JOINs
    cur.execute(
        f"""
        SELECT t.id, t.entity_id, t.date, t.amount, t.currency, t.type,
               t.description, t.counterparty, t.source_type,
               t.mapping_confidence, t.mapping_source, t.is_confirmed,
               t.is_duplicate, t.note, t.member_id,
               t.internal_account_id, t.standard_account_id, t.is_cancel, t.card_number,
               m.name AS member_name,
               ia.code AS internal_account_code, ia.name AS internal_account_name,
               pia.name AS internal_account_parent_name,
               sa.code AS standard_account_code, sa.name AS standard_account_name,
               EXISTS(SELECT 1 FROM transaction_slack_match tsm WHERE tsm.transaction_id = t.id) AS has_slack_match
        FROM transactions t
        LEFT JOIN members m ON t.member_id = m.id
        LEFT JOIN internal_accounts ia ON t.internal_account_id = ia.id
        LEFT JOIN internal_accounts pia ON pia.id = ia.parent_id
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE {where_clause}
        ORDER BY t.date DESC, t.id DESC
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


@router.patch("/{tx_id}")
def update_transaction(
    tx_id: int,
    body: TransactionUpdate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        sets = []
        params: list = []
        data = body.model_dump(exclude_none=True)
        if not data:
            raise HTTPException(400, "No fields to update")

        for key, val in data.items():
            sets.append(f"{key} = %s")
            params.append(val)

        # 내부계정 직접 변경 시 mapping_source='manual'로 보호
        if body.internal_account_id is not None:
            if "mapping_source" not in data:
                sets.append("mapping_source = %s")
                params.append("manual")
            if "mapping_confidence" not in data:
                sets.append("mapping_confidence = %s")
                params.append(1.0)

        sets.append("updated_at = NOW()")
        params.append(tx_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s RETURNING id, is_confirmed, standard_account_id",
            params,
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Transaction not found")

        tx_id_out, is_confirmed, std_account_id = row[0], row[1], row[2]
        journal_entry_id = None
        journal_error = None

        # 매핑 학습: internal_account_id 변경 시 mapping_rules UPSERT
        if body.internal_account_id is not None:
            # 거래의 counterparty + entity_id 조회
            cur.execute("SELECT counterparty, entity_id FROM transactions WHERE id = %s", [tx_id])
            tx_info = cur.fetchone()
            if tx_info and tx_info[0]:
                learn_mapping_rule(
                    cur,
                    entity_id=tx_info[1],
                    counterparty=tx_info[0],
                    internal_account_id=body.internal_account_id,
                )

            # 내부계정의 표준계정도 자동 설정
            if body.standard_account_id is None:
                cur.execute(
                    "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
                    [body.internal_account_id],
                )
                std_row = cur.fetchone()
                if std_row and std_row[0]:
                    cur.execute(
                        "UPDATE transactions SET standard_account_id = %s WHERE id = %s",
                        [std_row[0], tx_id],
                    )
                    std_account_id = std_row[0]

        # 확정 + 매핑 완료 → 자동 분개 생성 (원자성)
        if is_confirmed and std_account_id:
            try:
                journal_entry_id = create_journal_from_transaction(conn, tx_id_out)
            except ValueError as e:
                if "already exists" not in str(e):
                    journal_error = str(e)

        conn.commit()
        cur.close()
        return {"id": tx_id_out, "updated": True, "journal_entry_id": journal_entry_id, "journal_error": journal_error}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise


@router.post("/auto-map")
def auto_map_unmapped(
    entity_id: int = Query(...),
    year: int = Query(None),
    month: int = Query(None),
    enable_ai: bool = Query(False),
    conn: PgConnection = Depends(get_db),
):
    """자동 매핑: manual/confirmed 제외 거래에 5단계 캐스케이드 적용.

    year/month가 주어지면 해당 월만, 없으면 전체 대상.
    Slack 매칭이 확정된 거래는 item_description을 description에 합쳐서
    키워드/유사 매칭 정확도를 높인다.
    """
    cur = conn.cursor()
    try:
        # manual/confirmed 제외
        month_filter = ""
        params = [entity_id]
        if year and month:
            month_filter = "AND date_trunc('month', t.date) = %s::date"
            params.append(f"{year}-{month:02d}-01")

        cur.execute(
            f"""
            SELECT t.id, t.counterparty, t.description, t.internal_account_id,
                   (
                       SELECT string_agg(
                           COALESCE(tsm.item_description, ''),
                           ' '
                       )
                       FROM transaction_slack_match tsm
                       WHERE tsm.transaction_id = t.id AND tsm.is_confirmed = true
                   ) AS slack_description
            FROM transactions t
            WHERE t.entity_id = %s
              AND (t.counterparty IS NOT NULL OR t.description IS NOT NULL)
              AND (t.mapping_source IS NULL OR t.mapping_source NOT IN ('manual', 'confirmed'))
              AND t.is_duplicate = false
              {month_filter}
            """,
            params,
        )
        targets = cur.fetchall()

        mapped_count = 0
        updated_count = 0
        mapped_ids = []
        for tx_id, counterparty, description, current_ia, slack_desc in targets:
            # Slack 컨텍스트를 description에 합침
            enriched_desc = " ".join(filter(None, [description, slack_desc]))

            mapping = auto_map_transaction(
                cur, entity_id=entity_id,
                counterparty=counterparty,
                description=enriched_desc or None,
                enable_ai=enable_ai,
            )
            if not mapping:
                continue

            new_ia = mapping["internal_account_id"]
            # 미분류 → 매핑: mapped
            # 기존 매핑 → 다른 계정: updated
            if current_ia is None:
                mapped_count += 1
            elif new_ia != current_ia:
                updated_count += 1
            else:
                continue  # 같은 계정이면 스킵

            cur.execute(
                """
                UPDATE transactions
                SET internal_account_id = %s,
                    standard_account_id = %s,
                    mapping_confidence = %s,
                    mapping_source = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                [
                    new_ia,
                    mapping["standard_account_id"],
                    mapping["confidence"],
                    mapping.get("match_type", "rule"),
                    tx_id,
                ],
            )
            mapped_ids.append(tx_id)

        conn.commit()
        cur.close()
        return {
            "total_targets": len(targets),
            "new_mapped": mapped_count,
            "updated": updated_count,
            "mapped_ids": mapped_ids,
        }
    except Exception:
        conn.rollback()
        raise


class BulkMap(BaseModel):
    ids: list[int]
    internal_account_id: int


@router.post("/bulk-map")
def bulk_map(body: BulkMap, conn: PgConnection = Depends(get_db)):
    """선택한 거래들에 내부계정 일괄 매핑 + 매핑 규칙 학습"""
    if not body.ids:
        raise HTTPException(400, "No IDs provided")
    cur = conn.cursor()
    try:
        # 내부계정의 standard_account_id 조회
        cur.execute(
            "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
            [body.internal_account_id],
        )
        std_row = cur.fetchone()
        std_id = std_row[0] if std_row else None

        # 일괄 업데이트
        placeholders = ",".join(["%s"] * len(body.ids))
        cur.execute(
            f"""
            UPDATE transactions
            SET internal_account_id = %s, standard_account_id = %s,
                mapping_source = 'manual', mapping_confidence = 1.0, updated_at = NOW()
            WHERE id IN ({placeholders})
            RETURNING id, counterparty, entity_id
            """,
            [body.internal_account_id, std_id] + body.ids,
        )
        updated = cur.fetchall()

        # 매핑 규칙 학습 (고유 거래처별)
        learned = set()
        for tx_id, counterparty, entity_id in updated:
            if counterparty and counterparty not in learned:
                learn_mapping_rule(
                    cur,
                    entity_id=entity_id,
                    counterparty=counterparty,
                    internal_account_id=body.internal_account_id,
                )
                learned.add(counterparty)

        conn.commit()
        cur.close()
        return {"mapped": len(updated), "rules_learned": len(learned)}
    except Exception:
        conn.rollback()
        raise


@router.post("/bulk-confirm")
def bulk_confirm(body: BulkConfirm, conn: PgConnection = Depends(get_db)):
    if not body.ids:
        raise HTTPException(400, "No IDs provided")
    cur = conn.cursor()
    try:
        placeholders = ",".join(["%s"] * len(body.ids))
        cur.execute(
            f"UPDATE transactions SET is_confirmed = true, mapping_source = 'confirmed', updated_at = NOW() WHERE id IN ({placeholders}) RETURNING id",
            body.ids,
        )
        updated = [r[0] for r in cur.fetchall()]

        # 벌크 확정 → 매핑 규칙 학습 (UPSERT)
        if updated:
            placeholders2 = ",".join(["%s"] * len(updated))
            cur.execute(
                f"""SELECT id, entity_id, counterparty, internal_account_id
                    FROM transactions WHERE id IN ({placeholders2})""",
                updated,
            )
            rules_learned = 0
            for tx_id, eid, cp, ia_id in cur.fetchall():
                if cp and ia_id:
                    learn_mapping_rule(cur, entity_id=eid, counterparty=cp, internal_account_id=ia_id)
                    rules_learned += 1

        # 벌크 확정 → 자동 분개 생성
        journal_created = 0
        journal_skipped = []
        for tx_id in updated:
            try:
                create_journal_from_transaction(conn, tx_id)
                journal_created += 1
            except ValueError as e:
                journal_skipped.append({"id": tx_id, "reason": str(e)})

        conn.commit()
        cur.close()
        return {"confirmed": len(updated), "ids": updated, "journals_created": journal_created, "journal_skipped": journal_skipped}
    except Exception:
        conn.rollback()
        raise


@router.post("/bulk-confirm-month")
def bulk_confirm_month(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """해당 월의 매핑된 미확정 거래 전체 확정 (manual/exact/similar/keyword/ai/rule)"""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE transactions
            SET is_confirmed = true, mapping_source = 'confirmed', updated_at = NOW()
            WHERE entity_id = %s
              AND date_trunc('month', date) = %s::date
              AND internal_account_id IS NOT NULL
              AND is_confirmed = false
              AND (mapping_source IS NULL OR mapping_source NOT IN ('confirmed'))
            RETURNING id
            """,
            [entity_id, f"{year}-{month:02d}-01"],
        )
        updated = [r[0] for r in cur.fetchall()]

        # 매핑 규칙 학습
        if updated:
            placeholders = ",".join(["%s"] * len(updated))
            cur.execute(
                f"""SELECT id, entity_id, counterparty, internal_account_id
                    FROM transactions WHERE id IN ({placeholders})""",
                updated,
            )
            for _, eid, cp, ia_id in cur.fetchall():
                if cp and ia_id:
                    learn_mapping_rule(cur, entity_id=eid, counterparty=cp, internal_account_id=ia_id)

        # 자동 분개 생성
        journal_created = 0
        journal_skipped = []
        for tx_id in updated:
            try:
                create_journal_from_transaction(conn, tx_id)
                journal_created += 1
            except ValueError as e:
                journal_skipped.append({"id": tx_id, "reason": str(e)})

        conn.commit()
        cur.close()
        return {"confirmed": len(updated), "journals_created": journal_created, "journal_skipped": journal_skipped}
    except Exception:
        conn.rollback()
        raise


@router.get("/{tx_id}")
def get_transaction(
    tx_id: int,
    conn: PgConnection = Depends(get_db),
):
    """거래 단건 조회"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.date, t.counterparty, t.description, t.amount, t.type,
               t.source_type, t.mapping_source, t.mapping_confidence,
               ia.name as internal_account_name, sa.name as standard_account_name
        FROM transactions t
        LEFT JOIN internal_accounts ia ON t.internal_account_id = ia.id
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE t.id = %s
        """,
        [tx_id],
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        raise HTTPException(404, "Transaction not found")
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


@router.get("/{tx_id}/slack-match")
def get_slack_match(
    tx_id: int,
    conn: PgConnection = Depends(get_db),
):
    """거래에 연결된 Slack 매칭 정보 조회"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            tsm.slack_message_id,
            sm.text,
            sm.date_override,
            sm.message_type,
            sm.sender_name,
            tsm.created_at AS matched_at,
            tsm.item_index,
            tsm.item_description,
            tsm.is_manual,
            tsm.match_confidence,
            tsm.ai_reasoning,
            tsm.note
        FROM transaction_slack_match tsm
        JOIN slack_messages sm ON sm.id = tsm.slack_message_id
        WHERE tsm.transaction_id = %s
        ORDER BY tsm.created_at DESC
        LIMIT 1
        """,
        [tx_id],
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return None

    return {
        "slack_message_id": row[0],
        "message_text": row[1],
        "message_date": str(row[2]) if row[2] else None,
        "message_type": row[3],
        "sender_name": row[4],
        "matched_at": str(row[5]) if row[5] else None,
        "item_index": row[6],
        "item_description": row[7],
        "match_type": "manual" if row[8] else "auto",
        "match_confidence": float(row[9]) if row[9] is not None else None,
        "ai_reasoning": row[10],
        "note": row[11],
    }


@router.post("/remap")
def remap_batch(
    entity_id: int = Query(...),
    dry_run: bool = Query(False),
    conn: PgConnection = Depends(get_db),
):
    """내부계정 재매핑 배치 — mapping_rules + Slack fallback 기반."""
    from backend.services.remapping_service import remap_transactions
    result = remap_transactions(conn, entity_id, dry_run=dry_run)
    return result

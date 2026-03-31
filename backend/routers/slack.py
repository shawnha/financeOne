"""Slack 메시지 매칭 API -- slack_messages <-> transactions 연결."""

import json
import time
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all
from backend.services.slack.slack_client import find_channel_id, fetch_history, fetch_replies, fetch_user_name, get_reactions
from backend.services.slack.message_parser import parse_message
from backend.services.slack.thread_analyzer import analyze_thread, resolve_slack_status
from backend.services.slack.structured_parser import parse_structured

router = APIRouter(prefix="/api/slack", tags=["slack"])


class ConfirmMatch(BaseModel):
    transaction_id: int
    match_confidence: Optional[float] = None
    ai_reasoning: Optional[str] = None
    note: Optional[str] = None
    amount_override: Optional[float] = None
    text_override: Optional[str] = None
    project_tag_override: Optional[str] = None
    item_index: Optional[int] = None
    item_description: Optional[str] = None


class IgnoreMessage(BaseModel):
    reason: Optional[str] = None


def _build_search_amounts(
    ps: dict,
    parsed_amount: float | None,
    item_index: int | None = None,
) -> list[dict]:
    """매칭 후보 검색에 사용할 금액 목록 생성.

    item_index 지정 시 해당 항목 금액만 반환.
    미지정 시 total_amount + 모든 items + parsed_amount fallback.
    """
    if not ps:
        ps = {}

    structured_total = ps.get("total_amount")
    structured_items = ps.get("items") or []

    # 개별 항목 모드
    if item_index is not None:
        if 0 <= item_index < len(structured_items):
            item = structured_items[item_index]
            item_amt = item.get("amount")
            if item_amt and item_amt > 0:
                return [{"amount": float(item_amt), "label": item.get("description", "")[:30]}]
        return []

    # 전체 모드 (기존 동작)
    search_amounts: list[dict] = []

    if structured_total and structured_total > 0:
        search_amounts.append({"amount": float(structured_total), "label": "총액"})

    for item in structured_items:
        item_amt = item.get("amount")
        if item_amt and item_amt > 0:
            desc = item.get("description", "")[:30]
            search_amounts.append({"amount": float(item_amt), "label": desc})

    if parsed_amount is not None and not search_amounts:
        search_amounts.append({"amount": float(parsed_amount), "label": "파싱금액"})

    return search_amounts


def _get_excluded_transaction_ids(cur, message_id: int) -> set[int]:
    """이미 확정된 매칭의 transaction_id 집합 반환."""
    cur.execute(
        "SELECT transaction_id FROM transaction_slack_match WHERE is_confirmed = true",
    )
    return {row[0] for row in cur.fetchall()}


def _build_item_matches(
    parsed_structured: dict | None,
    match_rows: list[dict],
) -> dict | None:
    """다중 항목 메시지의 항목별 매칭 상태를 빌드.

    items < 2이면 None 반환 (개별 매칭 해당 없음).
    """
    if not parsed_structured or not isinstance(parsed_structured, dict):
        return None

    items = parsed_structured.get("items") or []
    if len(items) < 2:
        return None

    match_by_index = {}
    for mr in match_rows:
        idx = mr.get("item_index")
        if idx is not None:
            match_by_index[idx] = mr

    item_matches = []
    matched_count = 0
    for i, item in enumerate(items):
        mr = match_by_index.get(i)
        is_confirmed = bool(mr and mr.get("is_confirmed"))
        if is_confirmed:
            matched_count += 1
        item_matches.append({
            "item_index": i,
            "item_description": item.get("description", ""),
            "amount": item.get("amount"),
            "currency": item.get("currency", "KRW"),
            "transaction_id": mr["transaction_id"] if mr else None,
            "is_confirmed": is_confirmed,
        })

    return {
        "item_matches": item_matches,
        "match_progress": {
            "total_items": len(items),
            "matched_items": matched_count,
        },
    }


@router.get("/messages")
def list_slack_messages(
    entity_id: Optional[int] = None,
    is_completed: Optional[bool] = None,
    is_cancelled: Optional[bool] = None,
    month: Optional[str] = Query(None, description="YYYY-MM format, e.g. 2026-03"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    conn: PgConnection = Depends(get_db),
):
    """List slack messages with match status."""
    cur = conn.cursor()

    where = ["1=1"]
    params: list = []

    if entity_id is not None:
        where.append("sm.entity_id = %s")
        params.append(entity_id)
    if is_completed is not None:
        where.append("sm.is_completed = %s")
        params.append(is_completed)
    if is_cancelled is not None:
        where.append("sm.is_cancelled = %s")
        params.append(is_cancelled)

    if month:
        # month = "2026-03" → ts 범위 필터 (unix timestamp 기반)
        try:
            year_val, month_val = month.split("-")
            month_start = datetime(int(year_val), int(month_val), 1)
            if int(month_val) == 12:
                month_end = datetime(int(year_val) + 1, 1, 1)
            else:
                month_end = datetime(int(year_val), int(month_val) + 1, 1)
            where.append("CAST(sm.ts AS DOUBLE PRECISION) >= %s")
            params.append(month_start.timestamp())
            where.append("CAST(sm.ts AS DOUBLE PRECISION) < %s")
            params.append(month_end.timestamp())
        except (ValueError, IndexError):
            raise HTTPException(400, "month must be YYYY-MM format")

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(
        f"SELECT COUNT(*) FROM slack_messages sm WHERE {where_clause}",
        params,
    )
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT sm.id, sm.entity_id, sm.ts, sm.channel AS channel_name,
               sm.user_id, sm.text AS message_text,
               sm.parsed_amount, sm.parsed_amount_vat_included,
               sm.vat_flag, sm.project_tag,
               sm.slack_status, sm.message_type,
               sm.sender_name, sm.currency, sm.member_id,
               sm.is_completed, sm.is_cancelled,
               COALESCE(sm.date_override, to_timestamp(CAST(sm.ts AS DOUBLE PRECISION))::date) AS message_date,
               sm.reply_count,
               sm.parsed_structured,
               sm.created_at,
               tsm.id AS match_id,
               tsm.transaction_id AS matched_transaction_id,
               tsm.match_confidence,
               tsm.is_confirmed AS match_confirmed,
               tsm.is_manual AS match_manual,
               m.name AS member_name_ko
        FROM slack_messages sm
        LEFT JOIN transaction_slack_match tsm ON sm.id = tsm.slack_message_id
        LEFT JOIN members m ON m.slack_user_id = sm.user_id AND m.entity_id = sm.entity_id
        WHERE {where_clause}
        ORDER BY sm.ts DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    rows = fetch_all(cur)
    cur.close()

    # ── 항목별 매칭 상태 조회 ──
    message_ids = [r["id"] for r in rows]
    item_match_map = {}
    if message_ids:
        placeholders = ",".join(["%s"] * len(message_ids))
        cur3 = conn.cursor()
        cur3.execute(
            f"""SELECT slack_message_id, item_index, item_description,
                       transaction_id, is_confirmed
                FROM transaction_slack_match
                WHERE slack_message_id IN ({placeholders})
                  AND item_index IS NOT NULL AND is_confirmed = true
                ORDER BY slack_message_id, item_index""",
            message_ids,
        )
        for match_row in fetch_all(cur3):
            mid = match_row["slack_message_id"]
            if mid not in item_match_map:
                item_match_map[mid] = []
            item_match_map[mid].append(match_row)
        cur3.close()

    for row in rows:
        ps = row.get("parsed_structured")
        match_rows_for_msg = item_match_map.get(row["id"], [])
        item_data = _build_item_matches(ps, match_rows_for_msg)
        if item_data:
            row["item_matches"] = item_data["item_matches"]
            row["match_progress"] = item_data["match_progress"]

    # 월별 요약 통계 — month 필터 없이 entity 전체
    summary_where = ["1=1"]
    summary_params: list = []
    if entity_id is not None:
        summary_where.append("sm.entity_id = %s")
        summary_params.append(entity_id)

    summary_where_clause = " AND ".join(summary_where)

    cur2 = conn.cursor()
    cur2.execute(
        f"""
        SELECT
            EXTRACT(YEAR FROM to_timestamp(CAST(sm.ts AS DOUBLE PRECISION)))::int AS yr,
            EXTRACT(MONTH FROM to_timestamp(CAST(sm.ts AS DOUBLE PRECISION)))::int AS mo,
            COUNT(*) AS total,
            COUNT(CASE WHEN sm.slack_status = 'done' THEN 1 END) AS done_count,
            COUNT(CASE WHEN sm.slack_status = 'pending' THEN 1 END) AS pending_count,
            COUNT(CASE WHEN sm.slack_status = 'cancelled' THEN 1 END) AS cancelled_count,
            COALESCE(SUM(sm.parsed_amount) FILTER (WHERE sm.message_type IN ('card_payment', 'expense_share', 'deposit_request', 'tax_invoice')), 0) AS total_expense
        FROM slack_messages sm
        WHERE {summary_where_clause}
        GROUP BY yr, mo
        ORDER BY yr DESC, mo DESC
        """,
        summary_params,
    )
    monthly_summary = fetch_all(cur2)
    cur2.close()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
        "monthly_summary": monthly_summary,
    }


@router.get("/messages/{message_id}/candidates")
def get_candidates(
    message_id: int,
    item_index: Optional[int] = Query(None, description="개별 항목 인덱스 (0-based)"),
    conn: PgConnection = Depends(get_db),
):
    """Find candidate transactions for a slack message.

    Matching strategy:
    1. Amount: exact (±1), ±3%, VAT ×1.1
    2. Date: ±30일 (크로스월 지원), 날짜 근접도 가산
    3. Vendor: 구조화 파싱의 vendor와 거래처명 유사도 가산
    """
    cur = conn.cursor()

    # Get the slack message + structured data
    cur.execute(
        """SELECT id, entity_id, parsed_amount, parsed_amount_vat_included,
                  COALESCE(date_override, to_timestamp(CAST(ts AS DOUBLE PRECISION))::date) AS msg_date,
                  parsed_structured, text
           FROM slack_messages WHERE id = %s""",
        [message_id],
    )
    msg = cur.fetchone()
    if not msg:
        raise HTTPException(404, "Slack message not found")

    msg_id, entity_id, parsed_amount, parsed_amount_vat, msg_date, parsed_structured, msg_text = msg

    # 구조화 파싱에서 정보 추출
    ps = parsed_structured if isinstance(parsed_structured, dict) else {}
    vendor = ps.get("vendor")

    search_amounts = _build_search_amounts(ps, parsed_amount, item_index)

    if not search_amounts:
        cur.close()
        return {"candidates": [], "message_id": message_id, "reason": "금액 정보 없음"}

    # 주 금액 (총액 또는 첫 번째)
    primary_amount = search_amounts[0]["amount"]

    # 모든 검색 금액의 ±3%, VAT 범위를 합쳐서 하나의 쿼리로
    amount_conditions = []
    amount_params: list = []
    for sa in search_amounts:
        amt = sa["amount"]
        lo = round(amt * 0.97, 2)
        hi = round(amt * 1.03, 2)
        vat_amt = round(amt * 1.1, 2)
        vat_lo = round(vat_amt * 0.97, 2)
        vat_hi = round(vat_amt * 1.03, 2)
        amount_conditions.append("(t.amount BETWEEN %s AND %s OR t.amount BETWEEN %s AND %s)")
        amount_params.extend([lo, hi, vat_lo, vat_hi])

    where_parts = ["t.entity_id = %s"]
    params: list = [entity_id]

    where_parts.append("(" + " OR ".join(amount_conditions) + ")")
    params.extend(amount_params)

    if msg_date:
        where_parts.append("t.date BETWEEN %s - interval '30 days' AND %s + interval '30 days'")
        params.extend([msg_date, msg_date])

    excluded_ids = _get_excluded_transaction_ids(cur, message_id)
    if excluded_ids:
        placeholders = ",".join(["%s"] * len(excluded_ids))
        where_parts.append(f"t.id NOT IN ({placeholders})")
        params.extend(list(excluded_ids))

    where_clause = " AND ".join(where_parts)

    # 각 검색 금액별 best match를 위한 CASE 구문 동적 생성
    # 가장 가까운 금액과의 차이 기반 점수
    best_amount_cases = []
    best_amount_params: list = []
    for sa in search_amounts:
        amt = sa["amount"]
        lo = round(amt * 0.97, 2)
        hi = round(amt * 1.03, 2)
        vat_amt = round(amt * 1.1, 2)
        vat_lo = round(vat_amt * 0.97, 2)
        vat_hi = round(vat_amt * 1.03, 2)
        best_amount_cases.append(
            "CASE WHEN ABS(t.amount - %s) <= 1 THEN 0.40"
            " WHEN t.amount BETWEEN %s AND %s THEN 0.30"
            " WHEN t.amount BETWEEN %s AND %s THEN 0.25"
            " ELSE 0 END"
        )
        best_amount_params.extend([amt, lo, hi, vat_lo, vat_hi])

    amount_score_expr = "GREATEST(" + ", ".join(best_amount_cases) + ")"

    # match_type: 주 금액 기준
    match_type_params = [primary_amount,
                         round(primary_amount * 0.97, 2), round(primary_amount * 1.03, 2),
                         round(primary_amount * 1.1 * 0.97, 2), round(primary_amount * 1.1 * 1.03, 2)]

    vendor_case = "0"
    vendor_params: list = []
    if vendor:
        vendor_case = """
            CASE
                WHEN t.counterparty ILIKE %s THEN 0.30
                WHEN t.counterparty ILIKE %s THEN 0.15
                WHEN t.description ILIKE %s THEN 0.15
                ELSE 0
            END"""
        vendor_params = [vendor, f"%{vendor}%", f"%{vendor}%"]

    date_case = "0"
    date_params_score: list = []
    if msg_date:
        date_case = """
            CASE
                WHEN t.date = %s THEN 0.30
                WHEN ABS(t.date - %s) <= 3 THEN 0.25
                WHEN ABS(t.date - %s) <= 7 THEN 0.15
                WHEN ABS(t.date - %s) <= 14 THEN 0.10
                ELSE 0.05
            END"""
        date_params_score = [msg_date, msg_date, msg_date, msg_date]

    cur.execute(
        f"""
        SELECT t.id, t.date, t.amount, t.currency, t.type,
               t.description, t.counterparty, t.source_type,
               t.is_confirmed,
               CASE
                   WHEN ABS(t.amount - %s) <= 1 THEN 'exact'
                   WHEN t.amount BETWEEN %s AND %s THEN 'within_3pct'
                   WHEN t.amount BETWEEN %s AND %s THEN 'vat_match'
                   ELSE 'item_match'
               END AS match_type,
               ROUND((
                   {amount_score_expr}
                   + {date_case}
                   + {vendor_case}
               )::numeric, 2) AS confidence
        FROM transactions t
        WHERE {where_clause}
        ORDER BY confidence DESC, ABS(t.amount - %s) ASC
        LIMIT 20
        """,
        match_type_params
        + best_amount_params + date_params_score + vendor_params
        + params + [primary_amount],
    )
    candidates = fetch_all(cur)
    cur.close()

    return {
        "message_id": message_id,
        "parsed_amount": float(parsed_amount) if parsed_amount else None,
        "structured_total": structured_total,
        "search_amounts": search_amounts,
        "candidates": candidates,
    }


@router.post("/messages/{message_id}/confirm")
def confirm_match(
    message_id: int,
    body: ConfirmMatch,
    conn: PgConnection = Depends(get_db),
):
    """Create a transaction_slack_match record and mark message as completed."""
    cur = conn.cursor()
    try:
        # Verify slack message exists
        cur.execute(
            "SELECT id, entity_id, parsed_structured FROM slack_messages WHERE id = %s",
            [message_id],
        )
        msg = cur.fetchone()
        if not msg:
            raise HTTPException(404, "Slack message not found")

        _, _, parsed_structured = msg

        # Verify transaction exists
        cur.execute("SELECT id FROM transactions WHERE id = %s", [body.transaction_id])
        if not cur.fetchone():
            raise HTTPException(404, "Transaction not found")

        # Check for existing confirmed match
        if body.item_index is not None:
            cur.execute(
                """SELECT id FROM transaction_slack_match
                   WHERE slack_message_id = %s AND item_index = %s AND is_confirmed = true""",
                [message_id, body.item_index],
            )
        else:
            cur.execute(
                """SELECT id FROM transaction_slack_match
                   WHERE slack_message_id = %s AND is_confirmed = true AND item_index IS NULL""",
                [message_id],
            )
        if cur.fetchone():
            raise HTTPException(409, "이 항목은 이미 매칭이 확정되었습니다.")

        # Create match record
        cur.execute(
            """
            INSERT INTO transaction_slack_match
                (transaction_id, slack_message_id, match_confidence, is_manual, is_confirmed,
                 ai_reasoning, note, amount_override, text_override, project_tag_override,
                 item_index, item_description)
            VALUES (%s, %s, %s, true, true, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            [
                body.transaction_id, message_id,
                body.match_confidence or 1.0,
                body.ai_reasoning, body.note,
                body.amount_override, body.text_override, body.project_tag_override,
                body.item_index, body.item_description,
            ],
        )
        match_id = cur.fetchone()[0]

        # is_completed 판단
        ps = parsed_structured if isinstance(parsed_structured, dict) else {}
        items = ps.get("items") or []

        if body.item_index is not None and len(items) >= 2:
            cur.execute(
                """SELECT COUNT(*) FROM transaction_slack_match
                   WHERE slack_message_id = %s AND is_confirmed = true AND item_index IS NOT NULL""",
                [message_id],
            )
            confirmed_count = cur.fetchone()[0]
            is_completed = confirmed_count >= len(items)
        else:
            is_completed = True

        cur.execute(
            "UPDATE slack_messages SET is_completed = %s WHERE id = %s",
            [is_completed, message_id],
        )

        conn.commit()
        cur.close()
        return {
            "match_id": match_id,
            "message_id": message_id,
            "confirmed": True,
            "is_completed": is_completed,
            "item_index": body.item_index,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise


@router.delete("/messages/{message_id}/match/{item_index}")
def undo_item_match(
    message_id: int,
    item_index: int,
    conn: PgConnection = Depends(get_db),
):
    """개별 항목 매칭 확정 취소."""
    cur = conn.cursor()
    try:
        cur.execute(
            """DELETE FROM transaction_slack_match
               WHERE slack_message_id = %s AND item_index = %s AND is_confirmed = true
               RETURNING id""",
            [message_id, item_index],
        )
        deleted = cur.fetchone()
        if not deleted:
            raise HTTPException(404, "해당 항목의 매칭 기록이 없습니다.")

        # is_completed 재계산
        cur.execute(
            "SELECT parsed_structured FROM slack_messages WHERE id = %s",
            [message_id],
        )
        msg = cur.fetchone()
        if msg:
            ps = msg[0] if isinstance(msg[0], dict) else {}
            items = ps.get("items") or []
            if len(items) >= 2:
                cur.execute(
                    """SELECT COUNT(*) FROM transaction_slack_match
                       WHERE slack_message_id = %s AND is_confirmed = true AND item_index IS NOT NULL""",
                    [message_id],
                )
                confirmed_count = cur.fetchone()[0]
                is_completed = confirmed_count >= len(items)
            else:
                is_completed = False

            cur.execute(
                "UPDATE slack_messages SET is_completed = %s WHERE id = %s",
                [is_completed, message_id],
            )

        conn.commit()
        cur.close()
        return {"message_id": message_id, "item_index": item_index, "undone": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise


@router.post("/messages/{message_id}/ignore")
def ignore_message(
    message_id: int,
    body: IgnoreMessage,
    conn: PgConnection = Depends(get_db),
):
    """Mark a slack message as cancelled/ignored. 부분 매칭 시 매칭 레코드도 삭제."""
    cur = conn.cursor()
    try:
        # 부분 매칭 레코드 삭제
        cur.execute(
            "DELETE FROM transaction_slack_match WHERE slack_message_id = %s AND is_confirmed = true",
            [message_id],
        )

        cur.execute(
            "UPDATE slack_messages SET is_cancelled = true, is_completed = false WHERE id = %s RETURNING id",
            [message_id],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Slack message not found")

        conn.commit()
        cur.close()
        return {"message_id": message_id, "ignored": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise


@router.post("/sync")
def sync_slack_channel(
    channel: str = Query("99-expenses"),
    entity_id: int = Query(...),
    year: int = Query(2026),
    months: Optional[str] = None,
    conn: PgConnection = Depends(get_db),
):
    """Slack 채널 메시지 + 쓰레드를 DB에 동기화."""
    cur = conn.cursor()
    try:
        channel_id = find_channel_id(channel)
        messages = fetch_history(channel_id)

        user_cache = {}

        # 멤버 매핑 캐시
        cur.execute(
            "SELECT slack_user_id, id FROM members WHERE entity_id = %s AND slack_user_id IS NOT NULL AND is_active = true",
            [entity_id],
        )
        member_map = {row[0]: row[1] for row in cur.fetchall()}

        target_months = set()
        if months:
            target_months = {int(m) for m in months.split(",")}

        stats = {"total_fetched": len(messages), "new": 0, "updated": 0, "skipped": 0, "structured": 0}

        # 기존 메시지 캐시 (구조화 파싱 스킵 판단용)
        cur.execute(
            "SELECT ts, text, reply_count, parsed_structured IS NOT NULL AS has_structured FROM slack_messages WHERE entity_id = %s",
            [entity_id],
        )
        existing_cache = {row[0]: {"text": row[1], "reply_count": row[2], "has_structured": row[3]} for row in cur.fetchall()}

        for msg in messages:
            ts = msg.get("ts", "")
            text = msg.get("text", "")
            user_id = msg.get("user", "")
            bot_id = msg.get("bot_id")
            subtype = msg.get("subtype")

            # 월 필터
            if target_months:
                try:
                    msg_time = datetime.fromtimestamp(float(ts))
                    if msg_time.year != year or msg_time.month not in target_months:
                        stats["skipped"] += 1
                        continue
                except (ValueError, OSError):
                    stats["skipped"] += 1
                    continue

            is_bot = bool(bot_id)
            is_system = subtype in ("channel_join", "channel_leave", "channel_purpose", "channel_topic")

            parsed = parse_message(text, is_bot=is_bot, is_system=is_system)
            if parsed.get("skip"):
                stats["skipped"] += 1
                continue

            # 유저 이름
            sender_name = None
            if user_id and user_id not in user_cache:
                try:
                    user_cache[user_id] = fetch_user_name(user_id)
                except Exception:
                    user_cache[user_id] = user_id
                time.sleep(0.2)
            sender_name = user_cache.get(user_id)

            member_id = member_map.get(user_id)

            # 쓰레드 분석
            thread_events = {"deposit_done": False, "cancelled": False, "new_amount": None, "file_urls": []}
            reply_count = msg.get("reply_count", 0)
            thread_replies_json = None

            if reply_count > 0:
                try:
                    replies = fetch_replies(channel_id, ts)
                    thread_replies_json = json.dumps(
                        [{"ts": r.get("ts"), "user": r.get("user"), "text": r.get("text", "")[:500],
                          "files": [{"name": f.get("name"), "url": f.get("url_private") or f.get("permalink")} for f in r.get("files", [])]}
                         for r in replies],
                        ensure_ascii=False,
                    )
                    thread_events = analyze_thread(replies, original_amount=parsed.get("parsed_amount"))
                    time.sleep(0.5)
                except Exception:
                    pass

            final_amount = parsed.get("parsed_amount")
            if thread_events.get("new_amount") is not None:
                final_amount = thread_events["new_amount"]

            # 외화 → KRW 변환
            if final_amount is not None and parsed["currency"] != "KRW":
                from backend.services.slack.message_parser import convert_to_krw
                from datetime import datetime as dt
                try:
                    msg_date = dt.fromtimestamp(float(ts)).date()
                    final_amount = convert_to_krw(final_amount, parsed["currency"], msg_date, conn)
                except (ValueError, OSError):
                    pass  # ts 파싱 실패 시 원본 유지

            reactions = get_reactions(msg)
            has_check = "white_check_mark" in reactions

            status_result = resolve_slack_status(parsed["message_type"], has_check, thread_events)

            # ── Claude 구조화 파싱 ──
            parsed_structured = None
            existing = existing_cache.get(ts)
            should_call_claude = (
                existing is None                                    # 신규
                or not existing["has_structured"]                   # 미파싱
                or existing["text"] != text                         # 텍스트 변경
                or existing["reply_count"] < reply_count            # 새 댓글
            )

            if should_call_claude and not parsed.get("skip") and parsed["message_type"] != "other":
                parsed_structured = parse_structured(
                    text,
                    thread_replies=thread_replies_json,
                    skip=False,
                )

            if parsed_structured is not None:
                stats["structured"] += 1

            cur.execute(
                """
                INSERT INTO slack_messages
                    (entity_id, ts, channel, user_id, text, parsed_amount, parsed_amount_vat_included,
                     vat_flag, project_tag, date_override, reply_count, thread_replies_json, raw_json,
                     member_id, message_type, slack_status, currency, withholding_tax, sender_name,
                     sub_amounts, parsed_structured, is_cancelled, deposit_completed_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ts) DO UPDATE SET
                    text = EXCLUDED.text,
                    parsed_amount = EXCLUDED.parsed_amount,
                    parsed_amount_vat_included = EXCLUDED.parsed_amount_vat_included,
                    vat_flag = EXCLUDED.vat_flag,
                    project_tag = EXCLUDED.project_tag,
                    date_override = EXCLUDED.date_override,
                    reply_count = EXCLUDED.reply_count,
                    thread_replies_json = EXCLUDED.thread_replies_json,
                    member_id = EXCLUDED.member_id,
                    message_type = EXCLUDED.message_type,
                    slack_status = EXCLUDED.slack_status,
                    currency = EXCLUDED.currency,
                    withholding_tax = EXCLUDED.withholding_tax,
                    sender_name = EXCLUDED.sender_name,
                    sub_amounts = EXCLUDED.sub_amounts,
                    parsed_structured = CASE
                        WHEN EXCLUDED.parsed_structured IS NOT NULL THEN EXCLUDED.parsed_structured
                        ELSE slack_messages.parsed_structured
                    END,
                    is_cancelled = EXCLUDED.is_cancelled,
                    deposit_completed_date = EXCLUDED.deposit_completed_date
                RETURNING (xmax = 0) AS is_new
                """,
                [
                    entity_id, ts, channel_id, user_id, text,
                    final_amount, parsed.get("parsed_amount_vat_included"),
                    parsed["vat_flag"], parsed["project_tag"], parsed.get("date_override"),
                    reply_count, thread_replies_json, json.dumps(msg, ensure_ascii=False),
                    member_id, parsed["message_type"], status_result["slack_status"],
                    parsed["currency"], parsed["withholding_tax"], sender_name,
                    json.dumps(parsed["sub_amounts"]) if parsed.get("sub_amounts") else None,
                    json.dumps(parsed_structured, ensure_ascii=False) if parsed_structured else None,
                    status_result.get("is_cancelled", False),
                    None,
                ],
            )
            is_new = cur.fetchone()[0]
            if is_new:
                stats["new"] += 1
            else:
                stats["updated"] += 1

        conn.commit()
        cur.close()
        return stats
    except RuntimeError as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        conn.rollback()
        raise

"""Forecasts CRUD API — 예상 현금흐름 입력 데이터.

카테고리별 예상 입금/출금을 생성·조회·수정·삭제.
"""

from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])


class ForecastCreate(BaseModel):
    entity_id: int
    year: int
    month: int
    category: str
    subcategory: Optional[str] = None
    type: str  # 'in' or 'out'
    forecast_amount: float
    is_recurring: bool = False
    internal_account_id: Optional[int] = None
    note: Optional[str] = None
    expected_day: Optional[int] = Field(None, ge=1, le=31)  # CQ-2
    payment_method: str = "bank"


class ForecastUpdate(BaseModel):
    type: Optional[str] = Field(None, pattern="^(in|out)$")
    category: Optional[str] = None
    subcategory: Optional[str] = None
    forecast_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    is_recurring: Optional[bool] = None
    note: Optional[str] = None
    expected_day: Optional[int] = Field(None, ge=1, le=31)
    payment_method: Optional[str] = None


@router.get("")
def list_forecasts(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    """특정 법인/연도의 forecasts 조회. month 생략 시 해당 연도 전체."""
    cur = conn.cursor()
    if month is not None:
        cur.execute(
            """
            SELECT f.id, f.entity_id, f.year, f.month, f.category, f.subcategory, f.type,
                   f.forecast_amount, f.actual_amount, f.is_recurring,
                   f.internal_account_id, ia.name AS internal_account_name,
                   f.note, f.expected_day, f.payment_method, f.created_at, f.updated_at
            FROM forecasts f
            LEFT JOIN internal_accounts ia ON f.internal_account_id = ia.id
            WHERE f.entity_id = %s AND f.year = %s AND f.month = %s
            ORDER BY f.type, f.category, f.subcategory
            """,
            [entity_id, year, month],
        )
    else:
        cur.execute(
            """
            SELECT f.id, f.entity_id, f.year, f.month, f.category, f.subcategory, f.type,
                   f.forecast_amount, f.actual_amount, f.is_recurring,
                   f.internal_account_id, ia.name AS internal_account_name,
                   f.note, f.expected_day, f.payment_method, f.created_at, f.updated_at
            FROM forecasts f
            LEFT JOIN internal_accounts ia ON f.internal_account_id = ia.id
            WHERE f.entity_id = %s AND f.year = %s
            ORDER BY f.month, f.type, f.category, f.subcategory
            """,
            [entity_id, year],
        )
    rows = fetch_all(cur)
    cur.close()

    return {"forecasts": rows, "count": len(rows)}


@router.post("", status_code=201)
def create_forecast(
    body: ForecastCreate,
    conn: PgConnection = Depends(get_db),
):
    """forecast 항목 생성. UPSERT — 동일 키 존재 시 금액 업데이트."""
    if body.type not in ("in", "out"):
        raise HTTPException(400, "type must be 'in' or 'out'")

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO forecasts
            (entity_id, year, month, category, subcategory, type,
             forecast_amount, is_recurring, internal_account_id, note,
             expected_day, payment_method)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (entity_id, year, month, internal_account_id, type)
          WHERE internal_account_id IS NOT NULL
        DO UPDATE SET forecast_amount = EXCLUDED.forecast_amount,
                      is_recurring = EXCLUDED.is_recurring,
                      category = EXCLUDED.category,
                      note = EXCLUDED.note,
                      expected_day = EXCLUDED.expected_day,
                      payment_method = EXCLUDED.payment_method,
                      updated_at = NOW()
        RETURNING id
        """,
        [body.entity_id, body.year, body.month, body.category,
         body.subcategory, body.type, body.forecast_amount,
         body.is_recurring, body.internal_account_id, body.note,
         body.expected_day, body.payment_method],
    )
    forecast_id = cur.fetchone()[0]
    conn.commit()
    cur.close()

    return {"id": forecast_id, "status": "created"}


@router.put("/{forecast_id}")
def update_forecast(
    forecast_id: int,
    body: ForecastUpdate,
    conn: PgConnection = Depends(get_db),
):
    """forecast 항목 부분 수정."""
    cur = conn.cursor()

    # Build dynamic SET clause
    updates = []
    params = []
    if body.type is not None:
        updates.append("type = %s")
        params.append(body.type)
    if body.category is not None:
        cat = body.category.strip()
        if not cat:
            raise HTTPException(400, "category cannot be empty")
        updates.append("category = %s")
        params.append(cat)
    if body.subcategory is not None:
        updates.append("subcategory = %s")
        params.append(body.subcategory.strip() or None)
    if body.forecast_amount is not None:
        updates.append("forecast_amount = %s")
        params.append(body.forecast_amount)
    if body.actual_amount is not None:
        updates.append("actual_amount = %s")
        params.append(body.actual_amount)
    if body.is_recurring is not None:
        updates.append("is_recurring = %s")
        params.append(body.is_recurring)
    if body.note is not None:
        updates.append("note = %s")
        params.append(body.note)
    if body.expected_day is not None:
        updates.append("expected_day = %s")
        params.append(body.expected_day)
    if body.payment_method is not None:
        updates.append("payment_method = %s")
        params.append(body.payment_method)

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = NOW()")
    params.append(forecast_id)

    cur.execute(
        f"UPDATE forecasts SET {', '.join(updates)} WHERE id = %s RETURNING id",
        params,
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Forecast not found")

    conn.commit()
    cur.close()

    return {"id": forecast_id, "status": "updated"}


@router.delete("/{forecast_id}")
def delete_forecast(
    forecast_id: int,
    conn: PgConnection = Depends(get_db),
):
    """forecast 항목 삭제."""
    cur = conn.cursor()
    cur.execute("DELETE FROM forecasts WHERE id = %s RETURNING id", [forecast_id])
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Forecast not found")

    conn.commit()
    cur.close()

    return {"id": forecast_id, "status": "deleted"}


@router.post("/backfill-accounts")
def backfill_forecast_accounts(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """내부계정 미연결 예상항목을 이름 매칭으로 자동 연결."""
    cur = conn.cursor()

    # 1. 미연결 항목 조회
    cur.execute(
        """
        SELECT id, category FROM forecasts
        WHERE entity_id = %s AND year = %s AND month = %s
          AND internal_account_id IS NULL
        """,
        [entity_id, year, month],
    )
    unlinked = fetch_all(cur)

    if not unlinked:
        cur.close()
        return {"matched": 0, "unmatched": []}

    # 2. 해당 법인의 내부계정 전체 조회
    cur.execute(
        """
        SELECT id, name, parent_id
        FROM internal_accounts
        WHERE entity_id = %s AND is_active = true
        """,
        [entity_id],
    )
    accounts = fetch_all(cur)

    # 부모 계정 ID 집합 (리프 계정 우선을 위해)
    parent_ids = {a["parent_id"] for a in accounts if a["parent_id"]}
    # 이름 → 계정 매핑 (리프 계정 우선)
    name_map: dict[str, dict] = {}
    for a in accounts:
        key = a["name"].strip()
        if key not in name_map:
            name_map[key] = a
        elif a["id"] not in parent_ids and name_map[key]["id"] in parent_ids:
            # 기존이 부모고 새 것이 리프면 교체
            name_map[key] = a

    # 3. 매칭 및 업데이트
    matched = 0
    unmatched_names = []
    for item in unlinked:
        cat = item["category"].strip()
        account = name_map.get(cat)
        if account:
            cur.execute(
                "UPDATE forecasts SET internal_account_id = %s, updated_at = NOW() WHERE id = %s",
                [account["id"], item["id"]],
            )
            matched += 1
        else:
            unmatched_names.append(cat)

    conn.commit()
    cur.close()

    return {"matched": matched, "unmatched": unmatched_names}


@router.post("/copy-recurring", status_code=201)
def copy_recurring_forecasts(
    entity_id: int = Query(...),
    source_year: int = Query(...),
    source_month: int = Query(...),
    target_year: int = Query(...),
    target_month: int = Query(...),
    amount_source: str = Query("forecast"),
    conn: PgConnection = Depends(get_db),
):
    """is_recurring=true인 항목을 source → target 월로 복사.
    amount_source='actual'이면 actual_amount 우선 사용 (없으면 forecast_amount fallback).
    """
    if amount_source not in ("forecast", "actual"):
        raise HTTPException(400, "amount_source must be 'forecast' or 'actual'")

    cur = conn.cursor()
    try:
        if amount_source == "actual":
            # transactions 테이블에서 실제 거래 합계를 가져와 forecast_amount로 사용
            cur.execute(
                """
                INSERT INTO forecasts
                    (entity_id, year, month, category, subcategory, type,
                     forecast_amount, is_recurring, internal_account_id, note,
                     expected_day, payment_method)
                SELECT f.entity_id, %s, %s, f.category, f.subcategory, f.type,
                       COALESCE(t.actual_total, f.forecast_amount),
                       f.is_recurring, f.internal_account_id, f.note,
                       f.expected_day, f.payment_method
                FROM forecasts f
                LEFT JOIN (
                    SELECT internal_account_id, type, SUM(amount) AS actual_total
                    FROM transactions
                    WHERE entity_id = %s
                      AND date >= make_date(%s, %s, 1)
                      AND date < make_date(%s, %s, 1) + INTERVAL '1 month'
                      AND is_duplicate = false
                      AND internal_account_id IS NOT NULL
                    GROUP BY internal_account_id, type
                ) t ON t.internal_account_id = f.internal_account_id AND t.type = f.type
                WHERE f.entity_id = %s AND f.year = %s AND f.month = %s AND f.is_recurring = true
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                [target_year, target_month,
                 entity_id, source_year, source_month, source_year, source_month,
                 entity_id, source_year, source_month],
            )
        else:
            cur.execute(
                """
                INSERT INTO forecasts
                    (entity_id, year, month, category, subcategory, type,
                     forecast_amount, is_recurring, internal_account_id, note,
                     expected_day, payment_method)
                SELECT entity_id, %s, %s, category, subcategory, type,
                       forecast_amount, is_recurring, internal_account_id, note,
                       expected_day, payment_method
                FROM forecasts
                WHERE entity_id = %s AND year = %s AND month = %s AND is_recurring = true
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                [target_year, target_month, entity_id, source_year, source_month],
            )
        copied = len(cur.fetchall())
        conn.commit()
        cur.close()
        return {"copied": copied, "target": f"{target_year}-{target_month:02d}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/backfill-accounts")
def backfill_accounts(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """internal_account_id가 NULL인 forecast 항목에 대해 category 이름으로 내부계정 매칭."""
    cur = conn.cursor()

    # 1) Find forecasts with NULL internal_account_id
    cur.execute(
        """
        SELECT id, category
        FROM forecasts
        WHERE entity_id = %s AND year = %s AND month = %s
          AND internal_account_id IS NULL
        """,
        [entity_id, year, month],
    )
    null_forecasts = fetch_all(cur)

    if not null_forecasts:
        cur.close()
        return {"matched": 0, "unmatched": []}

    # 2) Load all internal_accounts for the entity, marking which are leaves
    cur.execute(
        """
        SELECT ia.id, ia.name, ia.parent_id,
               NOT EXISTS (
                   SELECT 1 FROM internal_accounts child
                   WHERE child.parent_id = ia.id
               ) AS is_leaf
        FROM internal_accounts ia
        WHERE ia.entity_id = %s
        """,
        [entity_id],
    )
    accounts = fetch_all(cur)

    # Build lookup: name -> list of matching accounts
    from collections import defaultdict
    name_to_accounts: dict[str, list[dict]] = defaultdict(list)
    for acc in accounts:
        name_to_accounts[acc["name"]].append(acc)

    matched = 0
    unmatched = []

    for fc in null_forecasts:
        category = fc["category"]
        candidates = name_to_accounts.get(category, [])

        if not candidates:
            unmatched.append(category)
            continue

        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            # Prefer leaf accounts (not parents of other accounts)
            leaves = [c for c in candidates if c["is_leaf"]]
            if len(leaves) == 1:
                chosen = leaves[0]
            elif leaves:
                # Multiple leaves — pick the one whose parent_id is set
                # (more specific, under a category group)
                with_parent = [c for c in leaves if c["parent_id"] is not None]
                chosen = with_parent[0] if with_parent else leaves[0]
            else:
                # No leaves — pick first with a parent
                with_parent = [c for c in candidates if c["parent_id"] is not None]
                chosen = with_parent[0] if with_parent else candidates[0]

        cur.execute(
            "UPDATE forecasts SET internal_account_id = %s, updated_at = NOW() WHERE id = %s",
            [chosen["id"], fc["id"]],
        )
        matched += 1

    conn.commit()
    cur.close()

    return {"matched": matched, "unmatched": unmatched}


@router.get("/suggest-from-actuals")
def suggest_forecasts_from_actuals(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """전월 내부계정별 실제 지출을 예상 금액으로 제안."""
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12

    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.internal_account_id,
               ia.name AS account_name,
               ia.code AS account_code,
               ia.is_recurring,
               t.type,
               SUM(t.amount) AS total
        FROM transactions t
        JOIN internal_accounts ia ON t.internal_account_id = ia.id
        WHERE t.entity_id = %s
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND t.is_duplicate = false
          AND t.internal_account_id IS NOT NULL
        GROUP BY t.internal_account_id, ia.name, ia.code, ia.is_recurring, t.type
        ORDER BY ia.is_recurring DESC, total DESC
        """,
        [entity_id, prev_year, prev_month, prev_year, prev_month],
    )
    rows = fetch_all(cur)
    cur.close()

    return {
        "source_year": prev_year,
        "source_month": prev_month,
        "suggestions": rows,
    }


class AddMissingRecurringRequest(BaseModel):
    entity_id: int
    year: int
    month: int
    items: list[dict]  # [{internal_account_id, type, amount}]


@router.get("/missing-recurring")
def missing_recurring(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """is_recurring=TRUE인데 해당 월 forecast에 없는 내부계정 감지.

    Decision 1A: type은 최근 3개월 transactions majority vote.
    Decision 5B: suggested_amount는 majority type의 absolute amount 평균.
    """
    cur = conn.cursor()
    cur.execute(
        """
        WITH recurring_accounts AS (
            SELECT ia.id, ia.name, ia.code
            FROM internal_accounts ia
            WHERE ia.entity_id = %(eid)s
              AND ia.is_recurring = true
              AND ia.is_active = true
              AND ia.id NOT IN (
                  SELECT f.internal_account_id FROM forecasts f
                  WHERE f.entity_id = %(eid)s AND f.year = %(y)s AND f.month = %(m)s
                    AND f.internal_account_id IS NOT NULL
              )
        ),
        txn_agg AS (
            SELECT t.internal_account_id, t.type,
                   COUNT(*) AS cnt,
                   SUM(t.amount) AS total
            FROM transactions t
            WHERE t.entity_id = %(eid)s
              AND t.date >= make_date(%(y)s, %(m)s, 1) - INTERVAL '3 months'
              AND t.date < make_date(%(y)s, %(m)s, 1)
              AND t.is_duplicate = false
              AND t.internal_account_id IN (SELECT id FROM recurring_accounts)
            GROUP BY t.internal_account_id, t.type
        ),
        majority AS (
            SELECT internal_account_id, type AS majority_type, total, cnt,
                   ROW_NUMBER() OVER (
                       PARTITION BY internal_account_id ORDER BY cnt DESC, total DESC
                   ) AS rn
            FROM txn_agg
        ),
        prev_pm AS (
            SELECT DISTINCT ON (internal_account_id)
                   internal_account_id, payment_method
            FROM forecasts
            WHERE entity_id = %(eid)s AND internal_account_id IS NOT NULL
            ORDER BY internal_account_id, year DESC, month DESC
        )
        SELECT ra.id AS internal_account_id, ra.name, ra.code,
               COALESCE(m.majority_type, 'out') AS inferred_type,
               COALESCE(ROUND(m.total / 3.0, 0), 0) AS suggested_amount,
               COALESCE(m.cnt, 0) AS txn_count,
               COALESCE(pm.payment_method, 'bank') AS payment_method
        FROM recurring_accounts ra
        LEFT JOIN majority m ON ra.id = m.internal_account_id AND m.rn = 1
        LEFT JOIN prev_pm pm ON ra.id = pm.internal_account_id
        ORDER BY ra.name
        """,
        {"eid": entity_id, "y": year, "m": month},
    )
    rows = fetch_all(cur)
    cur.close()
    return {"items": rows, "count": len(rows), "year": year, "month": month}


@router.post("/add-missing-recurring", status_code=201)
def add_missing_recurring(
    body: AddMissingRecurringRequest,
    conn: PgConnection = Depends(get_db),
):
    """누락된 반복 항목을 일괄 forecast에 추가. UPSERT로 중복 안전."""
    if not body.items:
        return {"added": 0}

    cur = conn.cursor()
    added = 0
    try:
        for item in body.items:
            ia_id = item.get("internal_account_id")
            inferred_type = item.get("type", "out")
            amount = item.get("amount", 0)
            payment_method = item.get("payment_method", "bank")
            name = item.get("name", "")

            if not ia_id:
                continue
            if inferred_type not in ("in", "out"):
                inferred_type = "out"
            if payment_method not in ("bank", "card"):
                payment_method = "bank"

            cur.execute(
                """
                INSERT INTO forecasts
                    (entity_id, year, month, category, subcategory, type,
                     forecast_amount, is_recurring, internal_account_id, note,
                     expected_day, payment_method)
                VALUES (%s, %s, %s, %s, NULL, %s, %s, true, %s, NULL, NULL, %s)
                ON CONFLICT (entity_id, year, month, internal_account_id, type)
                  WHERE internal_account_id IS NOT NULL
                DO NOTHING
                RETURNING id
                """,
                [body.entity_id, body.year, body.month, name, inferred_type,
                 amount, ia_id, payment_method],
            )
            row = cur.fetchone()
            if row:
                added += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()

    return {"added": added, "target": f"{body.year}-{body.month:02d}"}

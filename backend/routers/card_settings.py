"""Card Settings CRUD API — 카드 결제일, 카드사 정보 관리.

비용 탭 slide-over에서 사용. 시차 보정 계산에 payment_day 활용.
"""

from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all

router = APIRouter(prefix="/api/card-settings", tags=["card-settings"])


class CardSettingCreate(BaseModel):
    entity_id: int
    card_name: str
    source_type: str  # 'lotte_card', 'woori_card'
    payment_day: int = 15
    card_number: Optional[str] = None


class CardSettingUpdate(BaseModel):
    card_name: Optional[str] = None
    payment_day: Optional[int] = None
    card_number: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("")
def list_card_settings(
    entity_id: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """법인의 카드 설정 전체 조회."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, entity_id, card_name, source_type, payment_day,
               card_number, is_active, created_at, updated_at
        FROM card_settings
        WHERE entity_id = %s
        ORDER BY source_type, card_name
        """,
        [entity_id],
    )
    rows = fetch_all(cur)
    cur.close()

    return {"card_settings": rows, "count": len(rows)}


@router.post("", status_code=201)
def create_card_setting(
    body: CardSettingCreate,
    conn: PgConnection = Depends(get_db),
):
    """카드 설정 생성."""
    if body.payment_day < 1 or body.payment_day > 31:
        raise HTTPException(400, "payment_day must be between 1 and 31")

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO card_settings
            (entity_id, card_name, source_type, payment_day, card_number)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (entity_id, source_type, card_number)
        DO UPDATE SET card_name = EXCLUDED.card_name,
                      payment_day = EXCLUDED.payment_day,
                      updated_at = NOW()
        RETURNING id
        """,
        [body.entity_id, body.card_name, body.source_type,
         body.payment_day, body.card_number],
    )
    setting_id = cur.fetchone()[0]
    conn.commit()
    cur.close()

    return {"id": setting_id, "status": "created"}


@router.put("/{setting_id}")
def update_card_setting(
    setting_id: int,
    body: CardSettingUpdate,
    conn: PgConnection = Depends(get_db),
):
    """카드 설정 수정."""
    updates = []
    params = []
    if body.card_name is not None:
        updates.append("card_name = %s")
        params.append(body.card_name)
    if body.payment_day is not None:
        if body.payment_day < 1 or body.payment_day > 31:
            raise HTTPException(400, "payment_day must be between 1 and 31")
        updates.append("payment_day = %s")
        params.append(body.payment_day)
    if body.card_number is not None:
        updates.append("card_number = %s")
        params.append(body.card_number)
    if body.is_active is not None:
        updates.append("is_active = %s")
        params.append(body.is_active)

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = NOW()")
    params.append(setting_id)

    cur = conn.cursor()
    cur.execute(
        f"UPDATE card_settings SET {', '.join(updates)} WHERE id = %s RETURNING id",
        params,
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Card setting not found")

    conn.commit()
    cur.close()

    return {"id": setting_id, "status": "updated"}


@router.delete("/{setting_id}")
def delete_card_setting(
    setting_id: int,
    conn: PgConnection = Depends(get_db),
):
    """카드 설정 삭제."""
    cur = conn.cursor()
    cur.execute("DELETE FROM card_settings WHERE id = %s RETURNING id", [setting_id])
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Card setting not found")

    conn.commit()
    cur.close()

    return {"id": setting_id, "status": "deleted"}

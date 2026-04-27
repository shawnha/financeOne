"""법인 관리 API"""

import logging
import re
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PgConnection
from pydantic import BaseModel, field_validator

from backend.database.connection import get_db
from backend.utils.db import fetch_all

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("")
def list_entities(conn: PgConnection = Depends(get_db)):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, code, name, type, currency, parent_id, is_active, business_number
        FROM entities ORDER BY id
        """
    )
    rows = fetch_all(cur)
    cur.close()
    return rows


class EntityUpdate(BaseModel):
    business_number: str | None = None  # digits-only or None to clear

    @field_validator("business_number")
    @classmethod
    def normalize(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        digits = re.sub(r"\D", "", v)
        if len(digits) not in (10, 12):
            raise ValueError("사업자번호는 숫자 10자리 (또는 12자리 종사업장) 이어야 합니다")
        return digits


@router.patch("/{entity_id}")
def update_entity(entity_id: int, body: EntityUpdate, conn: PgConnection = Depends(get_db)):
    """현재는 business_number 만 PATCH 지원. 나머지 필드는 추후 확장."""
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "변경 필드가 없습니다.")
    cur = conn.cursor()
    try:
        set_parts = [f"{k} = %s" for k in fields]
        params = list(fields.values()) + [entity_id]
        cur.execute(
            f"UPDATE entities SET {', '.join(set_parts)} WHERE id = %s",
            params,
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "법인을 찾을 수 없습니다.")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.exception("update_entity failed")
        raise HTTPException(400, str(e))
    finally:
        cur.close()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, code, name, type, currency, parent_id, is_active, business_number "
        "FROM entities WHERE id = %s",
        [entity_id],
    )
    rows = fetch_all(cur)
    cur.close()
    return rows[0] if rows else None

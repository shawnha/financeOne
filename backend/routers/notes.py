"""Obsidian 노트 생성 API"""

import os
import sys
from pathlib import Path
from datetime import date, datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import build_date_range

router = APIRouter(prefix="/api/notes", tags=["notes"])

VAULT_PATH = os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    "/Users/admin/Desktop/claude/financeone/obsidian-vault",
)

def _get_entities(cur) -> dict:
    """DB에서 법인 목록 조회. Returns: {id: (name, currency)}"""
    cur.execute("SELECT id, name, currency FROM entities WHERE is_active = TRUE ORDER BY id")
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _format_krw(amount: float) -> str:
    if amount >= 0:
        return f"₩{amount:,.0f}"
    return f"-₩{abs(amount):,.0f}"


class GenerateNotesRequest(BaseModel):
    year: int
    month: int | None = None
    include_counterparties: bool = False


@router.post("/generate")
def generate_notes(
    body: GenerateNotesRequest,
    conn: PgConnection = Depends(get_db),
):
    """월별 재무 요약 Obsidian 노트 생성."""
    vault = Path(VAULT_PATH)
    if not vault.exists():
        raise HTTPException(400, f"Vault not found: {VAULT_PATH}")

    months = [body.month] if body.month else list(range(1, 13))
    created = []
    cur = conn.cursor()
    entities = _get_entities(cur)

    for m in months:
        for eid, (ename, currency) in entities.items():
            # 거래 요약
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0),
                    COUNT(*),
                    COUNT(*) FILTER (WHERE is_confirmed = TRUE),
                    COUNT(*) FILTER (WHERE is_confirmed = FALSE)
                FROM transactions
                WHERE entity_id = %s
                  AND date >= %s AND date < %s
                """,
                [eid, *build_date_range(body.year, m)],
            )
            row = cur.fetchone()
            income, expense, tx_count, confirmed, unconfirmed = row

            if tx_count == 0:
                continue

            # 상위 지출처
            cur.execute(
                """
                SELECT counterparty, SUM(amount)
                FROM transactions
                WHERE entity_id = %s AND type = 'out'
                  AND date >= %s AND date < %s
                  AND counterparty IS NOT NULL
                GROUP BY counterparty ORDER BY SUM(amount) DESC LIMIT 5
                """,
                [eid, *build_date_range(body.year, m)],
            )
            top_exp = [(r[0], float(r[1])) for r in cur.fetchall()]

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            net = float(income - expense)
            conf_pct = f"{confirmed / tx_count * 100:.0f}%" if tx_count > 0 else "N/A"

            top_exp_lines = "".join(
                f"- [[{name}]] — {_format_krw(amt)}\n" for name, amt in top_exp
            ) or "- (없음)\n"

            content = f"""---
tags: [월별리포트, 재무, {ename}]
entity: {ename}
entity_id: {eid}
year: {body.year}
month: {m}
generated: {now}
---

# {body.year}년 {m}월 재무 요약 — {ename}

## 현금흐름

| 항목 | 금액 |
|------|------|
| 수입 합계 | {_format_krw(float(income))} |
| 지출 합계 | {_format_krw(float(expense))} |
| 순현금흐름 | {_format_krw(net)} |

## 거래 현황

- 총 거래: **{tx_count}건**
- 확정: {confirmed}건 / 미확정: {unconfirmed}건
- 확정율: **{conf_pct}**

## 상위 지출처
{top_exp_lines}
## 주요 이슈

> [!note] 자동 생성 노트
> FinanceOne에서 자동 생성됨 ({now})

## 다음 달 액션

- [ ] 미확정 거래 {unconfirmed}건 확인
"""
            filepath = vault / "월별 리포트" / str(body.year) / f"{body.year}-{m:02d}-{ename}.md"
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            created.append(str(filepath.name))

    cur.close()
    return {"created": len(created), "files": created, "vault": VAULT_PATH}


@router.get("/status")
def vault_status():
    """Obsidian 볼트 상태 확인."""
    vault = Path(VAULT_PATH)
    if not vault.exists():
        return {"connected": False, "path": VAULT_PATH, "error": "Vault not found"}

    note_count = len(list(vault.rglob("*.md")))
    dirs = [d.name for d in vault.iterdir() if d.is_dir() and not d.name.startswith(".")]

    return {
        "connected": True,
        "path": VAULT_PATH,
        "note_count": note_count,
        "directories": dirs,
    }

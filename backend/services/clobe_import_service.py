# 클로브 세금계산서 파싱 행을 invoices(tax_invoice)로 멱등 적재 — 내사업자번호→entity 매핑, 자연키 dedup
"""clobe 세금계산서 importer.

parse_clobe_tax_invoice() 결과를 invoices 테이블에 적재.
- entity 매핑: 행의 '내 사업자번호' → entities.business_number.
- dedup 자연키: (entity_id, direction, issue_date, total).
  근거: 기존 tax_invoice 행은 counterparty_biz_no=NULL·vat=0·amount=합계로
  저장돼 amount/vat/biz_no 가 clobe 와 불일치 → 공통 신뢰 필드는 합계(total).
- 적재: source_kind='tax_invoice', note='clobe', raw_data=원본 행. 음수(수정세금계산서) 그대로.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Optional


def _natural_key(entity_id: int, row: dict) -> tuple:
    """dedup 자연키. total 은 소수 2자리로 양자화해 부동소수 비교 안정화."""
    total = Decimal(str(row["total"])).quantize(Decimal("0.01"))
    return (entity_id, row["direction"], row["issue_date"], str(total))


def _load_entity_map(cur) -> dict:
    """business_number(정규화) → entity_id."""
    cur.execute("SELECT id, business_number FROM entities WHERE business_number IS NOT NULL")
    out = {}
    for eid, biz in cur.fetchall():
        digits = "".join(c for c in str(biz) if c.isdigit())
        if digits:
            out[digits] = eid
    return out


def import_clobe_invoices(
    conn,
    parsed: list[dict],
    dry_run: bool = True,
    only_entity_id: Optional[int] = None,
    only_direction: Optional[str] = None,
) -> dict:
    """clobe 파싱 행 → invoices 적재 (멱등).

    Args:
        parsed: parse_clobe_tax_invoice()["parsed"].
        dry_run: True 면 INSERT 안 하고 미리보기만.
        only_entity_id: 지정 시 해당 entity 행만 처리.
        only_direction: 'sales'|'purchase' 지정 시 해당 방향만.

    Returns:
        {dry_run, inserted, duplicates, skipped_no_entity, errors,
         new_rows[], dup_rows[], by_bucket{}}
    """
    cur = conn.cursor()
    try:
        entity_map = _load_entity_map(cur)

        # 적재 대상에 들어갈 (entity, key) 들을 미리 모아 기존 DB 조회로 dedup 판정
        candidates = []
        skipped_no_entity = 0
        errors: list = []
        for row in parsed:
            biz = row.get("entity_biz_no")
            eid = entity_map.get(biz) if biz else None
            if eid is None:
                skipped_no_entity += 1
                continue
            if only_entity_id is not None and eid != only_entity_id:
                continue
            if only_direction is not None and row["direction"] != only_direction:
                continue
            candidates.append((eid, row))

        # 기존 DB 자연키 집합 조회 (대상 entity/direction/issue_date 범위)
        existing_keys = set()
        if candidates:
            eids = sorted({c[0] for c in candidates})
            cur.execute(
                """
                SELECT entity_id, direction, issue_date::text, total
                FROM invoices
                WHERE entity_id = ANY(%s)
                """,
                [eids],
            )
            for eid, direction, isodate, total in cur.fetchall():
                t = Decimal(str(total)).quantize(Decimal("0.01"))
                existing_keys.add((eid, direction, isodate, str(t)))

        new_rows = []
        dup_rows = []
        seen_batch = set()
        for eid, row in candidates:
            key = _natural_key(eid, row)
            if key in existing_keys or key in seen_batch:
                dup_rows.append({"entity_id": eid, **row})
                continue
            seen_batch.add(key)
            new_rows.append({"entity_id": eid, **row})

        inserted = 0
        if not dry_run and new_rows:
            for r in new_rows:
                cur.execute(
                    """
                    INSERT INTO invoices (
                        entity_id, direction, counterparty, counterparty_biz_no,
                        issue_date, due_date, document_no,
                        amount, vat, total, currency,
                        description, status, source_kind, note, raw_data
                    ) VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,'KRW',%s,'open','tax_invoice','clobe',%s)
                    """,
                    [
                        r["entity_id"], r["direction"], r["counterparty"], r["counterparty_biz_no"],
                        r["issue_date"], r["due_date"],
                        r["amount"], r["vat"], r["total"],
                        r["description"],
                        json.dumps(r["raw"], ensure_ascii=False),
                    ],
                )
                inserted += 1
            conn.commit()

        # 버킷 요약 (entity×direction)
        by_bucket: dict = {}
        for r in new_rows:
            k = f"{r['entity_id']}:{r['direction']}"
            b = by_bucket.setdefault(k, {"new": 0, "new_total": 0.0})
            b["new"] += 1
            b["new_total"] += r["total"]

        return {
            "dry_run": dry_run,
            "inserted": inserted,
            "new": len(new_rows),
            "duplicates": len(dup_rows),
            "skipped_no_entity": skipped_no_entity,
            "errors": errors,
            "new_rows": new_rows,
            "dup_rows": dup_rows,
            "by_bucket": by_bucket,
        }
    finally:
        cur.close()

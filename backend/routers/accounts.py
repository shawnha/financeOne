"""계정과목 API — CRUD for standard/internal accounts and members"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.utils.db import fetch_all

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


# ---------------------------------------------------------------------------
# 계정별 원장 (Ledger)
# ---------------------------------------------------------------------------

@router.get("/{account_code}/ledger")
def get_account_ledger(
    account_code: str,
    entity_id: int = Query(...),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    conn: PgConnection = Depends(get_db),
):
    """특정 standard_account 의 분개 history (계정별 원장).

    Returns: { account, opening_balance, lines: [...], summary: {debit, credit, ending} }
    """
    cur = conn.cursor()

    # 1. account 정보 조회
    cur.execute(
        """
        SELECT id, code, name, category, subcategory, normal_side
        FROM standard_accounts WHERE code = %s
        """,
        [account_code],
    )
    acc_row = cur.fetchone()
    if not acc_row:
        cur.close()
        raise HTTPException(404, f"Account {account_code} not found")
    account = {
        "id": acc_row[0], "code": acc_row[1], "name": acc_row[2],
        "category": acc_row[3], "subcategory": acc_row[4], "normal_side": acc_row[5],
    }

    # 2. 기초 잔액 (start_date 이전까지)
    opening = 0.0
    if start_date:
        cur.execute(
            """
            SELECT
              COALESCE(SUM(jel.debit_amount), 0) - COALESCE(SUM(jel.credit_amount), 0) AS bal
            FROM journal_entry_lines jel
            JOIN journal_entries je ON je.id = jel.journal_entry_id
            WHERE je.entity_id = %s
              AND jel.standard_account_id = %s
              AND je.entry_date < %s
            """,
            [entity_id, account["id"], start_date],
        )
        r = cur.fetchone()
        opening = float(r[0]) if r else 0.0
        # 대변 normal account 면 부호 반전
        if account["normal_side"] == "credit":
            opening = -opening

    # 3. 기간 내 분개 lines
    where = ["je.entity_id = %s", "jel.standard_account_id = %s"]
    params = [entity_id, account["id"]]
    if start_date:
        where.append("je.entry_date >= %s")
        params.append(start_date)
    if end_date:
        where.append("je.entry_date <= %s")
        params.append(end_date)

    # 페이지네이션 — 전체 count
    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.journal_entry_id
        WHERE {' AND '.join(where)}
        """,
        params,
    )
    total = cur.fetchone()[0]

    offset = (page - 1) * per_page
    cur.execute(
        f"""
        SELECT
          je.id AS journal_entry_id, je.entry_date, je.description AS je_description,
          jel.debit_amount, jel.credit_amount, jel.description AS line_description,
          t.id AS transaction_id, t.counterparty, t.source_type
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.journal_entry_id
        LEFT JOIN transactions t ON t.id = je.transaction_id
        WHERE {' AND '.join(where)}
        ORDER BY je.entry_date, je.id, jel.id
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    rows = cur.fetchall()

    # 4. running balance 계산
    running = opening
    lines = []
    sum_debit = 0.0
    sum_credit = 0.0
    for r in rows:
        debit = float(r[3]) if r[3] else 0.0
        credit = float(r[4]) if r[4] else 0.0
        sum_debit += debit
        sum_credit += credit
        if account["normal_side"] == "debit":
            running += debit - credit
        else:
            running += credit - debit
        lines.append({
            "journal_entry_id": r[0],
            "entry_date": r[1].isoformat() if r[1] else None,
            "entry_description": r[2],
            "debit": debit,
            "credit": credit,
            "line_description": r[5],
            "running_balance": running,
            "transaction_id": r[6],
            "counterparty": r[7],
            "source_type": r[8],
        })

    cur.close()

    ending = running
    return {
        "account": account,
        "entity_id": entity_id,
        "start_date": start_date,
        "end_date": end_date,
        "opening_balance": opening,
        "lines": lines,
        "summary": {
            "total_debit": sum_debit,
            "total_credit": sum_credit,
            "net_change": sum_debit - sum_credit if account["normal_side"] == "debit" else sum_credit - sum_debit,
            "ending_balance": ending,
            "line_count": len(lines),
        },
        "pagination": {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page},
    }


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class InternalAccountCreate(BaseModel):
    entity_id: int
    code: str
    name: str
    standard_account_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = 0
    is_recurring: Optional[bool] = False


class InternalAccountUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    standard_account_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    is_recurring: Optional[bool] = None


class InternalAccountCopy(BaseModel):
    source_entity_id: int
    target_entity_id: int
    mode: str = "merge"            # "merge" | "replace"
    include_recurring: bool = True
    include_standard_mapping: bool = True
    preview: bool = False           # True 면 시뮬레이션 후 rollback
    fix_existing_parents: bool = True  # merge 시 같은 code 가 있으면 parent_id 만 source 트리 기준으로 갱신 (트리 깨짐 보정)


def _normalize_card_number(raw: str) -> str:
    """멤버 카드번호를 '****XXXX' (뒤 4자리) 포맷으로 정규화.

    허용 입력: '1114', '****1114', '5105-xxxx-xxxx-1114', '5105 1234 5678 1114' 등.
    뒤 4자리만 추출해 마스킹 prefix 부여.
    """
    if not raw:
        return raw
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 4:
        return f"****{digits[-4:]}"
    return raw.strip()


def _normalize_card_list(raw: Optional[list[str]]) -> Optional[list[str]]:
    if raw is None:
        return None
    # dedupe preserving order
    seen = set()
    out: list[str] = []
    for c in raw:
        n = _normalize_card_number(c)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


class MemberCreate(BaseModel):
    entity_id: int
    name: str
    role: Optional[str] = "staff"
    card_numbers: Optional[list[str]] = None
    slack_user_id: Optional[str] = None


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    card_numbers: Optional[list[str]] = None
    slack_user_id: Optional[str] = None


class MappingRuleUpdate(BaseModel):
    internal_account_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Standard accounts (read-only)
# ---------------------------------------------------------------------------

@router.get("/standard")
def list_standard_accounts(
    entity_id: Optional[int] = None,
    gaap_type: Optional[str] = Query(None, description="K_GAAP | US_GAAP — 미지정시 entity type 기반 자동 결정"),
    conn: PgConnection = Depends(get_db),
):
    """표준 계정과목 조회.

    - entity_id 지정 + gaap_type 미지정 → entity.type 으로 자동 필터:
        US_CORP (HOI) → gaap_type='US_GAAP'
        KR_CORP (HOK/HOR/HOW) → gaap_type='K_GAAP'
    - gaap_type 명시 시 그 값으로 필터
    - 둘 다 미지정 → 모든 GAAP 반환 (관리/디버깅용)
    """
    cur = conn.cursor()

    # entity_id → gaap_type 자동 결정
    resolved_gaap = gaap_type
    if entity_id is not None and resolved_gaap is None:
        cur.execute("SELECT type FROM entities WHERE id = %s", [entity_id])
        ent_row = cur.fetchone()
        if ent_row:
            resolved_gaap = "US_GAAP" if ent_row[0] == "US_CORP" else "K_GAAP"

    gaap_clause = "AND sa.gaap_type = %s" if resolved_gaap else ""
    gaap_clause_simple = "AND gaap_type = %s" if resolved_gaap else ""

    if entity_id is not None:
        params = [entity_id]
        if resolved_gaap:
            params.append(resolved_gaap)
        cur.execute(
            f"""
            SELECT sa.id, sa.code, sa.name, sa.category, sa.subcategory,
                   sa.normal_side, sa.sort_order, sa.description, sa.gaap_type,
                   ia.id AS mapped_internal_id,
                   ia.name AS mapped_internal_name,
                   ia.code AS mapped_internal_code
            FROM standard_accounts sa
            LEFT JOIN internal_accounts ia
              ON ia.standard_account_id = sa.id
              AND ia.entity_id = %s
              AND ia.is_active = true
            WHERE sa.is_active = true
              {gaap_clause}
            ORDER BY sa.sort_order, sa.code
            """,
            params,
        )
    else:
        params = []
        if resolved_gaap:
            params.append(resolved_gaap)
        cur.execute(
            f"""
            SELECT id, code, name, category, subcategory, normal_side, sort_order, description, gaap_type
            FROM standard_accounts WHERE is_active = true {gaap_clause_simple}
            ORDER BY sort_order, code
            """,
            params,
        )
    rows = fetch_all(cur)
    cur.close()
    return rows


# ---------------------------------------------------------------------------
# Internal accounts — CRUD
# ---------------------------------------------------------------------------

@router.get("/internal")
def list_internal_accounts(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    if entity_id is not None:
        cur.execute(
            """
            SELECT ia.id, ia.entity_id, ia.code, ia.name,
                   sa.code AS standard_code, sa.name AS standard_name,
                   ia.sort_order, ia.parent_id, ia.is_recurring
            FROM internal_accounts ia
            LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
            WHERE ia.entity_id = %s AND ia.is_active = true
            ORDER BY ia.sort_order, ia.code
            """,
            [entity_id],
        )
    else:
        cur.execute(
            """
            SELECT ia.id, ia.entity_id, ia.code, ia.name,
                   sa.code AS standard_code, sa.name AS standard_name,
                   ia.sort_order, ia.parent_id, ia.is_recurring
            FROM internal_accounts ia
            LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
            WHERE ia.is_active = true
            ORDER BY ia.entity_id, ia.sort_order, ia.code
            """
        )
    rows = fetch_all(cur)
    cur.close()
    return rows


@router.post("/internal", status_code=201)
def create_internal_account(
    body: InternalAccountCreate,
    conn: PgConnection = Depends(get_db),
):
    from backend.services.standard_account_recommender import recommend_standard_account

    cur = conn.cursor()
    try:
        # 표준계정 미지정 시 자동 추천
        std_account_id = body.standard_account_id
        recommendation = None
        if not std_account_id:
            recommendation = recommend_standard_account(
                cur,
                entity_id=body.entity_id,
                account_name=body.name,
                parent_id=body.parent_id,
            )
            if recommendation:
                std_account_id = recommendation["standard_account_id"]

        cur.execute(
            """
            INSERT INTO internal_accounts
                (entity_id, code, name, standard_account_id, parent_id, sort_order, is_recurring)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, entity_id, code, name, standard_account_id,
                      parent_id, sort_order, is_active, is_recurring
            """,
            [
                body.entity_id,
                body.code,
                body.name,
                std_account_id,
                body.parent_id,
                body.sort_order,
                body.is_recurring,
            ],
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        if recommendation:
            row["std_recommendation"] = recommendation
        conn.commit()
        return row
    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            raise HTTPException(
                status_code=409,
                detail=f"Account code '{body.code}' already exists for entity {body.entity_id}",
            )
        raise HTTPException(status_code=400, detail=error_msg)
    finally:
        cur.close()


@router.post("/internal/copy")
def copy_internal_accounts(
    body: InternalAccountCopy,
    conn: PgConnection = Depends(get_db),
):
    """다른 법인의 내부 계정과목을 현재 법인으로 복사.

    mode:
      - "merge": 기존 계정 유지, source 의 같은 code 는 skip
      - "replace": 기존 활성 계정 모두 비활성화 후 source 그대로 복사
    preview=True 면 INSERT 시뮬레이션 후 rollback (UI 미리보기용).

    부모-자식 관계는 source 의 parent_id 를 새 ID 로 remap 하여 보존.
    """
    if body.source_entity_id == body.target_entity_id:
        raise HTTPException(400, "source 와 target 법인이 동일합니다")
    if body.mode not in ("merge", "replace"):
        raise HTTPException(400, "mode 는 'merge' 또는 'replace' 만 허용됩니다")

    cur = conn.cursor()
    try:
        # 1) 두 법인 검증
        cur.execute(
            "SELECT id, name FROM entities WHERE id IN (%s, %s)",
            [body.source_entity_id, body.target_entity_id],
        )
        ents = cur.fetchall()
        if len(ents) != 2:
            raise HTTPException(404, "법인을 찾을 수 없습니다")
        ent_name = {r[0]: r[1] for r in ents}

        # 2) source 계정 로드
        cur.execute(
            """
            SELECT id, code, name, standard_account_id, parent_id,
                   sort_order, is_recurring
            FROM internal_accounts
            WHERE entity_id = %s AND is_active = true
            """,
            [body.source_entity_id],
        )
        src_rows = cur.fetchall()
        # tuple → dict 로 사용성 향상
        src = [
            {
                "id": r[0], "code": r[1], "name": r[2],
                "std_id": r[3], "parent_id": r[4],
                "sort_order": r[5] or 0, "is_recurring": bool(r[6]),
            }
            for r in src_rows
        ]
        src_by_id = {r["id"]: r for r in src}

        # 3) target 기존 active 계정 — skip 시 자식이 부모로 참조 가능하도록 code→id 매핑 보존
        cur.execute(
            "SELECT id, code FROM internal_accounts WHERE entity_id = %s AND is_active = true",
            [body.target_entity_id],
        )
        target_before_rows = cur.fetchall()
        target_before = [r[1] for r in target_before_rows]
        target_id_by_code: dict[str, int] = {r[1]: r[0] for r in target_before_rows}
        existing_codes = set(target_before)

        deactivated = 0
        if body.mode == "replace":
            cur.execute(
                "UPDATE internal_accounts SET is_active = false "
                "WHERE entity_id = %s AND is_active = true",
                [body.target_entity_id],
            )
            deactivated = cur.rowcount or 0
            existing_codes = set()
            target_id_by_code = {}   # 모두 비활성화됐으니 lookup 불필요

        # 4) depth 계산 — 부모 먼저 INSERT 되도록 정렬
        depth_cache: dict[int, int] = {}

        def get_depth(rid: int, stack: set) -> int:
            if rid in depth_cache:
                return depth_cache[rid]
            if rid in stack:           # cycle 방어
                depth_cache[rid] = 0
                return 0
            row = src_by_id.get(rid)
            if not row:
                return 0
            pid = row["parent_id"]
            if pid is None or pid not in src_by_id:
                depth_cache[rid] = 0
            else:
                stack.add(rid)
                depth_cache[rid] = get_depth(pid, stack) + 1
                stack.discard(rid)
            return depth_cache[rid]

        for r in src:
            get_depth(r["id"], set())

        src_sorted = sorted(
            src,
            key=lambda r: (depth_cache.get(r["id"], 0), r["sort_order"], r["id"]),
        )

        # 5) 순차 INSERT — old_id → new_id 맵 유지
        id_map: dict[int, int] = {}
        inserted = 0
        skipped_existing = 0
        fixed_parents = 0

        for r in src_sorted:
            if r["code"] in existing_codes:
                skipped_existing += 1
                # 자식들이 이 부모를 참조할 수 있도록 target 의 같은 code id 를 id_map 에 등록
                target_id = target_id_by_code.get(r["code"])
                if target_id:
                    id_map[r["id"]] = target_id

                # 트리 보정: source 의 parent_id 를 따라가서 target 의 같은 code 의 id 를
                # 새 parent_id 로 UPDATE. 사용자가 이미 만든 매핑은 standard_account_id 로 보존,
                # parent 만 source 트리에 맞게 갱신.
                if body.fix_existing_parents and target_id:
                    src_parent = src_by_id.get(r["parent_id"]) if r["parent_id"] else None
                    desired_parent_id: int | None = None
                    if src_parent:
                        desired_parent_id = target_id_by_code.get(src_parent["code"])
                        if desired_parent_id is None:
                            # source 부모가 INSERT 된 신규일 수도 — id_map 에서 찾음
                            desired_parent_id = id_map.get(src_parent["id"])
                    # 현재 target row 의 parent_id 조회 후 다르면 UPDATE
                    cur.execute(
                        "SELECT parent_id FROM internal_accounts WHERE id = %s",
                        [target_id],
                    )
                    cur_row = cur.fetchone()
                    current_parent = cur_row[0] if cur_row else None
                    if current_parent != desired_parent_id:
                        cur.execute(
                            "UPDATE internal_accounts SET parent_id = %s WHERE id = %s",
                            [desired_parent_id, target_id],
                        )
                        fixed_parents += 1
                continue
            old_pid = r["parent_id"]
            new_pid = id_map.get(old_pid) if old_pid else None
            std_id = r["std_id"] if body.include_standard_mapping else None
            is_rec = r["is_recurring"] if body.include_recurring else False

            cur.execute(
                """
                INSERT INTO internal_accounts
                    (entity_id, code, name, standard_account_id, parent_id,
                     sort_order, is_recurring)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                [
                    body.target_entity_id, r["code"], r["name"],
                    std_id, new_pid, r["sort_order"], is_rec,
                ],
            )
            new_id = cur.fetchone()[0]
            id_map[r["id"]] = new_id
            inserted += 1

        cur.execute(
            "SELECT COUNT(*) FROM internal_accounts WHERE entity_id = %s AND is_active = true",
            [body.target_entity_id],
        )
        target_after = cur.fetchone()[0]

        result = {
            "source": {
                "entity_id": body.source_entity_id,
                "name": ent_name.get(body.source_entity_id),
                "total": len(src),
            },
            "target": {
                "entity_id": body.target_entity_id,
                "name": ent_name.get(body.target_entity_id),
                "before": len(target_before),
                "after": target_after,
            },
            "mode": body.mode,
            "preview": body.preview,
            "inserted": inserted,
            "skipped_existing": skipped_existing,
            "deactivated": deactivated,
            "fixed_parents": fixed_parents,
        }

        if body.preview:
            conn.rollback()
        else:
            conn.commit()
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"복사 실패: {e}")
    finally:
        cur.close()


class InternalAutoMapStandard(BaseModel):
    entity_id: int
    only_unmapped: bool = True   # True 면 standard_account_id IS NULL 만 대상
    min_confidence: float = 0.55
    apply: bool = False           # False = preview, True = 실제 UPDATE


@router.post("/internal/auto-map-standard")
def auto_map_standard(
    body: InternalAutoMapStandard,
    conn: PgConnection = Depends(get_db),
):
    """internal_accounts 의 standard_account_id 자동 매핑 (이름/거래처 통계 기반).

    매핑 알고리즘 (entity 의 GAAP 자동 결정):
      1. internal_account.name 과 standard_accounts.name similarity (pg_trgm) 매칭
      2. 그 internal_account 에 매핑된 transactions 의 거래처 → standard_account_keywords 빈도 통계
      3. 두 신호 weighted: 0.4 * name_sim + 0.6 * keyword_freq_ratio
      4. min_confidence 이상만 채택

    apply=False (preview) 면 후보 list 반환만, apply=True 면 UPDATE.
    """
    cur = conn.cursor()
    try:
        # 1) entity 검증 + GAAP 결정
        cur.execute("SELECT id, type FROM entities WHERE id = %s", [body.entity_id])
        ent = cur.fetchone()
        if not ent:
            raise HTTPException(404, "법인을 찾을 수 없음")
        gaap_type = "US_GAAP" if ent[1] == "US_CORP" else "K_GAAP"

        # 2) 대상 internal_accounts
        where = "ia.entity_id = %s AND ia.is_active = true"
        params = [body.entity_id]
        if body.only_unmapped:
            where += " AND ia.standard_account_id IS NULL"
        cur.execute(
            f"""
            SELECT ia.id, ia.code, ia.name, ia.standard_account_id
            FROM internal_accounts ia
            WHERE {where}
            ORDER BY ia.sort_order, ia.code
            """,
            params,
        )
        targets = cur.fetchall()

        proposals: list[dict] = []
        for ia_id, ia_code, ia_name, current_std_id in targets:
            # 0순위: internal_code 가 standard_accounts.code 에 정확 매칭되면 즉시 채택
            # (A3 seed 처럼 ledger 코드 기반으로 만들어진 internal_account 에 적용)
            cur.execute(
                """
                SELECT id, code, name FROM standard_accounts
                WHERE code = %s AND gaap_type = %s AND is_active = true
                LIMIT 1
                """,
                [ia_code, gaap_type],
            )
            exact = cur.fetchone()
            if exact:
                proposals.append({
                    "internal_id": ia_id, "internal_code": ia_code, "internal_name": ia_name,
                    "current_std_id": current_std_id,
                    "best": {"std_id": exact[0], "code": exact[1], "name": exact[2],
                             "name_sim": 1.0, "kw_freq": 0.0},
                    "confidence": 0.99,
                    "alternatives": [],
                    "accepted": True,
                    "reason": "exact_code_match",
                })
                continue

            # 1순위: name similarity
            cur.execute(
                """
                SELECT id, code, name, similarity(name, %s) AS sim
                FROM standard_accounts
                WHERE gaap_type = %s AND is_active = true
                  AND similarity(name, %s) > 0.2
                ORDER BY sim DESC
                LIMIT 3
                """,
                [ia_name, gaap_type, ia_name],
            )
            name_candidates = [
                {"std_id": r[0], "code": r[1], "name": r[2], "name_sim": float(r[3])}
                for r in cur.fetchall()
            ]

            # keyword freq — 이 internal_account 에 매핑된 transactions 의 counterparty
            cur.execute(
                """
                SELECT sak.standard_account_id, COUNT(*) AS hits
                FROM transactions t
                JOIN standard_account_keywords sak
                  ON t.counterparty ILIKE '%%' || sak.keyword || '%%'
                JOIN standard_accounts sa
                  ON sa.id = sak.standard_account_id
                 AND sa.gaap_type = %s
                WHERE t.entity_id = %s
                  AND t.internal_account_id = %s
                GROUP BY sak.standard_account_id
                ORDER BY hits DESC
                LIMIT 3
                """,
                [gaap_type, body.entity_id, ia_id],
            )
            kw_rows = cur.fetchall()
            kw_total = sum(r[1] for r in kw_rows) or 1
            kw_freq = {r[0]: r[1] / kw_total for r in kw_rows}

            # 후보 score 계산: 두 신호 합산
            score: dict[int, dict] = {}
            for c in name_candidates:
                score[c["std_id"]] = {
                    "std_id": c["std_id"], "code": c["code"], "name": c["name"],
                    "name_sim": c["name_sim"], "kw_freq": kw_freq.get(c["std_id"], 0.0),
                }
            for sid, freq in kw_freq.items():
                if sid not in score:
                    cur.execute(
                        "SELECT code, name FROM standard_accounts WHERE id = %s",
                        [sid],
                    )
                    r = cur.fetchone()
                    if r:
                        score[sid] = {
                            "std_id": sid, "code": r[0], "name": r[1],
                            "name_sim": 0.0, "kw_freq": freq,
                        }
            # 가중치 동적 조정: keyword 신호 있으면 두 신호 weighted, 없으면 name 단독
            def _score(x: dict) -> float:
                if kw_total > 1:    # 거래 데이터 충분
                    return 0.4 * x["name_sim"] + 0.6 * x["kw_freq"]
                return 0.9 * x["name_sim"]    # name_sim 단독 모드 (kw_total ≤ 1)

            ranked = sorted(score.values(), key=lambda x: -_score(x))
            best = ranked[0] if ranked else None
            confidence = round(_score(best), 2) if best else 0.0

            proposals.append({
                "internal_id": ia_id,
                "internal_code": ia_code,
                "internal_name": ia_name,
                "current_std_id": current_std_id,
                "best": best,
                "confidence": confidence,
                "alternatives": ranked[1:3],
                "accepted": bool(best and confidence >= body.min_confidence),
                "reason": "name_sim+kw_freq" if kw_total > 1 else "name_sim_only",
            })

        # 3) apply
        applied = 0
        if body.apply:
            for p in proposals:
                if not p["accepted"]:
                    continue
                cur.execute(
                    """
                    UPDATE internal_accounts
                       SET standard_account_id = %s, updated_at = NOW()
                     WHERE id = %s
                    """,
                    [p["best"]["std_id"], p["internal_id"]],
                )
                applied += 1
            conn.commit()

        return {
            "entity_id": body.entity_id,
            "gaap_type": gaap_type,
            "total_targets": len(targets),
            "accepted": sum(1 for p in proposals if p["accepted"]),
            "rejected_low_confidence": sum(1 for p in proposals if not p["accepted"]),
            "applied": applied,
            "preview": not body.apply,
            "proposals": proposals,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"표준계정 자동매핑 실패: {e}")
    finally:
        cur.close()


@router.get("/internal/recommend-standard")
def recommend_standard(
    entity_id: int = Query(...),
    name: str = Query(...),
    parent_id: int | None = Query(None),
    conn: PgConnection = Depends(get_db),
):
    """내부계정 이름으로 표준계정 추천 (미리보기용)"""
    from backend.services.standard_account_recommender import recommend_standard_account

    cur = conn.cursor()
    result = recommend_standard_account(cur, entity_id=entity_id, account_name=name, parent_id=parent_id)
    cur.close()
    if not result:
        return {"recommendation": None}

    # 표준계정 이름도 같이 반환
    cur2 = conn.cursor()
    cur2.execute(
        "SELECT code, name FROM standard_accounts WHERE id = %s",
        [result["standard_account_id"]],
    )
    sa = cur2.fetchone()
    cur2.close()
    if sa:
        result["standard_code"] = sa[0]
        result["standard_name"] = sa[1]
    return {"recommendation": result}


class SortOrderItem(BaseModel):
    id: int
    sort_order: int
    parent_id: Optional[int] = None


class BulkSortOrderUpdate(BaseModel):
    items: list[SortOrderItem]


@router.put("/internal/sort-order")
def bulk_update_sort_order(
    body: BulkSortOrderUpdate,
    conn: PgConnection = Depends(get_db),
):
    """드래그앤드롭 후 전체 순서 + 부모 일괄 업데이트"""
    cur = conn.cursor()
    try:
        for item in body.items:
            cur.execute(
                """
                UPDATE internal_accounts
                SET sort_order = %s, parent_id = %s
                WHERE id = %s
                """,
                [item.sort_order, item.parent_id, item.id],
            )
        conn.commit()
        return {"updated": len(body.items)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


@router.patch("/internal/{account_id}")
def update_internal_account(
    account_id: int,
    body: InternalAccountUpdate,
    conn: PgConnection = Depends(get_db),
):
    # Build dynamic SET clause from provided fields only
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = []
    params = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = %s")
        params.append(value)
    params.append(account_id)

    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE internal_accounts
            SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, entity_id, code, name, standard_account_id,
                      parent_id, sort_order, is_active, is_recurring
            """,
            params,
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail="Internal account not found")
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, result))
        conn.commit()
        return row
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


@router.delete("/internal/{account_id}")
def delete_internal_account(
    account_id: int,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        # Check for referencing transactions
        cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE internal_account_id = %s",
            [account_id],
        )
        tx_count = cur.fetchone()[0]

        # Soft-delete + unlink transactions
        cur.execute(
            """
            UPDATE internal_accounts SET is_active = false
            WHERE id = %s AND is_active = true
            RETURNING id
            """,
            [account_id],
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Internal account not found or already deleted",
            )

        # 연결된 거래를 미분류로 되돌림
        if tx_count > 0:
            cur.execute(
                "UPDATE transactions SET internal_account_id = NULL WHERE internal_account_id = %s",
                [account_id],
            )

        conn.commit()

        response = {"id": account_id, "deleted": True}
        if tx_count > 0:
            response["unlinked_transactions"] = tx_count
        return response
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Members — CRUD
# ---------------------------------------------------------------------------

@router.get("/members")
def list_members(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    if entity_id is not None:
        cur.execute(
            """SELECT m.id, m.entity_id, m.name, m.role, m.card_numbers, m.slack_user_id,
                      (SELECT COUNT(*) FROM transactions t WHERE t.member_id = m.id) AS tx_count
               FROM members m WHERE m.entity_id = %s AND m.is_active = true ORDER BY m.name""",
            [entity_id],
        )
    else:
        cur.execute(
            """SELECT m.id, m.entity_id, m.name, m.role, m.card_numbers, m.slack_user_id,
                      (SELECT COUNT(*) FROM transactions t WHERE t.member_id = m.id) AS tx_count
               FROM members m WHERE m.is_active = true ORDER BY m.entity_id, m.name"""
        )
    rows = fetch_all(cur)
    cur.close()
    return rows


@router.post("/members", status_code=201)
def create_member(
    body: MemberCreate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        normalized_cards = _normalize_card_list(body.card_numbers) or []
        cur.execute(
            """
            INSERT INTO members (entity_id, name, role, card_numbers, slack_user_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, entity_id, name, role, is_active, card_numbers, slack_user_id
            """,
            [body.entity_id, body.name, body.role, normalized_cards, body.slack_user_id],
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        new_member_id = row["id"]

        # 카드번호 기반 자동 relink (exact + 뒤 3자리 fallback) — PATCH와 동일 정책
        relinked = 0
        if normalized_cards:
            placeholders = ",".join(["%s"] * len(normalized_cards))
            cur.execute(
                f"""UPDATE transactions SET member_id = %s
                    WHERE entity_id = %s AND card_number IN ({placeholders})
                      AND member_id IS NULL""",
                [new_member_id, body.entity_id] + normalized_cards,
            )
            relinked += cur.rowcount
            tails = list({c[-3:] for c in normalized_cards if c and len(c) >= 3})
            if tails:
                tail_ph = ",".join(["%s"] * len(tails))
                cur.execute(
                    f"""UPDATE transactions SET member_id = %s
                        WHERE entity_id = %s AND member_id IS NULL
                          AND card_number IS NOT NULL AND LENGTH(card_number) >= 3
                          AND RIGHT(card_number, 3) IN ({tail_ph})""",
                    [new_member_id, body.entity_id] + tails,
                )
                relinked += cur.rowcount
        row["relinked_transactions"] = relinked
        conn.commit()
        return row
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


@router.patch("/members/{member_id}")
def update_member(
    member_id: int,
    body: MemberUpdate,
    conn: PgConnection = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # 카드번호 정규화 (****XXXX)
    if "card_numbers" in updates:
        updates["card_numbers"] = _normalize_card_list(updates["card_numbers"])

    set_clauses = []
    params = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = %s")
        params.append(value)
    params.append(member_id)

    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE members
            SET {', '.join(set_clauses)}
            WHERE id = %s AND is_active = true
            RETURNING id, entity_id, name, role, is_active, card_numbers, slack_user_id
            """,
            params,
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail="Member not found")
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, result))

        # 멤버 변경 시 카드번호/이름 기반으로 기존 거래 재연결
        entity_id = row["entity_id"]
        card_numbers = row.get("card_numbers") or []
        member_name = row["name"]
        relinked = 0
        # 카드번호로 미연결 거래 연결 — exact + 뒤 3자리 fallback
        if card_numbers:
            placeholders = ",".join(["%s"] * len(card_numbers))
            cur.execute(
                f"""UPDATE transactions SET member_id = %s
                    WHERE entity_id = %s AND card_number IN ({placeholders})
                      AND (member_id IS NULL OR member_id != %s)""",
                [member_id, entity_id] + card_numbers + [member_id],
            )
            relinked += cur.rowcount
            # 뒤 3자리 기반 fallback (Codef는 '5105*********477' 포맷)
            # members.card_numbers 는 '****XXXX' 로 정규화되어 있으므로
            # 뒤 3자리끼리 비교.
            tails = list({c[-3:] for c in card_numbers if c and len(c) >= 3})
            if tails:
                tail_placeholders = ",".join(["%s"] * len(tails))
                cur.execute(
                    f"""UPDATE transactions SET member_id = %s
                        WHERE entity_id = %s
                          AND member_id IS NULL
                          AND card_number IS NOT NULL
                          AND LENGTH(card_number) >= 3
                          AND RIGHT(card_number, 3) IN ({tail_placeholders})""",
                    [member_id, entity_id] + tails,
                )
                relinked += cur.rowcount
        # parsed_member_name으로 미연결 거래 연결
        cur.execute(
            """UPDATE transactions SET member_id = %s
               WHERE entity_id = %s AND parsed_member_name = %s
                 AND (member_id IS NULL OR member_id != %s)""",
            [member_id, entity_id, member_name, member_id],
        )
        relinked += cur.rowcount

        conn.commit()
        row["relinked_transactions"] = relinked
        return row
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


@router.delete("/members/{member_id}")
def delete_member(
    member_id: int,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    try:
        # Check for referencing transactions
        cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE member_id = %s",
            [member_id],
        )
        tx_count = cur.fetchone()[0]

        cur.execute(
            """
            UPDATE members SET is_active = false
            WHERE id = %s AND is_active = true
            RETURNING id
            """,
            [member_id],
        )
        result = cur.fetchone()
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Member not found or already deleted",
            )
        conn.commit()

        response = {"id": member_id, "deleted": True}
        if tx_count > 0:
            response["warning"] = (
                f"{tx_count} transaction(s) reference this member. "
                "They retain the reference but this member is now inactive."
            )
        return response
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# 미매칭 카드 — 멤버 관리 UI 지원 엔드포인트
# ---------------------------------------------------------------------------

CARD_SOURCE_TYPES = (
    "lotte_card", "codef_lotte_card",
    "woori_card", "codef_woori_card",
    "shinhan_card", "codef_shinhan_card",
    "bc_card", "samsung_card", "hyundai_card",
    "nh_card", "kb_card", "hana_card",
)

_SOURCE_LABELS = {
    "lotte_card": "롯데카드", "codef_lotte_card": "롯데카드(Codef)",
    "woori_card": "우리카드", "codef_woori_card": "우리카드(Codef)",
    "shinhan_card": "신한카드", "codef_shinhan_card": "신한카드(Codef)",
    "bc_card": "BC카드", "samsung_card": "삼성카드", "hyundai_card": "현대카드",
    "nh_card": "NH카드", "kb_card": "KB국민카드", "hana_card": "하나카드",
}


@router.get("/members/unmatched-cards")
def list_unmatched_cards(
    entity_id: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """멤버 미배정 카드 목록 — 멤버 관리 UI용.

    같은 (card_number, source_type)에 해당하는 transactions 중 member_id가
    NULL인 건을 그룹핑. tx_count + 최근 거래 날짜 반환.
    """
    cur = conn.cursor()
    try:
        placeholders = ",".join(["%s"] * len(CARD_SOURCE_TYPES))
        cur.execute(
            f"""
            SELECT source_type, card_number, COUNT(*) AS tx_count,
                   MIN(date) AS first_date, MAX(date) AS last_date,
                   COALESCE(SUM(CASE WHEN type='out' AND NOT is_cancel THEN amount
                                     WHEN type='in'  AND is_cancel THEN -amount
                                     ELSE 0 END), 0) AS net_amount
            FROM transactions
            WHERE entity_id = %s
              AND member_id IS NULL
              AND card_number IS NOT NULL
              AND source_type IN ({placeholders})
            GROUP BY source_type, card_number
            ORDER BY tx_count DESC, source_type, card_number
            """,
            [entity_id, *CARD_SOURCE_TYPES],
        )
        rows = cur.fetchall()
        return {
            "cards": [
                {
                    "source_type": r[0],
                    "source_label": _SOURCE_LABELS.get(r[0], r[0]),
                    "card_number": r[1],
                    "tx_count": r[2],
                    "first_date": r[3].isoformat() if r[3] else None,
                    "last_date": r[4].isoformat() if r[4] else None,
                    "net_amount": float(r[5] or 0),
                }
                for r in rows
            ]
        }
    finally:
        cur.close()


class AssignCardBody(BaseModel):
    card_number: str


@router.post("/members/{member_id}/assign-card")
def assign_card_to_member(
    member_id: int,
    body: AssignCardBody,
    conn: PgConnection = Depends(get_db),
):
    """카드번호를 특정 멤버에게 배정.

    - 카드번호를 '****XXXX' 포맷으로 정규화해 member.card_numbers에 append
      (중복 시 skip)
    - 해당 card_number의 미연결 transactions (exact + 뒤 3자리 fallback)의
      member_id를 업데이트
    """
    cur = conn.cursor()
    try:
        normalized = _normalize_card_number(body.card_number)
        if not normalized:
            raise HTTPException(400, "invalid card_number")

        # 멤버 정보 + 기존 카드 조회
        cur.execute(
            "SELECT entity_id, name, card_numbers FROM members WHERE id = %s AND is_active = true",
            [member_id],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "member not found or inactive")
        entity_id, name, existing_cards = row
        existing_cards = existing_cards or []

        # append (중복 아닐 때만)
        if normalized not in existing_cards:
            new_cards = list(existing_cards) + [normalized]
            cur.execute(
                "UPDATE members SET card_numbers = %s WHERE id = %s",
                [new_cards, member_id],
            )
        else:
            new_cards = existing_cards

        # transactions relink: exact + 뒤 3자리 fallback
        tail3 = normalized[-3:] if len(normalized) >= 3 else None
        cur.execute(
            """
            UPDATE transactions
            SET member_id = %s
            WHERE entity_id = %s
              AND member_id IS NULL
              AND card_number IS NOT NULL
              AND (
                card_number = %s
                OR (LENGTH(card_number) >= 3 AND RIGHT(card_number, 3) = %s)
              )
            """,
            [member_id, entity_id, normalized, tail3 or ""],
        )
        relinked = cur.rowcount
        conn.commit()
        return {
            "ok": True,
            "member_id": member_id,
            "member_name": name,
            "card_number": normalized,
            "relinked_transactions": relinked,
            "card_numbers": new_cards,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Mapping rules — CRUD
# ---------------------------------------------------------------------------

@router.get("/mapping-rules")
def list_mapping_rules(
    entity_id: int,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    where = ["mr.entity_id = %s"]
    params: list = [entity_id]

    if search:
        where.append("mr.counterparty_pattern ILIKE %s")
        params.append(f"%{search}%")

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(f"SELECT COUNT(*) FROM mapping_rules mr WHERE {where_clause}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT mr.id, mr.counterparty_pattern,
               mr.internal_account_id, ia.name AS internal_account_name, ia.code AS internal_account_code,
               mr.standard_account_id, sa.name AS standard_account_name, sa.code AS standard_account_code,
               mr.confidence, mr.hit_count, mr.updated_at
        FROM mapping_rules mr
        LEFT JOIN internal_accounts ia ON mr.internal_account_id = ia.id
        LEFT JOIN standard_accounts sa ON mr.standard_account_id = sa.id
        WHERE {where_clause}
        ORDER BY mr.hit_count DESC, mr.updated_at DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    return {"items": rows, "total": total, "page": page, "per_page": per_page}


@router.patch("/mapping-rules/{rule_id}")
def update_mapping_rule(
    rule_id: int,
    body: MappingRuleUpdate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    if body.internal_account_id is not None:
        cur.execute("SELECT standard_account_id FROM internal_accounts WHERE id = %s", [body.internal_account_id])
        std_row = cur.fetchone()
        std_id = std_row[0] if std_row else None

        cur.execute(
            """
            UPDATE mapping_rules
            SET internal_account_id = %s, standard_account_id = %s, updated_at = NOW()
            WHERE id = %s RETURNING id
            """,
            [body.internal_account_id, std_id, rule_id],
        )
    else:
        raise HTTPException(400, "No fields to update")

    if not cur.fetchone():
        raise HTTPException(404, "Mapping rule not found")

    conn.commit()
    cur.close()
    return {"id": rule_id, "updated": True}


@router.delete("/mapping-rules/{rule_id}")
def delete_mapping_rule(
    rule_id: int,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    cur.execute("DELETE FROM mapping_rules WHERE id = %s RETURNING id", [rule_id])
    if not cur.fetchone():
        raise HTTPException(404, "Mapping rule not found")
    conn.commit()
    cur.close()
    return {"id": rule_id, "deleted": True}

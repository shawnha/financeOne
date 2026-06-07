# 계정 트리 재설계 마이그레이션 사전점검 — 읽기전용 DB 스냅샷 (쓰기 차단, 분석만)
"""
적대적 리뷰 2건이 공통 요구한 "사실 기반 사전점검표"를 실측한다. SELECT only.
  - 표준 중복명칭 그룹 + 코드별 FK 참조수(동적 FK 발견)
  - gaap_mapping 커버리지 공백 (생존코드 0행 / 폐기후보가 매핑 보유)
  - 25300(선수금) 실제 booking triage
  - 법인별 drift (transactions.std ≠ internal.std)
  - 법인별 GL 유무 + journal_entry_lines.std 2차 drift + 마감장치 유무
  - internal standard NULL 개수

실행: .venv/bin/python3 scripts/account_tree_preflight.py
DB는 read-only 세션으로 강제 — 어떤 write도 거부됨.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DSN = os.environ.get("DATABASE_URL")
if not DSN:
    print("DATABASE_URL 미설정")
    sys.exit(1)


def hr(title):
    print("\n" + "=" * 78)
    print(f"## {title}")
    print("=" * 78)


def main():
    conn = psycopg2.connect(DSN)
    conn.set_session(readonly=True, autocommit=True)  # ★ 쓰기 차단
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SET search_path TO financeone, public")

    # entity 이름
    cur.execute("SELECT id, name FROM entities ORDER BY id")
    ent = {r["id"]: r["name"] for r in cur.fetchall()}

    # ── 표준 참조 FK 동적 발견 ──
    cur.execute(
        """
        SELECT tc.table_name AS child_table, kcu.column_name AS child_col
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'financeone'
          AND ccu.table_name = 'standard_accounts' AND ccu.column_name = 'id'
        ORDER BY tc.table_name
        """
    )
    fk_children = [(r["child_table"], r["child_col"]) for r in cur.fetchall()]

    hr("표준계정 참조 FK 테이블 (동적 발견)")
    for t, c in fk_children:
        print(f"  - {t}.{c}")

    # 코드별 FK 참조수 맵: counts[std_id][child_table] = n
    counts = defaultdict(lambda: defaultdict(int))
    for t, c in fk_children:
        cur.execute(f"SELECT {c} AS sid, count(*) AS n FROM {t} WHERE {c} IS NOT NULL GROUP BY {c}")
        for r in cur.fetchall():
            counts[r["sid"]][t] = r["n"]

    # 표준계정 전체
    cur.execute(
        "SELECT id, code, name, category, subcategory, is_active FROM standard_accounts ORDER BY name, code"
    )
    sa = cur.fetchall()
    by_id = {r["id"]: r for r in sa}

    child_labels = [t for t, _ in fk_children]

    def refrow(sid):
        d = counts.get(sid, {})
        tot = sum(d.values())
        cells = " ".join(f"{lbl[:10]}={d.get(lbl,0)}" for lbl in child_labels if d.get(lbl, 0))
        return tot, cells

    # ── 1. 중복 명칭 그룹 ──
    hr("1. 표준 중복 명칭 그룹 + 코드별 FK 참조수 (canonical 후보 = 참조 많은 활성코드)")
    groups = defaultdict(list)
    for r in sa:
        groups[r["name"]].append(r)
    dup = {n: rows for n, rows in groups.items() if len(rows) > 1}
    print(f"중복 명칭 그룹 수: {len(dup)}  (총 코드 {sum(len(v) for v in dup.values())})\n")
    for name in sorted(dup):
        rows = dup[name]
        print(f"● {name}")
        for r in sorted(rows, key=lambda x: x["code"]):
            tot, cells = refrow(r["id"])
            act = "활성" if r["is_active"] else "비활성"
            print(f"    {r['code']:<8} id={r['id']:<4} [{act}] 참조{tot:<5} {cells}")

    # ── 2. gaap_mapping 커버리지 공백 ──
    hr("2. gaap_mapping 커버리지 — 중복그룹 내 매핑 보유 코드 (일원화 시 이관 필요)")
    for name in sorted(dup):
        rows = dup[name]
        gaps = [(r, counts[r["id"]].get("gaap_mapping", 0)) for r in rows]
        holders = [(r, g) for r, g in gaps if g > 0]
        if holders:
            print(f"● {name}")
            for r, g in sorted(gaps, key=lambda x: x[0]["code"]):
                used = sum(counts[r["id"]].values()) - g
                flag = " ◀ 매핑보유(폐기 시 이관)" if g > 0 else (" ← 생존후보(gaap=0!)" if used > 0 else "")
                print(f"    {r['code']:<8} gaap={g}  타참조={used}{flag}")

    # 생존(활성·고참조)인데 gaap=0
    hr("2b. 활성 표준 중 거래는 있는데 gaap_mapping 0행 (연결 누락 위험, 예: 81400 통신비)")
    miss = []
    for r in sa:
        if not r["is_active"]:
            continue
        d = counts.get(r["id"], {})
        used = d.get("transactions", 0) + d.get("journal_entry_lines", 0) + d.get("invoices", 0)
        if used > 0 and d.get("gaap_mapping", 0) == 0:
            miss.append((r, used))
    for r, used in sorted(miss, key=lambda x: -x[1])[:40]:
        print(f"    {r['code']:<8} {r['name']:<16} 사용={used}  gaap=0")
    print(f"  … 총 {len(miss)}개 활성·사용·gaap0 코드")

    # ── 3. 25300 등 triage ──
    hr("3. 25300(선수금) + 인접코드 triage")
    cur.execute(
        "SELECT id, code, name, category, subcategory, is_active FROM standard_accounts "
        "WHERE code IN ('25300','25200','25900','20700','26200','26000') ORDER BY code"
    )
    for r in cur.fetchall():
        tot, cells = refrow(r["id"])
        print(f"  {r['code']} {r['name']:<12} id={r['id']} cat={r['category']}/{r['subcategory']} "
              f"활성={r['is_active']} 참조{tot} {cells}")
    # 25300 거래 상세 (선수금 vs 미지급금 판별용)
    print("\n  ▸ 25300 직접 거래 (entity·방향·거래처·금액):")
    cur.execute(
        """
        SELECT t.entity_id AS e, t.type, t.counterparty AS cp, left(t.description,32) AS d,
               t.amount, t.date
        FROM transactions t JOIN standard_accounts s ON s.id = t.standard_account_id
        WHERE s.code = '25300' ORDER BY t.date
        """
    )
    rows = cur.fetchall()
    for r in rows:
        print(f"    e{r['e']} {r['date']} {r['type']:<8} {str(r['cp'])[:16]:<16} {r['amount']:>15,.0f}  {r['d']}")
    print(f"    (거래 {len(rows)}건)")
    # 25300 invoices 상세
    try:
        cur.execute(
            """
            SELECT i.entity_id AS e, i.direction, i.counterparty AS cp, i.total, i.issue_date
            FROM invoices i JOIN standard_accounts s ON s.id = i.standard_account_id
            WHERE s.code = '25300' ORDER BY i.issue_date
            """
        )
        irows = cur.fetchall()
        print(f"\n  ▸ 25300 invoices: {len(irows)}건")
        for r in irows:
            print(f"    e{r['e']} {r.get('issue_date')} {r.get('direction')} {str(r.get('cp'))[:16]:<16} {r.get('total')}")
    except Exception as ex:
        conn.rollback() if not conn.autocommit else None
        print(f"  ▸ invoices 조회 스킵: {ex}")

    # ── 4. drift per entity ──
    hr("4. 법인별 drift — transactions.std ≠ internal(매핑).std")
    cur.execute(
        """
        SELECT t.entity_id AS e, count(*) AS drift
        FROM transactions t JOIN internal_accounts ia ON ia.id = t.internal_account_id
        WHERE t.standard_account_id IS NOT NULL AND ia.standard_account_id IS NOT NULL
          AND t.standard_account_id <> ia.standard_account_id
        GROUP BY t.entity_id ORDER BY t.entity_id
        """
    )
    for r in cur.fetchall():
        print(f"    e{r['e']} {ent.get(r['e'],'?'):<16} drift={r['drift']}")

    # ── 5. GL 유무 + 2차 drift + 마감장치 ──
    hr("5. 법인별 GL(journal_entries) 유무 + std 2차 drift")
    cur.execute(
        """
        SELECT t.entity_id AS e, count(*) AS tx_total,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM journal_entries je WHERE je.transaction_id=t.id)) AS tx_gl
        FROM transactions t GROUP BY t.entity_id ORDER BY t.entity_id
        """
    )
    glmap = {r["e"]: r for r in cur.fetchall()}
    cur.execute(
        """
        SELECT t.entity_id AS e,
          count(*) AS tx_gl_std,
          count(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM journal_entries je2 JOIN journal_entry_lines jl ON jl.journal_entry_id=je2.id
            WHERE je2.transaction_id=t.id AND jl.standard_account_id=t.standard_account_id)) AS matched
        FROM transactions t
        WHERE t.standard_account_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM journal_entries je WHERE je.transaction_id=t.id)
        GROUP BY t.entity_id ORDER BY t.entity_id
        """
    )
    dmap = {r["e"]: r for r in cur.fetchall()}
    for e in sorted(set(glmap) | set(dmap)):
        g = glmap.get(e, {})
        d = dmap.get(e, {})
        tot = g.get("tx_total", 0)
        gl = g.get("tx_gl", 0)
        std = d.get("tx_gl_std", 0)
        m = d.get("matched", 0)
        print(f"    e{e} {ent.get(e,'?'):<16} 거래={tot:<6} GL있음={gl:<6} "
              f"(GL+std {std} 중 std일치 {m})")
    cur.execute("SELECT entity_id AS e, count(*) FILTER (WHERE is_closing) AS clo, "
                "count(*) FILTER (WHERE is_adjusting) AS adj, count(*) AS je FROM journal_entries GROUP BY entity_id ORDER BY entity_id")
    print("\n  ▸ 마감/조정 분개:")
    for r in cur.fetchall():
        print(f"    e{r['e']} {ent.get(r['e'],'?'):<16} 분개={r['je']:<6} 마감(is_closing)={r['clo']} 조정(is_adjusting)={r['adj']}")
    # 잠금/기간 테이블 존재 여부
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='financeone' "
        "AND (table_name ILIKE '%period%' OR table_name ILIKE '%lock%' OR table_name ILIKE '%close%' OR table_name ILIKE '%fiscal%')"
    )
    lk = [r["table_name"] for r in cur.fetchall()]
    print(f"\n  ▸ 기간잠금/마감 테이블: {lk if lk else '없음 (마감잠금 장치 부재)'}")

    # ── 6. internal NULL std ──
    hr("6. 법인별 internal_accounts standard 매핑 NULL")
    cur.execute(
        """
        SELECT entity_id AS e, count(*) AS total,
          count(*) FILTER (WHERE standard_account_id IS NULL) AS null_std,
          count(*) FILTER (WHERE is_active) AS active
        FROM internal_accounts GROUP BY entity_id ORDER BY entity_id
        """
    )
    for r in cur.fetchall():
        print(f"    e{r['e']} {ent.get(r['e'],'?'):<16} 내부계정={r['total']:<5} 활성={r['active']:<5} std_NULL={r['null_std']}")

    cur.close()
    conn.close()
    print("\n[완료] 읽기전용 — DB 무변경.")


if __name__ == "__main__":
    main()

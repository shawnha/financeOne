# 프로덕션 CODEF가 기존(데모) 데이터와 동일하게 불러오는지 DB에 쓰지 않고 대조하는 읽기전용 검증 스크립트
#
# 사용: 프로덕션 connectedId 등록 후 실행.
#   source .venv/bin/activate
#   CODEF_PROD_CLIENT_ID=... CODEF_PROD_CLIENT_SECRET=... \
#     python3 scripts/codef_prod_reconcile.py --mode card --entity 2 --org lotte_card \
#       --start 2026-05-01 --end 2026-05-30
#
# 동작:
#   1) 프로덕션 키 + production connectedId 로 라이브 fetch (get_card_approvals / get_bank_transactions)
#   2) 같은 (entity, source_type, 기간) 의 DB 행(데모로 받아둔 것) 조회
#   3) (date, amount) 멀티셋으로 대조 → 일치/누락/초과 리포트
#   DB INSERT/UPDATE 전혀 없음.

import argparse
import os
import sys
from collections import Counter
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()  # CODEF_PROD_* 를 main() 의 env 체크 전에 로드

from backend.services.integrations.codef import (  # noqa: E402
    CodefClient,
    resolve_base_url,
    _connected_id_key,
    _codef_account_key,
)


def _db():
    load_dotenv()
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    return conn, cur


def _get_setting(cur, key, entity_id):
    cur.execute(
        "SELECT value FROM settings WHERE key = %s AND (entity_id = %s OR entity_id IS NULL) "
        "ORDER BY entity_id NULLS LAST LIMIT 1",
        (key, entity_id),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _norm_amount(v) -> Decimal:
    try:
        return Decimal(str(v)).quantize(Decimal("1"))
    except Exception:
        return Decimal(0)


def fetch_prod_card(client, connected_id, org, entity_id, start, end, cur):
    # 카드번호 = DB transactions.card_number distinct (path B 자동도출)
    cur.execute(
        "SELECT DISTINCT card_number FROM transactions "
        "WHERE entity_id = %s AND source_type = %s AND card_number IS NOT NULL AND card_number <> ''",
        (entity_id, f"codef_{org}"),
    )
    cards = [r[0] for r in cur.fetchall()]
    if not cards:
        print(f"  [warn] DB에 {org} 카드번호 없음 — card-list 자동선택으로 fallback")
        cards = [None]
    print(f"  대상 카드 {len([c for c in cards if c])}장: {[c for c in cards if c]}")
    rows = []
    for cno in cards:
        appr = client.get_card_approvals(
            connected_id, start.replace("-", ""), end.replace("-", ""),
            card_type=org, card_no=cno,
        )
        for a in appr:
            d = (a.get("resUsedDate") or a.get("resPaymentDate") or "")[:8]
            amt = a.get("resUsedAmount") or a.get("resTotalAmount") or 0
            rows.append((f"{d[:4]}-{d[4:6]}-{d[6:8]}", _norm_amount(amt)))
    return rows


def fetch_prod_bank(client, connected_id, org, entity_id, start, end, cur):
    account = _get_setting(cur, _codef_account_key("production", org), entity_id)
    if not account:
        print(f"  [error] 은행 계좌번호 설정 없음 ({_codef_account_key('production', org)}). "
              f"먼저 /codef/account-numbers 로 입력 필요.")
        sys.exit(2)
    print(f"  대상 계좌: {account}")
    tr = client.get_bank_transactions(
        connected_id, start.replace("-", ""), end.replace("-", ""),
        account=account, org=org,
    )
    rows = []
    for t in tr:
        d = (t.get("resAccountTrDate") or "")[:8]
        out_amt = _norm_amount(t.get("resAccountOut") or 0)
        in_amt = _norm_amount(t.get("resAccountIn") or 0)
        amt = out_amt if out_amt else in_amt
        rows.append((f"{d[:4]}-{d[4:6]}-{d[6:8]}", amt))
    return rows


def fetch_db(cur, org, entity_id, start, end):
    cur.execute(
        "SELECT date, amount FROM transactions "
        "WHERE entity_id = %s AND source_type = %s AND date BETWEEN %s AND %s",
        (entity_id, f"codef_{org}", start, end),
    )
    return [(str(r[0]), _norm_amount(r[1])) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["card", "bank"], required=True)
    ap.add_argument("--entity", type=int, required=True)
    ap.add_argument("--org", required=True)
    ap.add_argument("--start", required=True)  # YYYY-MM-DD
    ap.add_argument("--end", required=True)
    args = ap.parse_args()

    cid = os.environ.get("CODEF_PROD_CLIENT_ID")
    sec = os.environ.get("CODEF_PROD_CLIENT_SECRET")
    if not cid or not sec:
        print("CODEF_PROD_CLIENT_ID / CODEF_PROD_CLIENT_SECRET 환경변수 필요")
        sys.exit(2)

    conn, cur = _db()
    connected_id = _get_setting(cur, _connected_id_key("production", args.org), args.entity)
    if not connected_id:
        print(f"[error] production connectedId 없음 ({_connected_id_key('production', args.org)}). "
              f"설정 화면에서 먼저 등록하세요.")
        sys.exit(2)
    print(f"connectedId(production/{args.org}): {connected_id}")

    client = CodefClient(cid, sec, base_url=resolve_base_url("production"))
    print(f"base_url: {client.base_url}")

    if args.mode == "card":
        prod = fetch_prod_card(client, connected_id, args.org, args.entity, args.start, args.end, cur)
    else:
        prod = fetch_prod_bank(client, connected_id, args.org, args.entity, args.start, args.end, cur)

    db = fetch_db(cur, args.org, args.entity, args.start, args.end)
    conn.close()

    pc, dc = Counter(prod), Counter(db)
    matched = sum((pc & dc).values())
    only_prod = pc - dc
    only_db = dc - pc

    print("\n================ 대조 결과 ================")
    print(f"  프로덕션 fetch: {len(prod)}건")
    print(f"  DB(데모 저장): {len(db)}건")
    print(f"  일치: {matched}건")
    print(f"  프로덕션에만 있음(DB 누락): {sum(only_prod.values())}건")
    print(f"  DB에만 있음(프로덕션 누락): {sum(only_db.values())}건")
    if only_prod:
        print("  --- 프로덕션에만 (상위 10) ---")
        for k, n in list(only_prod.items())[:10]:
            print(f"    {k} x{n}")
    if only_db:
        print("  --- DB에만 (상위 10) ---")
        for k, n in list(only_db.items())[:10]:
            print(f"    {k} x{n}")
    verdict = "✅ 동일하게 불러옴 — 전환 안전" if not only_prod and not only_db else "⚠️ 차이 있음 — 원인 확인 필요"
    print(f"\n  판정: {verdict}")


if __name__ == "__main__":
    main()

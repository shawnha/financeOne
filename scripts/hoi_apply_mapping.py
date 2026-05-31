# HOI(entity=1) 미분류 Mercury 거래를 cross-check 검증된 내부계정+US GAAP 표준계정으로 매핑하는 1회성 스크립트
"""HOI 거래 매핑 적용 (2026-05-31, 옵션 B = 전체 US-GAAP 일관).

cross-check 근거: QBO qbo_transaction_lines.account_name(US GAAP 정본) + HOI 2025 P&L PDF
+ Finance/cgetc 인보이스 + 웹검증. 상세: 메모리 project_hoi_mapping_dryrun_resume.

동작 3가지 (단일 트랜잭션, --apply 없으면 전부 dry-run/rollback):
1. 12개 내부계정 → US GAAP 표준계정(HOI-PL-*) 연결.
   - 7개는 NULL→연결, 5개(통신·광고·구독·수수료·기타수입)는 기존 K_GAAP→US GAAP relink.
   - 사장님 결정: HOI 표준계정 = QBO/US GAAP 기준.
2. 102건 거래 → internal_account_id + standard_account_id (내부계정 경유).
3. mapping_rules 학습 — 정규 vendor 12개만 (재발 안 하는 Amazon 거래별 suffix·케이스 중복 제외).

보류(매핑 안 함, 8건): Hanah One Korea $130K(매입vs차입금, 2026 HOK원장 확인 대기),
NEST GRID $16K(정체불명), CA DEPT TAX $213(sales tax 처리 불명), Mercury Credit/IO AUTOPAY $559(카드대금 검토).

사용: python3 scripts/hoi_apply_mapping.py          # dry-run (rollback)
      python3 scripts/hoi_apply_mapping.py --apply  # 실제 commit
"""
import os
import sys

# 프로젝트 루트를 import path 에 추가 (scripts/ 하위에서 backend 모듈 접근)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import psycopg2

from backend.services.mapping_service import learn_mapping_rule

APPLY = "--apply" in sys.argv

# ── 내부계정 → US GAAP 표준계정 연결 (12개) ──
# (internal_account_id, standard_account US_GAAP code, 근거). relink=기존 K_GAAP 덮어씀.
IA_STD_LINKS = [
    (886, "HOI-PL-4022", "Shopify → Shopify Sales"),
    (896, "HOI-PL-4024", "TikTok → Tiktok Sales"),
    (903, "HOI-PL-4021", "Amazon → Amazon Sales"),
    (884, "HOI-PL-6070", "3PL → Selling Expense-3PL (CGETC)"),
    (876, "HOI-PL-6051", "임차료 → Office Rent-Beverly Hills (Industrious)"),
    (889, "HOI-PL-6010", "회계법인 → Legal & Professional (Kim&Co)"),
    (897, "HOI-PL-6010", "법률서비스 → Legal & Professional (Venturous)"),
    # relink (기존 K_GAAP → US GAAP)
    (317, "HOI-PL-6015", "통신비 → Telephone Expense (relink)"),
    (327, "HOI-PL-6080", "광고비 → Selling Expense-Advertising (relink)"),
    (335, "HOI-PL-6030", "기타구독 → Dues & Subscription (relink)"),
    (336, "HOI-PL-6100", "수수료 → Selling Expense-Merchant Fees (relink)"),
    (308, "HOI-PL-7010", "기타수입 → Other Income (relink)"),
    # 상위(부모) 계정 GAAP 일관화 — 거래 직접 안 붙음(0건), 트리 롤업 일관성용
    (304, "HOI-PL-4000", "수입(상위) → Income (relink, 트리 일관성)"),
    (305, "HOI-PL-4020", "매출(상위) → Channel Sales (relink, 트리 일관성)"),
    (309, "HOI-PL-6000", "지출(상위) → Expenses (relink, 트리 일관성)"),
]

# ── counterparty 매핑 규칙 (HOLD 우선, type 으로 in/out 구분) ──
RULES = [
    ("shopify",            "in",  886, "Shopify"),
    ("tiktok inc",         "in",  896, "TikTok"),
    ("amazon",             "in",  903, "Amazon"),
    ("mercury io cashback","in",  308, "기타수입"),
    ("mercury io",         "in",  308, "기타수입"),
    ("cgetc",              "out", 884, "3PL"),
    ("industrious",        "out", 876, "임차료"),
    ("t-mobile",           "out", 317, "통신비"),
    ("kim and co",         "out", 889, "회계법인"),
    ("kmco",               "out", 889, "회계법인"),
    ("venturous",          "out", 897, "법률서비스"),
    ("facebook",           "out", 327, "광고비"),
    ("google",             "out", 327, "광고비"),
    ("tiktok ads",         "out", 327, "광고비"),
    ("tiktok",             "out", 327, "광고비"),
    ("quickbooks",         "out", 335, "기타구독"),
    ("intuit",             "out", 335, "기타구독"),
    ("intl. wire fee",     "out", 336, "수수료"),
    ("shopify",            "out", 336, "수수료"),
]
# 보류 (매핑/학습 안 함) — RULES 보다 먼저 검사
HOLD = ["hanah one korea", "nest grid", "ca dept tax", "franchise tax", "mercury credit", "io autopay"]

# ── 학습할 정규 vendor 규칙 (재발하는 거래처만, 거래별 suffix·케이스 중복 제외) ──
# (counterparty_pattern, internal_account_id)
LEARN = [
    ("Shopify", 886), ("TikTok Inc", 896), ("Amazon", 903),
    ("CGETC, INC", 884), ("INDUSTRIOUS BH 1", 876), ("T-MOBILE", 317),
    ("KIM AND CO", 889), ("Venturous Counsel, A Professional Corporation", 897),
    ("Facebook", 327), ("Google", 327), ("QuickBooks", 335),
    ("Mercury IO Cashback", 308),
]


def load_dburl():
    for line in open(".env", encoding="utf-8"):
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("DATABASE_URL not found")


def match(cp, ttype):
    cl = (cp or "").lower()
    if any(h in cl for h in HOLD):
        return None
    for pat, tcon, tid, label in RULES:
        if pat in cl and (tcon is None or tcon == ttype):
            return tid, label
    return None


def main():
    conn = psycopg2.connect(load_dburl())
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public;")
    log = []

    # STEP 1: 내부계정 → 표준계정 연결/relink
    std_changed = 0
    for ia_id, std_code, note in IA_STD_LINKS:
        cur.execute("SELECT id FROM standard_accounts WHERE code=%s AND gaap_type='US_GAAP'", [std_code])
        row = cur.fetchone()
        if not row:
            log.append(f"  ⚠️ STD NOT FOUND: {std_code} ({note}) — skip")
            continue
        std_id = row[0]
        cur.execute("SELECT standard_account_id FROM internal_accounts WHERE id=%s", [ia_id])
        old = cur.fetchone()
        old_std = old[0] if old else None
        if old_std == std_id:
            continue  # 이미 동일
        cur.execute("UPDATE internal_accounts SET standard_account_id=%s WHERE id=%s", [std_id, ia_id])
        std_changed += 1
        log.append(f"  IA {ia_id}: std {old_std} → {std_id} ({std_code})  [{note}]")

    # STEP 2: 거래 매핑 (internal + standard 동시)
    cur.execute("""
        SELECT id, type, amount, COALESCE(counterparty,'')
        FROM transactions
        WHERE entity_id=1 AND internal_account_id IS NULL AND (is_cancel IS NOT TRUE)
        ORDER BY ABS(amount) DESC
    """)
    txns = cur.fetchall()

    from collections import Counter
    by_label = Counter()
    mapped = 0
    for tid, ttype, amount, cp in txns:
        m = match(cp, ttype)
        if not m:
            continue
        ia_id, label = m
        cur.execute("SELECT standard_account_id FROM internal_accounts WHERE id=%s", [ia_id])
        std_row = cur.fetchone()
        std_id = std_row[0] if std_row else None
        cur.execute(
            "UPDATE transactions SET internal_account_id=%s, standard_account_id=%s WHERE id=%s",
            [ia_id, std_id, tid],
        )
        mapped += 1
        by_label[label] += 1

    # STEP 2.5: 기존 매핑 거래의 standard_account_id 동기화.
    # STEP 1 에서 std 를 연결/relink 한 12개 계정을 쓰는 기존 HOI 거래는
    # transactions.standard_account_id 가 NULL 이거나 옛 K_GAAP 값을 들고 있어
    # internal↔standard 불일치. 내부계정의 (새) std 로 일괄 동기화.
    target_ia_ids = [ia_id for ia_id, _, _ in IA_STD_LINKS]
    cur.execute(
        """
        UPDATE transactions t
        SET standard_account_id = ia.standard_account_id
        FROM internal_accounts ia
        WHERE t.internal_account_id = ia.id
          AND t.entity_id = 1
          AND t.internal_account_id = ANY(%s)
          AND (t.is_cancel IS NOT TRUE)
          AND t.standard_account_id IS DISTINCT FROM ia.standard_account_id
        """,
        [target_ia_ids],
    )
    std_synced = cur.rowcount

    # STEP 3: mapping_rules 학습 (정규 vendor 만, UPSERT)
    for cp_pattern, ia_id in LEARN:
        learn_mapping_rule(cur, entity_id=1, counterparty=cp_pattern, internal_account_id=ia_id)

    # 검증
    cur.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE entity_id=1 AND internal_account_id IS NULL AND (is_cancel IS NOT TRUE)
    """)
    remaining = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE entity_id=1 AND internal_account_id IS NOT NULL AND standard_account_id IS NULL AND (is_cancel IS NOT TRUE)
    """)
    mapped_no_std = cur.fetchone()[0]

    print("="*70)
    print(f"HOI 매핑 적용 {'[APPLY]' if APPLY else '[DRY-RUN]'}")
    print("="*70)
    print(f"STEP 1 내부계정→US GAAP 표준계정 연결/relink: {std_changed}건")
    for l in log:
        print(l)
    print(f"\nSTEP 2 거래 매핑: {mapped}건")
    for label, n in by_label.most_common():
        print(f"    {label:<12} {n:>3}건")
    print(f"\nSTEP 2.5 기존 거래 표준계정 동기화: {std_synced}건 (relink 영향 기존 거래 + NULL backfill)")
    print(f"\nSTEP 3 mapping_rules 학습: {len(LEARN)}개 정규 vendor")
    print(f"\n검증:")
    print(f"  매핑 후 미분류 잔여 = {remaining}건 (보류 8건 예상: Hanah Korea 2 + NEST 1 + CA tax 2 + Mercury Credit 3)")
    print(f"  매핑됐으나 표준계정 NULL = {mapped_no_std}건 (0 이어야 정상)")

    ok = (remaining == 8 and mapped_no_std == 0 and mapped == 102)
    print(f"\n  {'✅ 검증 통과' if ok else '❌ 검증 실패 — 적용 중단 권장'} (mapped={mapped}, remaining={remaining}, no_std={mapped_no_std})")

    if APPLY and ok:
        conn.commit()
        print("\n✅ COMMITTED")
    elif APPLY and not ok:
        conn.rollback()
        print("\n❌ 검증 실패로 ROLLBACK (commit 안 함)")
    else:
        conn.rollback()
        print("\n↩️  ROLLED BACK (dry-run). 실제 적용: --apply")
    conn.close()


if __name__ == "__main__":
    main()

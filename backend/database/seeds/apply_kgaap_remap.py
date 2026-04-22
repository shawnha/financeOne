"""기존 internal_accounts.standard_account_id를 새 K-GAAP 상세 코드로 재매핑
+ transactions.standard_account_id를 internal_account로부터 재계산.

매핑 표는 docs/kgaap-accounts-migration-plan.html 섹션 2 참조.

주의: internal_accounts의 이름·트리·is_confirmed 거래는 절대 건드리지 않음.
standard_account_id 외래키만 교체.
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
load_dotenv()

# 기존 standard_code → 새 K-GAAP 상세 code
REMAP = {
    "50200": "80200",   # 급여 → 직원급여
    "50400": "81100",   # 복리후생비 → 복리후생비
    "50500": "81900",   # 임차료 → 지급임차료
    "50600": "81300",   # 접대비 → 접대비(기업업무추진비)
    "50700": "82800",   # 통신비 → 통신비
    "50800": "84000",   # 수도광열비 → 수도광열비
    "50900": "81700",   # 세금과공과 → 세금과공과금
    "51300": "81200",   # 여비교통비 → 여비교통비
    "51400": "83000",   # 소모품비 → 소모품비
    "51500": "83100",   # 지급수수료 → 지급수수료
    "51510": "83100",   # SaaS 구독료 → 지급수수료 (내부계정에서 세분)
    "51520": "83100",   # 결제수수료 → 지급수수료
    "51530": "83100",   # 배달플랫폼수수료 → 지급수수료
    "51600": "83300",   # 광고선전비 → 광고선전비
    "40300": "90100",   # 이자수익 → 이자수익
    "40600": "93000",   # 잡이익 → 잡이익
    "52300": "96000",   # 잡손실 → 잡손실
    "50300": "80500",   # 퇴직급여 → 퇴직급여 (표준 보완 코드)
}


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # 1. old_code → old_id, new_code → new_id 해석
    cur.execute("SELECT code, id FROM standard_accounts")
    code_to_id = {r[0]: r[1] for r in cur.fetchall()}

    remap_ids: dict[int, int] = {}
    for old_code, new_code in REMAP.items():
        old_id = code_to_id.get(old_code)
        new_id = code_to_id.get(new_code)
        if not old_id or not new_id:
            print(f"⚠ skip {old_code}→{new_code}: id 없음 (old={old_id} new={new_id})")
            continue
        remap_ids[old_id] = new_id

    print(f"재매핑 대상: {len(remap_ids)}건")

    # 2. internal_accounts 업데이트
    ia_total = 0
    for old_id, new_id in remap_ids.items():
        cur.execute(
            "UPDATE internal_accounts SET standard_account_id = %s WHERE standard_account_id = %s RETURNING id",
            [new_id, old_id],
        )
        ia_total += cur.rowcount
    print(f"✓ internal_accounts 업데이트: {ia_total}건")

    # 3. transactions 재계산 — internal_account_id로부터 파생
    #    internal_account_id가 NULL이 아니면, ia.standard_account_id로 교체
    cur.execute(
        """
        UPDATE transactions t
        SET standard_account_id = ia.standard_account_id,
            updated_at = NOW()
        FROM internal_accounts ia
        WHERE t.internal_account_id = ia.id
          AND t.standard_account_id IS DISTINCT FROM ia.standard_account_id
        """
    )
    tx_total = cur.rowcount
    print(f"✓ transactions.standard_account_id 재계산: {tx_total}건")

    conn.commit()

    # 결과 요약
    cur.execute(
        """
        SELECT sa.code, sa.name, COUNT(*) AS ia_count,
               (SELECT COUNT(*) FROM transactions t WHERE t.standard_account_id = sa.id) AS tx_count
        FROM internal_accounts ia
        JOIN standard_accounts sa ON ia.standard_account_id = sa.id
        GROUP BY sa.code, sa.name, sa.id
        ORDER BY tx_count DESC
        LIMIT 20
        """
    )
    print("\n재매핑 후 상위 20개 사용 표준계정:")
    for r in cur.fetchall():
        print(f"  {r[0]} {r[1]:<25} IA={r[2]:<3} TX={r[3]}")

    # 남은 구식 코드 (재매핑 안 된 것)
    old_ids_still_used = []
    cur.execute(
        """
        SELECT sa.code, sa.name, COUNT(ia.id) AS ia_count
        FROM standard_accounts sa
        JOIN internal_accounts ia ON ia.standard_account_id = sa.id
        WHERE sa.code NOT IN (
            SELECT UNNEST(ARRAY[%s])
        )
        GROUP BY sa.code, sa.name
        HAVING COUNT(ia.id) > 0
        ORDER BY sa.code
        """,
        [list(set(REMAP.values()) | set(code_to_id.keys()))],
    )
    # NOTE: 위 쿼리는 모든 존재 code 제외 — 단순 리포트용
    conn.close()


if __name__ == "__main__":
    main()

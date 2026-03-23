"""GAAP 변환 서비스 — K-GAAP → US GAAP 코드 변환

gaap_mapping 테이블을 사용하여 standard_accounts (K-GAAP) 코드를
US GAAP 코드로 변환.
"""

import logging
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)


def get_gaap_mapping(conn: PgConnection) -> dict:
    """gaap_mapping 테이블 로드.

    Returns: {standard_account_id: {"us_gaap_code", "us_gaap_name", "category"}}
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT gm.standard_account_id, gm.us_gaap_code, gm.us_gaap_name, gm.category
        FROM gaap_mapping gm
        WHERE gm.is_confirmed = TRUE OR gm.mapping_source = 'manual'
        """
    )
    mapping = {}
    for row in cur.fetchall():
        std_id, code, name, category = row
        mapping[std_id] = {
            "us_gaap_code": code,
            "us_gaap_name": name,
            "category": category,
        }
    cur.close()

    # 미확인 매핑도 포함 (확인된 것이 없을 때 fallback)
    if not mapping:
        cur = conn.cursor()
        cur.execute(
            "SELECT standard_account_id, us_gaap_code, us_gaap_name, category FROM gaap_mapping"
        )
        for row in cur.fetchall():
            std_id, code, name, category = row
            mapping[std_id] = {
                "us_gaap_code": code,
                "us_gaap_name": name,
                "category": category,
            }
        cur.close()

    return mapping


def convert_kgaap_to_usgaap(
    conn: PgConnection,
    kgaap_balances: list[dict],
) -> list[dict]:
    """K-GAAP 잔액을 US GAAP 코드로 변환.

    Args:
        kgaap_balances: get_all_account_balances() 결과

    Returns:
        US GAAP 코드로 변환된 잔액 목록.
        매핑 없는 계정은 K-GAAP 코드 유지 + is_mapped=False.
    """
    mapping = get_gaap_mapping(conn)
    result = []
    unmapped = []

    for bal in kgaap_balances:
        account_id = bal["account_id"]
        gaap = mapping.get(account_id)

        if gaap:
            result.append({
                **bal,
                "us_gaap_code": gaap["us_gaap_code"],
                "us_gaap_name": gaap["us_gaap_name"],
                "us_gaap_category": gaap["category"],
                "is_mapped": True,
            })
        else:
            # 매핑 없음: K-GAAP 코드 유지
            result.append({
                **bal,
                "us_gaap_code": bal["code"],
                "us_gaap_name": bal["name"],
                "us_gaap_category": bal["category"],
                "is_mapped": False,
            })
            unmapped.append(bal["code"])

    if unmapped:
        logger.warning("Unmapped K-GAAP accounts: %s", unmapped)

    return result

"""
FinanceOne v2 — 초기 데이터 시딩
3개 법인 + K-GAAP 표준계정 + US GAAP 매핑 + 설정
"""

import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from pathlib import Path
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                DATABASE_URL = line.split("=", 1)[1].strip()
                break

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")


def seed():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # --------------------------------------------------
    # 1. entities — 3개 법인
    # --------------------------------------------------
    cur.execute("""
        INSERT INTO entities (code, name, type, currency, parent_id) VALUES
          ('HOI', 'HOI Inc.', 'US_CORP', 'USD', NULL),
          ('HOK', '주식회사 한아원코리아', 'KR_CORP', 'KRW', 1),
          ('HOR', '주식회사 한아원리테일', 'KR_CORP', 'KRW', 2)
        ON CONFLICT (code) DO NOTHING
    """)

    # --------------------------------------------------
    # 2. members — 법인별 구성원
    # --------------------------------------------------
    hok_members = [
        ("하승완", "admin"),
        ("김영수", "member"),
        ("이동현", "member"),
        ("채종민", "member"),
        ("한로제", "member"),
        ("김대윤", "member"),
        ("유동현", "member"),
        ("김주원", "member"),
        ("이창석", "member"),
        ("주식회사 한아원", "corporate"),
    ]
    # HOI + HOR: Shawn Ha only
    for eid in [1, 3]:
        cur.execute(
            "INSERT INTO members (entity_id, name, role) SELECT %s, %s, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM members WHERE entity_id = %s AND name = %s)",
            (eid, "Shawn Ha", "admin", eid, "Shawn Ha"),
        )
    # HOK: all members
    for name, role in hok_members:
        cur.execute(
            "INSERT INTO members (entity_id, name, role) SELECT %s, %s, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM members WHERE entity_id = %s AND name = %s)",
            (2, name, role, 2, name),
        )

    # --------------------------------------------------
    # 3. standard_accounts — K-GAAP 표준계정
    # --------------------------------------------------
    kgaap_accounts = [
        # 자산 - 유동자산
        ('10100', '현금및현금성자산', '자산', '유동자산', 'debit', None, 100),
        ('10200', '단기금융상품', '자산', '유동자산', 'debit', None, 200),
        ('10300', '매출채권', '자산', '유동자산', 'debit', None, 300),
        ('10400', '미수금', '자산', '유동자산', 'debit', None, 400),
        ('10500', '선급금', '자산', '유동자산', 'debit', None, 500),
        ('10600', '선급비용', '자산', '유동자산', 'debit', None, 600),
        ('10700', '재고자산', '자산', '유동자산', 'debit', None, 700),
        ('10800', '부가세대급금', '자산', '유동자산', 'debit', None, 800),
        ('10900', '단기대여금', '자산', '유동자산', 'debit', None, 900),

        # 자산 - 비유동자산
        ('12100', '장기금융상품', '자산', '비유동자산', 'debit', None, 1100),
        ('12200', '토지', '자산', '비유동자산', 'debit', None, 1200),
        ('12300', '건물', '자산', '비유동자산', 'debit', None, 1300),
        ('12400', '감가상각누계액(건물)', '자산', '비유동자산', 'credit', None, 1400),
        ('12500', '차량운반구', '자산', '비유동자산', 'debit', None, 1500),
        ('12600', '감가상각누계액(차량)', '자산', '비유동자산', 'credit', None, 1600),
        ('12700', '비품', '자산', '비유동자산', 'debit', None, 1700),
        ('12800', '감가상각누계액(비품)', '자산', '비유동자산', 'credit', None, 1800),
        ('12900', '소프트웨어', '자산', '비유동자산', 'debit', None, 1900),
        ('13000', '보증금', '자산', '비유동자산', 'debit', None, 2000),
        ('13100', '장기대여금', '자산', '비유동자산', 'debit', None, 2100),

        # 부채 - 유동부채
        ('20100', '매입채무', '부채', '유동부채', 'credit', None, 3000),
        ('20200', '미지급금', '부채', '유동부채', 'credit', None, 3100),
        ('20300', '미지급비용', '부채', '유동부채', 'credit', None, 3200),
        ('20400', '예수금', '부채', '유동부채', 'credit', None, 3300),
        ('20500', '부가세예수금', '부채', '유동부채', 'credit', None, 3400),
        ('20600', '단기차입금', '부채', '유동부채', 'credit', None, 3500),
        ('20700', '선수금', '부채', '유동부채', 'credit', None, 3600),
        ('20800', '유동성장기부채', '부채', '유동부채', 'credit', None, 3700),

        # 부채 - 비유동부채
        ('22100', '장기차입금', '부채', '비유동부채', 'credit', None, 4000),
        ('22200', '임대보증금', '부채', '비유동부채', 'credit', None, 4100),
        ('22300', '퇴직급여충당부채', '부채', '비유동부채', 'credit', None, 4200),

        # 자본
        ('30100', '자본금', '자본', '자본금', 'credit', None, 5000),
        ('30200', '자본잉여금', '자본', '자본잉여금', 'credit', None, 5100),
        ('30300', '이익잉여금', '자본', '이익잉여금', 'credit', None, 5200),
        ('30400', '기타포괄손익누계액', '자본', '기타포괄손익', 'credit', None, 5300),

        # 수익
        ('40100', '매출', '수익', '영업수익', 'credit', None, 6000),
        ('40200', '서비스매출', '수익', '영업수익', 'credit', None, 6100),
        ('40300', '이자수익', '수익', '영업외수익', 'credit', None, 6200),
        ('40400', '외환차익', '수익', '영업외수익', 'credit', None, 6300),
        ('40500', '외화환산이익', '수익', '영업외수익', 'credit', None, 6400),
        ('40600', '잡이익', '수익', '영업외수익', 'credit', None, 6500),

        # 비용
        ('50100', '매출원가', '비용', '매출원가', 'debit', None, 7000),
        ('50200', '급여', '비용', '판매비와관리비', 'debit', None, 7100),
        ('50300', '퇴직급여', '비용', '판매비와관리비', 'debit', None, 7200),
        ('50400', '복리후생비', '비용', '판매비와관리비', 'debit', None, 7300),
        ('50500', '임차료', '비용', '판매비와관리비', 'debit', None, 7400),
        ('50600', '접대비', '비용', '판매비와관리비', 'debit', None, 7500),
        ('50700', '통신비', '비용', '판매비와관리비', 'debit', None, 7600),
        ('50800', '수도광열비', '비용', '판매비와관리비', 'debit', None, 7700),
        ('50900', '세금과공과', '비용', '판매비와관리비', 'debit', None, 7800),
        ('51000', '감가상각비', '비용', '판매비와관리비', 'debit', None, 7900),
        ('51100', '보험료', '비용', '판매비와관리비', 'debit', None, 8000),
        ('51200', '차량유지비', '비용', '판매비와관리비', 'debit', None, 8100),
        ('51300', '여비교통비', '비용', '판매비와관리비', 'debit', None, 8200),
        ('51400', '소모품비', '비용', '판매비와관리비', 'debit', None, 8300),
        ('51500', '지급수수료', '비용', '판매비와관리비', 'debit', None, 8400),
        ('51600', '광고선전비', '비용', '판매비와관리비', 'debit', None, 8500),
        ('51700', '교육훈련비', '비용', '판매비와관리비', 'debit', None, 8600),
        ('51800', '도서인쇄비', '비용', '판매비와관리비', 'debit', None, 8700),
        ('51900', '수선비', '비용', '판매비와관리비', 'debit', None, 8800),
        ('52000', '이자비용', '비용', '영업외비용', 'debit', None, 8900),
        ('52100', '외환차손', '비용', '영업외비용', 'debit', None, 9000),
        ('52200', '외화환산손실', '비용', '영업외비용', 'debit', None, 9100),
        ('52300', '잡손실', '비용', '영업외비용', 'debit', None, 9200),
        ('52400', '법인세비용', '비용', '법인세', 'debit', None, 9300),

        # 구독/SaaS 세분화 (한아원 맞춤)
        ('51510', 'SaaS 구독료', '비용', '판매비와관리비', 'debit', '51500', 8410),
        ('51520', '결제수수료', '비용', '판매비와관리비', 'debit', '51500', 8420),
        ('51530', '배달플랫폼수수료', '비용', '판매비와관리비', 'debit', '51500', 8430),
    ]

    for acc in kgaap_accounts:
        cur.execute("""
            INSERT INTO standard_accounts (code, name, category, subcategory, normal_side, parent_code, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO NOTHING
        """, acc)

    # --------------------------------------------------
    # 4. gaap_mapping — US GAAP ↔ K-GAAP 매핑 (HOI용)
    # --------------------------------------------------
    gaap_mappings = [
        ('1000', 'Cash and Cash Equivalents', '10100', 'Assets'),
        ('1100', 'Accounts Receivable', '10300', 'Assets'),
        ('1200', 'Other Receivables', '10400', 'Assets'),
        ('1300', 'Prepaid Expenses', '10600', 'Assets'),
        ('1500', 'Property, Plant & Equipment', '12200', 'Assets'),
        ('1600', 'Accumulated Depreciation', '12400', 'Assets'),
        ('1700', 'Intangible Assets (Software)', '12900', 'Assets'),
        ('2000', 'Accounts Payable', '20100', 'Liabilities'),
        ('2100', 'Accrued Expenses', '20300', 'Liabilities'),
        ('2200', 'Short-term Borrowings', '20600', 'Liabilities'),
        ('2500', 'Long-term Debt', '22100', 'Liabilities'),
        ('3000', 'Common Stock', '30100', 'Equity'),
        ('3100', 'Additional Paid-in Capital', '30200', 'Equity'),
        ('3200', 'Retained Earnings', '30300', 'Equity'),
        ('3300', 'Accumulated Other Comprehensive Income', '30400', 'Equity'),
        ('4000', 'Revenue', '40100', 'Revenue'),
        ('4100', 'Service Revenue', '40200', 'Revenue'),
        ('4200', 'Interest Income', '40300', 'Revenue'),
        ('4300', 'Foreign Exchange Gain', '40400', 'Revenue'),
        ('5000', 'Cost of Revenue', '50100', 'Expenses'),
        ('5100', 'Salaries & Wages', '50200', 'Expenses'),
        ('5200', 'Rent Expense', '50500', 'Expenses'),
        ('5300', 'Depreciation Expense', '51000', 'Expenses'),
        ('5400', 'Professional Fees', '51500', 'Expenses'),
        ('5500', 'Software Subscriptions', '51510', 'Expenses'),
        ('5600', 'Interest Expense', '52000', 'Expenses'),
        ('5700', 'Foreign Exchange Loss', '52100', 'Expenses'),
        ('5800', 'Income Tax Expense', '52400', 'Expenses'),
    ]

    for us_code, us_name, kgaap_code, category in gaap_mappings:
        cur.execute("""
            INSERT INTO gaap_mapping (us_gaap_code, us_gaap_name, standard_account_id, category)
            SELECT %s, %s, sa.id, %s
            FROM standard_accounts sa WHERE sa.code = %s
            ON CONFLICT (us_gaap_code) DO NOTHING
        """, (us_code, us_name, category, kgaap_code))

    # --------------------------------------------------
    # 5. settings — 초기 설정
    # --------------------------------------------------
    settings = [
        ('min_cash_buffer', '5000000', 2),
        ('min_cash_buffer', '3000000', 3),
        ('api_woori_bank_enabled', 'false', None),
        ('api_lotte_card_enabled', 'false', None),
        ('default_exchange_rate_usd', '1482', None),
        ('notebooklm_enabled', 'false', None),
        ('obsidian_vault_path', '', None),
    ]

    for key, value, entity_id in settings:
        cur.execute("""
            INSERT INTO settings (key, value, entity_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (key, value, entity_id))

    # --------------------------------------------------
    # 6. internal_accounts — 내부 계정 (수입/비용 트리 구조)
    # --------------------------------------------------
    # (코드, 이름, 표준계정코드, 부모코드)
    # 코드 자동 생성 — 사용자에게 노출 안 됨
    internal_accounts = [
        # ── 수입 (최상위, 드래그 불가) ──
        ("INC", "수입", None, None),
        ("INC-001", "매출", "40100", "INC"),
        ("INC-002", "서비스매출", "40200", "INC"),
        ("INC-003", "이자수익", "40300", "INC"),
        ("INC-004", "기타수입", "40600", "INC"),

        # ── 비용 (최상위, 드래그 불가) ──
        ("EXP", "비용", None, None),

        # 인건비
        ("EXP-010", "인건비", "50200", "EXP"),
        ("EXP-010-001", "급여", "50200", "EXP-010"),
        ("EXP-010-002", "퇴직금", "50300", "EXP-010"),
        ("EXP-010-003", "4대보험", "50400", "EXP-010"),

        # 사무실
        ("EXP-020", "사무실", "50500", "EXP"),
        ("EXP-020-001", "임차료", "50500", "EXP-020"),
        ("EXP-020-002", "관리비", "50800", "EXP-020"),
        ("EXP-020-003", "통신비", "50700", "EXP-020"),

        # 식비/복리후생
        ("EXP-030", "식비/복리후생", "50400", "EXP"),
        ("EXP-030-001", "점심", "50400", "EXP-030"),
        ("EXP-030-002", "간식/커피", "50400", "EXP-030"),
        ("EXP-030-003", "회식", "50600", "EXP-030"),

        # 교통
        ("EXP-040", "교통", "51300", "EXP"),
        ("EXP-040-001", "택시", "51300", "EXP-040"),
        ("EXP-040-002", "주차", "51300", "EXP-040"),
        ("EXP-040-003", "출장", "51300", "EXP-040"),

        # 마케팅
        ("EXP-050", "마케팅", "51600", "EXP"),
        ("EXP-050-001", "광고비", "51600", "EXP-050"),
        ("EXP-050-002", "인플루언서", "51600", "EXP-050"),
        ("EXP-050-003", "이벤트", "51600", "EXP-050"),

        # IT/SaaS
        ("EXP-060", "IT/SaaS", "51510", "EXP"),
        ("EXP-060-001", "ChatGPT", "51510", "EXP-060"),
        ("EXP-060-002", "Cursor", "51510", "EXP-060"),
        ("EXP-060-003", "Google Workspace", "51510", "EXP-060"),
        ("EXP-060-004", "AWS", "51510", "EXP-060"),
        ("EXP-060-005", "기타 구독", "51510", "EXP-060"),

        # 수수료
        ("EXP-070", "수수료", "51500", "EXP"),
        ("EXP-070-001", "카드수수료", "51500", "EXP-070"),
        ("EXP-070-002", "결제수수료", "51520", "EXP-070"),
        ("EXP-070-003", "배달수수료", "51530", "EXP-070"),

        # 세금/공과
        ("EXP-080", "세금/공과", "50900", "EXP"),
        ("EXP-080-001", "부가세", "50900", "EXP-080"),
        ("EXP-080-002", "법인세", "50900", "EXP-080"),

        # 기타비용
        ("EXP-090", "기타비용", "52300", "EXP"),
    ]

    for entity_id in [1, 2, 3]:
        # Pass 1: insert all accounts without parent
        for idx, (code, name, std_code, _parent) in enumerate(internal_accounts):
            if std_code:
                cur.execute("""
                    INSERT INTO internal_accounts (entity_id, code, name, standard_account_id, sort_order)
                    SELECT %s, %s, %s, sa.id, %s
                    FROM standard_accounts sa WHERE sa.code = %s
                    ON CONFLICT (entity_id, code) DO NOTHING
                """, (entity_id, code, name, (idx + 1) * 100, std_code))
            else:
                # 최상위 노드 (수입/비용) — standard_account 없음
                cur.execute("""
                    INSERT INTO internal_accounts (entity_id, code, name, standard_account_id, sort_order)
                    VALUES (%s, %s, %s, NULL, %s)
                    ON CONFLICT (entity_id, code) DO NOTHING
                """, (entity_id, code, name, (idx + 1) * 100))

        # Pass 2: set parent_id for hierarchical accounts
        for code, _name, _std, parent_code in internal_accounts:
            if parent_code:
                cur.execute("""
                    UPDATE internal_accounts c
                    SET parent_id = p.id
                    FROM internal_accounts p
                    WHERE c.entity_id = %s AND c.code = %s
                      AND p.entity_id = %s AND p.code = %s
                """, (entity_id, code, entity_id, parent_code))

    conn.commit()
    cur.close()
    conn.close()
    print("Seed complete: 3 entities, K-GAAP accounts, US GAAP mappings, settings, internal accounts")


if __name__ == "__main__":
    seed()

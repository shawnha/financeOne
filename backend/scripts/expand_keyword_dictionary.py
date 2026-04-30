"""P4-A 도메인 키워드 사전 — standard_account_keywords 확장.

설계 결정 (Stage 3 Eng Review):
  D3 Idempotency: ON CONFLICT (keyword) DO NOTHING (불변)
  D4 Noise filter: stopwords + 정규화

운영 정책:
  - keyword 는 UNIQUE (스키마 제약). 같은 keyword 두 계정에 매핑 불가.
  - 한 keyword 가 여러 계정 후보면 가장 빈도 높거나 도메인적으로 명확한 1개만.
  - 사용자가 수동 조정한 confidence 는 보존 (DO NOTHING).

⚠️  중요 — Idempotency Silent-Drift 위험:
  ON CONFLICT DO NOTHING 정책상, 본 스크립트의 DOMAIN_KEYWORDS 에서
  기존 keyword 의 standard_account_id 또는 confidence 를 변경해도
  DB 에 반영되지 않습니다. 변경하려면:
    1) 명시적 SQL UPDATE (수동), 또는
    2) 별도 마이그레이션 스크립트 (예: update_keyword_mapping.py)
  를 작성해야 합니다.

키워드 선정 가이드 (Code Review P0/P1 반영):
  - ILIKE substring 매칭이므로 짧은 영문 약자 (KT, KB 등) 는 false-positive 위험.
    → 'KT' 대신 'KT통신', 'olleh KT' 같은 disambiguation 형태 사용.
  - 다중 카테고리 거래처 (Adobe = SaaS / Adobe Stock = 광고소재) 는 분리 등록.
    'Adobe Creative Cloud', 'Adobe Acrobat' 등 구체화.
  - 한국어 합성어 (월급 → 월급통장) 은 의도된 substring 매칭 검토.

사용법:
  source .venv/bin/activate
  python -m backend.scripts.expand_keyword_dictionary
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


# (keyword, standard_account_code, confidence)
# 14 개 기존 키워드(회식,택시,식대,커피,사무용품,인터넷,전화,임대,월세,급여,보험,광고,수수료,이자) 는 ON CONFLICT 로 자동 skip.
DOMAIN_KEYWORDS: list[tuple[str, str, float]] = [
    # ===== 복리후생비 (50400) =====
    ("간식", "50400", 0.80),
    ("도시락", "50400", 0.80),
    ("스타벅스", "50400", 0.90),
    ("파리바게뜨", "50400", 0.90),
    ("뚜레쥬르", "50400", 0.90),
    ("배민", "50400", 0.85),
    ("쿠팡이츠", "50400", 0.85),
    ("KFC", "50400", 0.90),
    ("맥도날드", "50400", 0.90),
    ("McDonald", "50400", 0.85),
    ("BBQ", "50400", 0.85),
    ("교촌", "50400", 0.85),
    ("회식비", "50400", 0.95),

    # ===== 여비교통비 (51300) =====
    ("카카오택시", "51300", 0.95),
    ("우버", "51300", 0.90),
    ("UBER", "51300", 0.85),
    ("지하철", "51300", 0.85),
    ("KTX", "51300", 0.85),
    ("코레일", "51300", 0.90),
    ("주유소", "51300", 0.85),
    ("GS칼텍스", "51300", 0.85),
    ("SK에너지", "51300", 0.85),
    ("출장", "51300", 0.80),
    ("항공", "51300", 0.85),
    ("대한항공", "51300", 0.90),
    ("아시아나", "51300", 0.85),
    ("주차장", "51300", 0.85),
    ("주차료", "51300", 0.85),
    ("티머니", "51300", 0.90),
    ("교통카드", "51300", 0.90),

    # ===== 임차료 (50500) =====
    ("임차", "50500", 0.85),
    ("임대료", "50500", 0.90),
    # P1-4: '관리비' 제거 — 모호 (아파트관리비 vs 사무실관리비). entity 별 mapping_rules 로 처리.
    ("위워크", "50500", 0.90),
    ("WeWork", "50500", 0.85),
    ("스파크플러스", "50500", 0.90),

    # ===== 통신비 (50700) =====
    # P0-1: 'KT' 제거 — 'KTX'(여비교통비), 'KT&G'(매출), 'KTwiz' 등 false-positive 위험.
    # 대안: 더 구체적인 disambiguation 키워드 사용
    ("KT통신", "50700", 0.95),
    ("olleh", "50700", 0.85),
    ("KT스카이라이프", "50700", 0.95),
    ("SKT", "50700", 0.85),
    ("LGU+", "50700", 0.85),
    ("통신요금", "50700", 0.95),
    ("통신비", "50700", 0.95),

    # ===== 급여 (50200) =====
    # P1-3: '월급' 제거 — '월급통장이체' 같은 비-급여 거래 false-hit. 기존 14개 '급여' 가 커버.
    ("연봉", "50200", 0.80),

    # ===== 퇴직급여 (50300) =====
    ("퇴직", "50300", 0.85),
    ("퇴직금", "50300", 0.90),
    ("퇴직연금", "50300", 0.90),

    # ===== 광고선전비 (51600) =====
    ("Google Ads", "51600", 0.95),
    ("META", "51600", 0.85),
    ("MIDJOURNEY", "51600", 0.90),
    ("LINKEDIN", "51600", 0.85),
    ("APIFY", "51600", 0.80),
    ("ARCADS", "51600", 0.80),
    ("AFTERSHIP", "51600", 0.85),

    # ===== 지급수수료 (51500) =====
    ("이체수수료", "51500", 0.95),
    ("법무사", "51500", 0.85),
    ("세무사", "51500", 0.85),
    ("회계법인", "51500", 0.90),

    # ===== 결제수수료 (51520) =====
    ("이니시스", "51520", 0.95),
    ("KCP", "51520", 0.90),
    ("나이스결제", "51520", 0.90),
    ("토스페이", "51520", 0.85),
    ("카카오페이", "51520", 0.85),
    ("페이팔", "51520", 0.85),
    ("PayPal", "51520", 0.85),
    ("Stripe", "51520", 0.85),

    # ===== SaaS 구독료 (51510) =====
    # P0-2: 'Adobe' 단독 제거 — 'Adobe Stock', 'Adobe Express' 는 광고소재 (51600 광고선전비).
    # SaaS 인 경우만 정확히 매칭하도록 분리:
    ("Adobe Creative Cloud", "51510", 0.95),
    ("Adobe CC", "51510", 0.95),
    ("Adobe Acrobat", "51510", 0.95),
    ("Notion", "51510", 0.95),
    ("Slack", "51510", 0.95),
    ("AIRTABLE", "51510", 0.90),
    ("FIGMA", "51510", 0.90),
    ("Zapier", "51510", 0.90),
    ("Zoom", "51510", 0.90),
    ("ANTHROPIC", "51510", 0.95),
    ("OPENAI", "51510", 0.95),
    ("ChatGPT", "51510", 0.90),
    ("GitHub", "51510", 0.90),
    ("AWS", "51510", 0.90),
    ("Vercel", "51510", 0.95),
    ("Cloudflare", "51510", 0.90),
    ("Dropbox", "51510", 0.90),

    # ===== 사무용품/소모품 (51400) =====
    ("문구", "51400", 0.80),
    ("한가람문구", "51400", 0.95),
    ("다이소", "51400", 0.90),
    ("토너", "51400", 0.85),
    ("A4용지", "51400", 0.95),

    # ===== 세금과공과 (50900) =====
    ("국민연금", "50900", 0.95),
    ("건강보험", "50900", 0.95),
    ("고용보험", "50900", 0.95),
    ("산재보험", "50900", 0.95),
    ("4대보험", "50900", 0.95),
    ("국민건강", "50900", 0.95),
    ("자동차세", "50900", 0.95),
    ("재산세", "50900", 0.95),
    ("등록세", "50900", 0.90),
    ("취득세", "50900", 0.90),
    ("부가가치세", "50900", 0.95),

    # ===== 법인세 (52400) =====
    ("법인세", "52400", 0.95),

    # ===== 접대비 (50600) =====
    ("접대", "50600", 0.85),

    # ===== 차량유지비 (51200) =====
    ("세차", "51200", 0.85),
    ("정비", "51200", 0.80),

    # ===== 이자비용 (52000) / 이자수익 (40300) =====
    ("이자비용", "52000", 0.95),
    ("대출이자", "52000", 0.90),
    ("이자수익", "40300", 0.95),
    ("예금이자", "40300", 0.95),

    # ===== 외환 (52100/52200) =====
    ("외환차손", "52100", 0.95),
    ("외화환산", "52200", 0.95),

    # ===== 매출 (40100) =====
    ("스마트스토어정산", "40100", 0.95),
    ("쿠팡정산", "40100", 0.90),
    ("11번가정산", "40100", 0.85),

    # ===== 운반비 (82400) =====
    ("택배", "82400", 0.85),
    ("CJ대한통운", "82400", 0.90),
    ("우체국택배", "82400", 0.90),

    # ===== 교육훈련비 (51700) =====
    ("강의", "51700", 0.80),
    ("세미나", "51700", 0.85),

    # ===== 도서인쇄비 (51800) =====
    ("교보문고", "51800", 0.90),
    ("YES24", "51800", 0.90),
    ("알라딘", "51800", 0.85),
    ("인쇄", "51800", 0.80),
]


def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")

        cur.execute("SELECT code, id FROM standard_accounts")
        code_to_id = {r[0]: r[1] for r in cur.fetchall()}

        inserted = 0
        skipped_existing = 0
        skipped_no_code = 0
        seen_keywords = set()

        for kw, code, conf in DOMAIN_KEYWORDS:
            if kw in seen_keywords:
                # 같은 키워드를 두 번 등록하려는 스크립트 내 중복
                skipped_existing += 1
                continue
            seen_keywords.add(kw)

            std_id = code_to_id.get(code)
            if not std_id:
                skipped_no_code += 1
                print(f"  ! code={code} not found, skipping keyword={kw}")
                continue

            # D3: ON CONFLICT (keyword) DO NOTHING — idempotent + 사용자 수동 조정 보존
            cur.execute(
                """
                INSERT INTO standard_account_keywords (keyword, standard_account_id, confidence)
                VALUES (%s, %s, %s)
                ON CONFLICT (keyword) DO NOTHING
                RETURNING id
                """,
                [kw, std_id, conf],
            )
            if cur.fetchone():
                inserted += 1
            else:
                skipped_existing += 1

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM standard_account_keywords")
        total = cur.fetchone()[0]
        cur.close()

        print(f"\n신규 INSERT: {inserted}건")
        print(f"이미 존재 / 중복: {skipped_existing}건")
        print(f"코드 없음: {skipped_no_code}건")
        print(f"전체 standard_account_keywords: {total}개")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

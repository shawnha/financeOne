"""25년 결산 PDF 코드 시스템(11000~95300) standard_accounts 등록 + 한국어 설명.

- import_2025_finalized_hok.py 가 PDF 양식 코드 그대로 line_items 에 저장하지만,
  standard_accounts 에는 다른 코드 체계(17900, 27500 등)로 들어있어
  hover tooltip 직접 lookup 이 실패.
- 이 스크립트가:
  1) PDF 코드 13개를 standard_accounts 에 신규 등록 (description 포함)
  2) 매칭되는 기존 코드(17900, 27500 등) 중 description 빈 것도 같이 채움
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


# (code, name, category, subcategory, normal_side, sort_order, description)
NEW_PDF_CODES: list[tuple[str, str, str, str, str, int, str]] = [
    ("11000", "받을어음", "자산", "당좌자산", "debit", 11000,
     "거래처에서 받은 어음. 만기 시 현금으로 회수 예정."),
    ("14700", "제품", "자산", "재고자산", "debit", 14700,
     "공장에서 직접 만든 완성품 (제조업 재고)."),
    ("14800", "재공품", "자산", "재고자산", "debit", 14800,
     "공장에서 만들고 있는 중인 미완성 제품."),
    ("14900", "원재료", "자산", "재고자산", "debit", 14900,
     "제품 만들 원료/재료."),
    ("17600", "장기대여금", "자산", "투자자산", "debit", 17600,
     "1년 넘어서 회수할 빌려준 돈."),
    ("23200", "임차보증금", "자산", "기타비유동", "debit", 23200,
     "임차 시 집주인에게 맡긴 보증금. 계약 종료 시 반환."),
    ("26400", "미지급급여", "부채", "유동부채", "credit", 26400,
     "임직원에게 지급할 급여 중 미지급 부분."),
    ("37700", "이월결손금", "자본", "이익잉여금", "debit", 37700,
     "전기까지 누적된 결손금 이월액."),
    ("80100", "직원급여", "비용", "판매비와관리비", "debit", 80100,
     "직원에게 지급한 월급/주급 등 정기 급여."),
    ("90200", "이자비용", "비용", "영업외비용", "debit", 90200,
     "은행 차입금에 낸 이자."),
    ("91000", "외환차익", "수익", "영업외수익", "credit", 91000,
     "외환 거래에서 발생한 환율 변동 이익."),
    ("91100", "국고보조금수익", "수익", "영업외수익", "credit", 91100,
     "정부에서 받은 보조금, 지원금."),
    ("95300", "잡손실", "비용", "영업외비용", "debit", 95300,
     "분류하기 애매한 기타 손실."),
]


# (code, description) — description 만 채울 기존 코드
FILL_EXISTING: list[tuple[str, str]] = [
    ("17900", "1년 넘어서 회수할 빌려준 돈."),
    ("27500", "임직원에게 지급할 급여 중 미지급 부분."),
    ("37600", "전기까지 누적된 결손금 이월액."),
    ("50200", "직원에게 지급한 월급/주급 등 정기 급여."),
    ("52000", "은행 차입금에 낸 이자."),
    ("52300", "분류하기 애매한 기타 손실."),
    ("90700", "외환 거래에서 발생한 환율 변동 이익."),
    ("92900", "정부에서 받은 보조금, 지원금."),
    ("93300", "은행 차입금에 낸 이자."),
    ("96000", "분류하기 애매한 기타 손실."),
    ("96200", "임차 시 집주인에게 맡긴 보증금. 계약 종료 시 반환."),
]


def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")

        # 1) 신규 PDF 코드 INSERT (이미 있으면 description 만 갱신)
        inserted = 0
        updated_existing_pdf = 0
        for code, name, cat, subcat, side, sort_order, desc in NEW_PDF_CODES:
            cur.execute(
                """
                INSERT INTO standard_accounts
                    (code, name, category, subcategory, normal_side, sort_order, is_active, description)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (code) DO UPDATE SET
                    description = EXCLUDED.description,
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    subcategory = EXCLUDED.subcategory,
                    normal_side = EXCLUDED.normal_side
                RETURNING (xmax = 0) AS inserted
                """,
                [code, name, cat, subcat, side, sort_order, desc],
            )
            row = cur.fetchone()
            if row and row[0]:
                inserted += 1
            else:
                updated_existing_pdf += 1

        # 2) 기존 매칭 코드 description 채움 (description 비어있을 때만)
        filled = 0
        skipped = 0
        for code, desc in FILL_EXISTING:
            cur.execute(
                """
                UPDATE standard_accounts
                SET description = %s
                WHERE code = %s AND (description IS NULL OR description = '')
                RETURNING id
                """,
                [desc, code],
            )
            if cur.fetchone():
                filled += 1
            else:
                skipped += 1

        conn.commit()
        cur.close()

        print(f"신규 PDF 코드 INSERT: {inserted}건")
        print(f"신규 PDF 코드 UPDATE (이미 있던 것): {updated_existing_pdf}건")
        print(f"기존 코드 description 채움: {filled}건 (skip {skipped}건)")

    except Exception as e:
        conn.rollback()
        print(f"실패: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

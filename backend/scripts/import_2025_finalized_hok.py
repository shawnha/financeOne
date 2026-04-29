"""한아원코리아(entity_id=2) 2025년 K-GAAP 확정 재무제표 import.

원본: /Users/admin/Documents/HanahOneAll/Finance/결산자료/[주식회사 한아원코리아]_25년귀속 재무제표 (2).pdf
- 재무상태표 (BS), 손익계산서 (PL), 결손금처리계산서 (DT), 합계잔액시산표 (TB)

직접 line_items INSERT (transactions 기반 자동 생성 X — 25년은 confirmed 자료).
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

ENTITY_ID = 2
FISCAL_YEAR = 2025
START_MONTH = 1
END_MONTH = 12
KI_NUM = 2  # 제2(당)기

# (statement_type, account_code, line_key, label, sort_order, is_section_header, auto_amount, auto_debit, auto_credit)

BS_LINES = [
    ("balance_sheet", None, "assets_header", "자산", 10, True, 0, 0, 0),
    ("balance_sheet", None, "current_assets_header", "  Ⅰ. 유동자산", 20, True, 505508004, 0, 0),
    ("balance_sheet", None, "quick_assets_header", "    (1) 당좌자산", 30, True, 469811609, 0, 0),
    ("balance_sheet", "10100", "cash", "      현금", 40, False, 0, 0, 0),
    ("balance_sheet", "10300", "checking_deposit", "      보통예금", 50, False, 161065312, 0, 0),
    ("balance_sheet", "10800", "accounts_receivable", "      외상매출금", 60, False, 246164180, 0, 0),
    ("balance_sheet", "12000", "other_receivable", "      미수금", 70, False, 50648785, 0, 0),
    ("balance_sheet", "13100", "prepaid_expense", "      선급금", 80, False, 11892712, 0, 0),
    ("balance_sheet", "13500", "prepaid_tax", "      선납세금", 90, False, 40620, 0, 0),
    ("balance_sheet", "13700", "stt_short_term_receivable", "      주.임.종 단기채권", 100, False, 0, 0, 0),
    ("balance_sheet", None, "inventory_header", "    (2) 재고자산", 110, True, 35696395, 0, 0),
    ("balance_sheet", "14600", "merchandise", "      상품", 120, False, 35696395, 0, 0),
    ("balance_sheet", None, "noncurrent_assets_header", "  Ⅱ. 비유동자산", 130, True, 216636365, 0, 0),
    ("balance_sheet", None, "investment_assets_header", "    (1) 투자자산", 140, True, 0, 0, 0),
    ("balance_sheet", None, "tangible_assets_header", "    (2) 유형자산", 150, True, 116436365, 0, 0),
    ("balance_sheet", "20800", "equipment", "      비품", 160, False, 36436365, 0, 0),
    ("balance_sheet", "21900", "facility", "      시설장치", 170, False, 80000000, 0, 0),
    ("balance_sheet", None, "intangible_assets_header", "    (3) 무형자산", 180, True, 0, 0, 0),
    ("balance_sheet", None, "other_noncurrent_header", "    (4) 기타비유동자산", 190, True, 100200000, 0, 0),
    ("balance_sheet", "23200", "lease_deposit", "      임차보증금", 200, False, 100200000, 0, 0),
    ("balance_sheet", None, "total_assets", "  자산총계", 210, True, 722144369, 0, 0),

    ("balance_sheet", None, "liabilities_header", "부채", 300, True, 0, 0, 0),
    ("balance_sheet", None, "current_liab_header", "  Ⅰ. 유동부채", 310, True, 100923991, 0, 0),
    ("balance_sheet", "25100", "accounts_payable", "    외상매입금", 320, False, 54253934, 0, 0),
    ("balance_sheet", "25400", "withholding", "    예수금", 330, False, 4069170, 0, 0),
    ("balance_sheet", "26200", "accrued_expense", "    미지급비용", 340, False, 42600887, 0, 0),
    ("balance_sheet", None, "noncurrent_liab_header", "  Ⅱ. 비유동부채", 350, True, 680000000, 0, 0),
    ("balance_sheet", "30300", "stt_long_term_borrowing", "    주.임.종 장기차입금", 360, False, 130000000, 0, 0),
    ("balance_sheet", "30400", "conditional_equity_liability", "    조건부지분인수계약부채", 370, False, 550000000, 0, 0),
    ("balance_sheet", None, "total_liabilities", "  부채총계", 380, True, 780923991, 0, 0),

    ("balance_sheet", None, "equity_header", "자본", 500, True, 0, 0, 0),
    ("balance_sheet", None, "capital_stock_header", "  Ⅰ. 자본금", 510, True, 303602000, 0, 0),
    ("balance_sheet", "33100", "capital_stock", "    자본금", 520, False, 303602000, 0, 0),
    ("balance_sheet", None, "capital_surplus_header", "  Ⅱ. 자본잉여금", 530, True, 761393660, 0, 0),
    ("balance_sheet", "34100", "share_premium", "    주식발행초과금", 540, False, 761393660, 0, 0),
    ("balance_sheet", None, "capital_adjustment_header", "  Ⅲ. 자본조정", 550, True, 0, 0, 0),
    ("balance_sheet", None, "aoci_header", "  Ⅳ. 기타포괄손익누계액", 560, True, 0, 0, 0),
    ("balance_sheet", None, "deficit_header", "  Ⅴ. 결손금", 570, True, -1123775282, 0, 0),
    ("balance_sheet", "37800", "unappropriated_deficit", "    미처리결손금", 580, False, -1123775282, 0, 0),
    ("balance_sheet", None, "net_loss_note", "    (당기순손실: 1,102,272,560원)", 590, True, 0, 0, 0),
    ("balance_sheet", None, "total_equity", "  자본총계", 600, True, -58779622, 0, 0),
    ("balance_sheet", None, "total_liab_and_equity", "부채 및 자본 총계", 610, True, 722144369, 0, 0),
]

PL_LINES = [
    ("income_statement", None, "revenue_header", "Ⅰ. 매출액", 10, True, 244205637, 0, 0),
    ("income_statement", "40100", "merchandise_sales", "  상품매출", 20, False, 254696544, 0, 0),
    ("income_statement", "40400", "sales_returns", "  매출환입및에누리", 30, False, -39581816, 0, 0),
    ("income_statement", "41200", "service_sales", "  서비스매출", 40, False, 29090909, 0, 0),
    ("income_statement", None, "cogs_header", "Ⅱ. 매출원가", 50, True, 221359084, 0, 0),
    ("income_statement", "45100", "merchandise_cogs", "  상품매출원가", 60, False, 221359084, 0, 0),
    ("income_statement", None, "beginning_inventory", "    기초상품재고액", 65, False, 0, 0, 0),
    ("income_statement", None, "purchases", "    당기상품매입액", 70, False, 257055479, 0, 0),
    ("income_statement", None, "ending_inventory", "    기말상품재고액", 75, False, -35696395, 0, 0),
    ("income_statement", None, "gross_profit", "Ⅲ. 매출총이익", 80, True, 22846553, 0, 0),
    ("income_statement", None, "sga_header", "Ⅳ. 판매비와관리비", 90, True, 1147279311, 0, 0),
    ("income_statement", "80100", "salaries", "  직원급여", 100, False, 285330258, 0, 0),
    ("income_statement", "81100", "welfare", "  복리후생비", 110, False, 110589671, 0, 0),
    ("income_statement", "81200", "travel", "  여비교통비", 120, False, 129703882, 0, 0),
    ("income_statement", "81300", "entertainment", "  접대비(기업업무추진비)", 130, False, 4255107, 0, 0),
    ("income_statement", "81700", "tax_expense", "  세금과공과금", 140, False, 2475080, 0, 0),
    ("income_statement", "81900", "rent_expense", "  지급임차료", 150, False, 68838490, 0, 0),
    ("income_statement", "82100", "insurance", "  보험료", 160, False, 22714950, 0, 0),
    ("income_statement", "82400", "delivery", "  운반비", 170, False, 8855388, 0, 0),
    ("income_statement", "82900", "office_supplies", "  사무용품비", 180, False, 8498203, 0, 0),
    ("income_statement", "83000", "consumables", "  소모품비", 190, False, 37754173, 0, 0),
    ("income_statement", "83100", "service_fee", "  지급수수료", 200, False, 214061914, 0, 0),
    ("income_statement", "83300", "advertising", "  광고선전비", 210, False, 254202195, 0, 0),
    ("income_statement", None, "operating_loss", "Ⅴ. 영업손실", 220, True, -1124432758, 0, 0),
    ("income_statement", None, "non_operating_income_header", "Ⅵ. 영업외수익", 230, True, 22905575, 0, 0),
    ("income_statement", "90100", "interest_income", "  이자수익", 240, False, 278816, 0, 0),
    ("income_statement", "91000", "fx_gain", "  외환차익", 250, False, 2918194, 0, 0),
    ("income_statement", "91100", "govt_subsidy", "  국고보조금수익", 260, False, 19050286, 0, 0),
    ("income_statement", "93000", "misc_income", "  잡이익", 270, False, 658279, 0, 0),
    ("income_statement", None, "non_operating_expense_header", "Ⅶ. 영업외비용", 280, True, 745377, 0, 0),
    ("income_statement", "95300", "misc_loss", "  잡손실", 290, False, 745377, 0, 0),
    ("income_statement", None, "income_before_tax", "Ⅷ. 법인세차감전손실", 300, True, -1102272560, 0, 0),
    ("income_statement", None, "income_tax", "Ⅸ. 법인세등", 310, True, 0, 0, 0),
    ("income_statement", None, "net_loss", "Ⅹ. 당기순손실", 320, True, -1102272560, 0, 0),
]

DT_LINES = [
    ("deficit_treatment", None, "unappropriated_header", "Ⅰ. 미처리결손금", 10, True, 1123775282, 0, 0),
    ("deficit_treatment", None, "prior_carryforward", "  1. 전기이월미처리결손금", 20, False, 21502722, 0, 0),
    ("deficit_treatment", None, "accounting_change", "  2. 회계변경의누적효과", 30, False, 0, 0, 0),
    ("deficit_treatment", None, "prior_correction_gain", "  3. 전기오류수정이익", 40, False, 0, 0, 0),
    ("deficit_treatment", None, "prior_correction_loss", "  4. 전기오류수정손실", 50, False, 0, 0, 0),
    ("deficit_treatment", None, "interim_dividend", "  5. 중간배당금", 60, False, 0, 0, 0),
    ("deficit_treatment", None, "current_net_loss", "  6. 당기순손실", 70, False, 1102272560, 0, 0),
    ("deficit_treatment", None, "deficit_treatment_amount", "Ⅱ. 결손금처리액", 80, True, 0, 0, 0),
    ("deficit_treatment", None, "retained_disposition", "Ⅲ. 이익잉여금처분액", 90, True, 0, 0, 0),
    ("deficit_treatment", None, "carryforward_deficit", "Ⅳ. 차기이월미처리결손금", 100, True, 1123775282, 0, 0),
]

# 합계잔액시산표 — PDF 의 차변/대변 합계 + 잔액 그대로
TB_LINES = [
    # 자산 영역
    ("trial_balance", None, "current_assets_tb", "유동자산", 10, True, 505508004, 3888726148, 3383218144),
    ("trial_balance", None, "quick_assets_tb", "<당좌자산>", 20, True, 469811609, 3631670669, 3161859060),
    ("trial_balance", "10100", "cash_tb", "현금", 30, False, 0, 553046, 553046),
    ("trial_balance", "10300", "checking_deposit_tb", "보통예금", 40, False, 161065312, 2976395059, 2815329747),
    ("trial_balance", "10800", "accounts_receivable_tb", "외상매출금", 50, False, 246164180, 286852904, 40688724),
    ("trial_balance", "12000", "other_receivable_tb", "미수금", 60, False, 50648785, 105352147, 54703362),
    ("trial_balance", "13100", "prepaid_expense_tb", "선급금", 70, False, 11892712, 20057120, 8164408),
    ("trial_balance", "13400", "prepaid_payment_tb", "가지급금", 80, False, 0, 70000000, 70000000),
    ("trial_balance", "13600", "vat_receivable_tb", "부가세대급금", 90, False, 0, 72091773, 72091773),
    ("trial_balance", "13500", "prepaid_tax_tb", "선납세금", 100, False, 40620, 40620, 0),
    ("trial_balance", "13700", "stt_short_term_tb", "주.임.종단기채권", 110, False, 0, 100328000, 100328000),
    ("trial_balance", None, "inventory_tb", "<재고자산>", 120, True, 35696395, 257055479, 221359084),
    ("trial_balance", "14600", "merchandise_tb", "상품", 130, False, 35696395, 257055479, 221359084),
    ("trial_balance", None, "noncurrent_assets_tb", "비유동자산", 140, True, 216636365, 381483171, 164846806),
    ("trial_balance", None, "investment_tb", "<투자자산>", 150, True, 0, 139766806, 139766806),
    ("trial_balance", "17600", "long_term_loan_tb", "장기대여금", 160, False, 0, 139766806, 139766806),
    ("trial_balance", None, "tangible_tb", "<유형자산>", 170, True, 116436365, 116436365, 0),
    ("trial_balance", "20800", "equipment_tb", "비품", 180, False, 36436365, 36436365, 0),
    ("trial_balance", "21900", "facility_tb", "시설장치", 190, False, 80000000, 80000000, 0),
    ("trial_balance", None, "other_noncurrent_tb", "<기타비유동자산>", 200, True, 100200000, 125280000, 25080000),
    ("trial_balance", "23200", "lease_deposit_tb", "임차보증금", 210, False, 100200000, 125280000, 25080000),
    # 부채 영역
    ("trial_balance", None, "current_liab_tb", "유동부채", 300, True, 0, 1448510180, 1549434171),
    ("trial_balance", "25100", "ap_tb", "외상매입금", 310, False, 0, 563506428, 617760362),
    ("trial_balance", "25400", "withholding_tb", "예수금", 320, False, 0, 30210560, 34279730),
    ("trial_balance", "25500", "vat_payable_tb", "부가세예수금", 330, False, 0, 3065451, 3065451),
    ("trial_balance", "26200", "accrued_expense_tb", "미지급비용", 340, False, 0, 556148267, 598749154),
    ("trial_balance", "26400", "accrued_salary_tb", "미지급급여", 350, False, 0, 295579474, 295579474),
    ("trial_balance", None, "noncurrent_liab_tb", "비유동부채", 360, True, 0, 0, 680000000),
    ("trial_balance", "30300", "stt_long_term_borrow_tb", "주.임.종장기차입금", 370, False, 0, 0, 130000000),
    ("trial_balance", "30400", "conditional_equity_tb", "조건부지분인수계약부채", 380, False, 0, 0, 550000000),
    # 자본 영역
    ("trial_balance", None, "capital_stock_tb", "자본금", 400, True, 0, 303602000, 607204000),
    ("trial_balance", "33100", "capital_stock_acct_tb", "자본금", 410, False, 0, 303602000, 607204000),
    ("trial_balance", None, "capital_surplus_tb", "자본잉여금", 420, True, 0, 0, 761393660),
    ("trial_balance", "34100", "share_premium_tb", "주식발행초과금", 430, False, 0, 0, 761393660),
    ("trial_balance", None, "retained_tb", "이익잉여금", 440, True, 1123775282, 2269053286, 1145278004),
    ("trial_balance", "37700", "carry_deficit_tb", "이월결손금", 450, False, 0, 1145278004, 21502722),
    ("trial_balance", "37800", "unappropriated_tb", "미처리결손금", 460, False, 1123775282, 1123775282, 0),
    ("trial_balance", None, "income_summary_tb", "손익", 470, True, 0, 1369383772, 1369383772),
    # 손익 영역
    ("trial_balance", None, "revenue_tb", "매출", 500, True, 0, 244205637, 244205637),
    ("trial_balance", "40100", "merch_sales_tb", "상품매출", 510, False, 0, 254696544, 254696544),
    ("trial_balance", "40400", "returns_tb", "매출환입및에누리", 520, False, 0, 39581816, 39581816),
    ("trial_balance", "41200", "service_sales_tb", "서비스매출", 530, False, 0, 29090909, 29090909),
    ("trial_balance", None, "cogs_tb", "매출원가", 540, True, 0, 221359084, 221359084),
    ("trial_balance", "45100", "merch_cogs_tb", "상품매출원가", 550, False, 0, 221359084, 221359084),
    ("trial_balance", None, "sga_tb", "판매관리비", 560, True, 0, 1148069743, 1148069743),
    ("trial_balance", "80100", "salaries_tb", "직원급여", 570, False, 0, 285330258, 285330258),
    ("trial_balance", "81100", "welfare_tb", "복리후생비", 580, False, 0, 110589671, 110589671),
    ("trial_balance", "81200", "travel_tb", "여비교통비", 590, False, 0, 129703882, 129703882),
    ("trial_balance", "81300", "entertainment_tb", "접대비(기업업무추진비)", 600, False, 0, 4255107, 4255107),
    ("trial_balance", "81700", "tax_tb", "세금과공과금", 610, False, 0, 2475080, 2475080),
    ("trial_balance", "81900", "rent_tb", "지급임차료", 620, False, 0, 68838490, 68838490),
    ("trial_balance", "82100", "insurance_tb", "보험료", 630, False, 0, 22714950, 22714950),
    ("trial_balance", "82400", "delivery_tb", "운반비", 640, False, 0, 8855388, 8855388),
    ("trial_balance", "82900", "office_tb", "사무용품비", 650, False, 0, 8498203, 8498203),
    ("trial_balance", "83000", "consumables_tb", "소모품비", 660, False, 0, 37754173, 37754173),
    ("trial_balance", "83100", "service_fee_tb", "지급수수료", 670, False, 0, 214852346, 214852346),
    ("trial_balance", "83300", "advertising_tb", "광고선전비", 680, False, 0, 254202195, 254202195),
    ("trial_balance", None, "non_op_income_tb", "영업외수익", 690, True, 0, 22905575, 22905575),
    ("trial_balance", "90100", "interest_tb", "이자수익", 700, False, 0, 278816, 278816),
    ("trial_balance", "91000", "fx_gain_tb", "외환차익", 710, False, 0, 2918194, 2918194),
    ("trial_balance", "91100", "subsidy_tb", "국고보조금수익", 720, False, 0, 19050286, 19050286),
    ("trial_balance", "93000", "misc_income_tb", "잡이익", 730, False, 0, 658279, 658279),
    ("trial_balance", None, "non_op_expense_tb", "영업외비용", 740, True, 0, 745377, 745377),
    ("trial_balance", "95300", "misc_loss_tb", "잡손실", 750, False, 0, 745377, 745377),
    # 합계
    ("trial_balance", None, "grand_total_tb", "합계", 800, True, 1845919651, 11298043973, 11298043973),
]

ALL_LINES = BS_LINES + PL_LINES + DT_LINES + TB_LINES


def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")

        # 기존 statement 있는지 확인
        cur.execute(
            """
            SELECT id FROM financial_statements
            WHERE entity_id = %s AND fiscal_year = %s AND start_month = %s AND end_month = %s
              AND is_consolidated = false
            """,
            [ENTITY_ID, FISCAL_YEAR, START_MONTH, END_MONTH],
        )
        existing = cur.fetchone()
        if existing:
            stmt_id = existing[0]
            print(f"기존 statement_id={stmt_id} 갱신 (line_items 삭제 후 재생성)")
            cur.execute(
                "DELETE FROM financial_statement_line_items WHERE statement_id = %s",
                [stmt_id],
            )
        else:
            cur.execute(
                """
                INSERT INTO financial_statements
                    (entity_id, fiscal_year, ki_num, start_month, end_month, is_consolidated, status, notes)
                VALUES (%s, %s, %s, %s, %s, false, 'finalized', %s)
                RETURNING id
                """,
                [ENTITY_ID, FISCAL_YEAR, KI_NUM, START_MONTH, END_MONTH,
                 "2025년 K-GAAP 확정 결산자료 (회계법인 제공) — manual import"],
            )
            stmt_id = cur.fetchone()[0]
            print(f"신규 statement_id={stmt_id} 생성")

        # line_items 일괄 INSERT
        for line in ALL_LINES:
            (st, code, key, label, order, is_header, amt, debit, credit) = line
            cur.execute(
                """
                INSERT INTO financial_statement_line_items
                    (statement_id, statement_type, account_code, line_key, label,
                     sort_order, is_section_header,
                     auto_amount, auto_debit, auto_credit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [stmt_id, st, code, key, label, order, is_header, amt, debit, credit],
            )

        conn.commit()
        cur.close()

        print(f"✓ {len(ALL_LINES)} line_items 입력 완료 (statement_id={stmt_id})")
        print(f"  - BS: {len(BS_LINES)} lines")
        print(f"  - PL: {len(PL_LINES)} lines")
        print(f"  - DT: {len(DT_LINES)} lines")
        print(f"  - TB: {len(TB_LINES)} lines")

    except Exception as e:
        conn.rollback()
        print(f"✗ 실패: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

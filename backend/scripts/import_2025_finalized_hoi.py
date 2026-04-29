"""HOI Inc. (entity_id=1) 2025년 US GAAP 확정 재무제표 import.

원본:
- BS: /Users/admin/Documents/HanahOneAll/한아원아메리카(HOI)/결산자료/25년 확정/[Hanah One Inc] BS_123125_Finalized_032026.pdf
- PL: /Users/admin/Documents/HanahOneAll/한아원아메리카(HOI)/결산자료/25년 확정/[Hanah One Inc] PL_123125_Finalized_031926.pdf

QBO Accrual Basis. USD 통화. Net Income -$53,007.11.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

ENTITY_ID = 1
FISCAL_YEAR = 2025
START_MONTH = 1
END_MONTH = 12
KI_NUM = 2  # 2nd year (HOI 도 2기)

# (statement_type, account_code, line_key, label, sort_order, is_section_header, auto_amount)
# USD 단위. 음수는 expense/loss/contra-asset

BS_LINES = [
    # ─ ASSETS ─────────────────────────────────────
    ("balance_sheet", None, "assets_header", "Assets", 10, True, 0),
    ("balance_sheet", None, "current_assets_header", "  Current Assets", 20, True, 288920.25),
    ("balance_sheet", None, "bank_accounts_header", "    Bank Accounts", 30, True, 144362.71),
    ("balance_sheet", None, "mercury_checking", "      Mercury Checking (3509) - 1", 40, False, 144362.71),
    ("balance_sheet", None, "other_current_header", "    Other Current Assets", 50, True, 144557.54),
    ("balance_sheet", None, "channel_clearing_header", "      Channel Clearing Account", 60, True, 2732.36),
    ("balance_sheet", None, "amazon_clearing", "        Amazon - US Clearing Account", 70, False, 26.40),
    ("balance_sheet", None, "shopify_clearing", "        Shopify - 3exks1-rc 3 Clearing Account", 80, False, 172.55),
    ("balance_sheet", None, "shopify_other_payment", "        Shopify - 3exks1-rc 3 Other Payment Gateway", 90, False, 156.07),
    ("balance_sheet", None, "shopify_paypal", "        Shopify - 3exks1-rc 3 PayPal Clearing", 100, False, 87.46),
    ("balance_sheet", None, "tiktok_clearing", "        TikTok Clearing Account", 110, False, 2289.88),
    ("balance_sheet", None, "inventory_asset", "      Inventory Asset", 120, False, 141825.18),
    ("balance_sheet", None, "other_assets_header", "  Other Assets", 130, True, 136652.00),
    ("balance_sheet", None, "industrious_deposit", "    Industrious Office Security Deposit", 140, False, 2472.00),
    ("balance_sheet", None, "investment_subsidiary", "    Investment in Subsidiary", 150, False, 134180.00),
    ("balance_sheet", None, "total_assets", "  Total Assets", 160, True, 425572.25),

    # ─ LIABILITIES ─────────────────────────────────
    ("balance_sheet", None, "liabilities_header", "Liabilities and Equity", 200, True, 0),
    ("balance_sheet", None, "liab_subhead", "Liabilities", 210, True, 0),
    ("balance_sheet", None, "current_liab_header", "  Current Liabilities", 220, True, 93.86),
    ("balance_sheet", None, "ap_header", "    Accounts Payable", 230, True, 0),
    ("balance_sheet", None, "ap_usd", "      Accounts Payable (A/P)", 240, False, 0),
    ("balance_sheet", None, "ap_eur", "      Accounts Payable (A/P) - EUR", 250, False, 0),
    ("balance_sheet", None, "credit_cards_header", "    Credit Cards", 260, True, 0),
    ("balance_sheet", None, "mercury_credit", "      Mercury Credit - 1", 270, False, 0),
    ("balance_sheet", None, "other_current_liab_header", "    Other Current Liabilities", 280, True, 93.86),
    ("balance_sheet", None, "channel_sales_tax_header", "      Channel Sales Tax Payable", 290, True, 93.86),
    ("balance_sheet", None, "amazon_sales_tax", "        Amazon Sales Sales Tax", 300, False, 0),
    ("balance_sheet", None, "shopify_sales_tax", "        Shopify Sales Tax", 310, False, 93.86),
    ("balance_sheet", None, "longterm_liab_header", "  Long-term Liabilities", 320, True, 125305.50),
    ("balance_sheet", None, "loan_from_hocl", "    Loan from HOCL", 330, False, 125305.50),
    ("balance_sheet", None, "total_liabilities", "  Total Liabilities", 340, True, 125399.36),

    # ─ EQUITY ─────────────────────────────────────
    ("balance_sheet", None, "equity_header", "Equity", 400, True, 0),
    ("balance_sheet", None, "additional_paid_in", "  Additional Paid-In Capital", 410, False, 219000.00),
    ("balance_sheet", None, "capital_stock", "  Capital Stock", 420, False, 134180.00),
    ("balance_sheet", None, "retained_earnings_header", "  Retained Earnings", 430, True, 0),
    ("balance_sheet", None, "net_income_2025", "    Net Income", 440, False, -53007.11),
    ("balance_sheet", None, "total_equity", "  Total Equity", 450, True, 300172.89),
    ("balance_sheet", None, "total_liab_equity", "Total Liabilities and Equity", 460, True, 425572.25),
]

PL_LINES = [
    # ─ INCOME ─────────────────────────────────────
    ("income_statement", None, "income_header", "Income", 10, True, 10584.20),
    ("income_statement", None, "channel_refund_adj_header", "  Channel Refund Adjustment", 20, True, 0),
    ("income_statement", None, "shopify_refund_adj", "    Shopify Refund Adjustment", 30, False, 0),
    ("income_statement", None, "channel_sales_header", "  Channel Sales", 40, True, 10584.20),
    ("income_statement", None, "amazon_sales", "    Amazon Sales", 50, False, 2482.00),
    ("income_statement", None, "shopify_sales_header", "    Shopify Sales", 60, True, 5569.10),
    ("income_statement", None, "shopify_sales_main", "      Shopify Sales", 70, False, 5569.10),
    ("income_statement", None, "shopify_discount", "      Shopify Discount", 80, False, 0),
    ("income_statement", None, "tiktok_sales", "    Tiktok Sales", 90, False, 2533.10),
    ("income_statement", None, "channel_shipping_header", "  Channel Shipping Income", 100, True, 0),
    ("income_statement", None, "amazon_shipping", "    Amazon Shipping Income", 110, False, 0),
    ("income_statement", None, "shopify_shipping", "    Shopify Shipping Income", 120, False, 0),
    ("income_statement", None, "total_income", "  Total Income", 130, True, 10584.20),

    # ─ COGS ───────────────────────────────────────
    ("income_statement", None, "cogs_header", "Cost of Goods Sold", 200, True, 4091.18),
    ("income_statement", None, "channel_selling_fees_header", "  Channel Selling Fees", 210, True, 1018.42),
    ("income_statement", None, "amazon_selling_fees", "    Amazon Selling Fees", 220, False, 336.36),
    ("income_statement", None, "shopify_selling_fees", "    Shopify Selling Fees", 230, False, 438.84),
    ("income_statement", None, "tiktok_selling_fees", "    TikTok Selling Fees", 240, False, 243.22),
    ("income_statement", None, "cogs_main", "  Cost of Goods Sold", 250, False, 3072.76),
    ("income_statement", None, "z_inventory", "  z-Inventory (Increase/Decrease)", 260, False, 0),
    ("income_statement", None, "gross_profit", "Gross Profit", 270, True, 6493.02),

    # ─ EXPENSES ───────────────────────────────────
    ("income_statement", None, "expenses_header", "Expenses", 300, True, 59509.13),
    ("income_statement", None, "admin_legal_header", "  Administrative Expense - Legal & Professional Fees", 310, True, 6259.38),
    ("income_statement", None, "admin_legal_main", "    Administrative Expense - Legal & Professional Fees (main)", 320, False, 2230.00),
    ("income_statement", None, "bank_charges", "    Bank Service Charges", 330, False, 125.20),
    ("income_statement", None, "gdrp_rep", "    GDRP Representative Fees", 340, False, 835.27),
    ("income_statement", None, "license_permit", "    License and Permit", 350, False, 5.00),
    ("income_statement", None, "registered_agent", "    Registered Agent Fees", 360, False, 2191.11),
    ("income_statement", None, "telephone", "    Telephone Expense", 370, False, 872.80),
    ("income_statement", None, "channel_subscription_header", "  Channel Subscription Fees", 380, True, 636.44),
    ("income_statement", None, "channel_sub_main", "    Channel Subscription Fees (main)", 390, False, 436.49),
    ("income_statement", None, "amazon_sub_fees", "    Amazon Subscription Fees", 400, False, 199.95),
    ("income_statement", None, "general_dues_header", "  General Expense - Dues & Subscription", 410, True, 412.99),
    ("income_statement", None, "dues_subs", "    Dues and subscriptions", 420, False, 112.99),
    ("income_statement", None, "shopify_api_3pl", "    Shopify API Integration (3PL)", 430, False, 300.00),
    ("income_statement", None, "general_insurance_header", "  General Expense - Insurance", 440, True, 650.00),
    ("income_statement", None, "customs_bond", "    Annual Customs Bond Fee (3PL)", 450, False, 650.00),
    ("income_statement", None, "general_rent_header", "  General Expense - Rent/Lease", 460, True, 6727.00),
    ("income_statement", None, "office_rent", "    Office Rent-Beverly Hills", 470, False, 6727.00),
    ("income_statement", None, "general_supplies_header", "  General Expenses - Supplies & Materials", 480, True, 282.66),
    ("income_statement", None, "office_supplies", "    Office Supplies Purchase", 490, False, 282.66),
    ("income_statement", None, "selling_3pl_header", "  Selling Expense - 3PL", 500, True, 15694.64),
    ("income_statement", None, "selling_3pl_main", "    Selling Expense - 3PL (main)", 510, False, 12034.01),
    ("income_statement", None, "bol", "    BOL", 520, False, 775.00),
    ("income_statement", None, "fulfillment", "    Fulfillment", 530, False, 1535.63),
    ("income_statement", None, "storage", "    Storage", 540, False, 1350.00),
    ("income_statement", None, "selling_advertising_header", "  Selling Expense - Advertising", 550, True, 12421.81),
    ("income_statement", None, "selling_adv_main", "    Selling Expense - Advertising (main)", 560, False, 95.00),
    ("income_statement", None, "awareness_creator", "    Awareness Ad Expense-Creator", 570, False, 5516.97),
    ("income_statement", None, "paid_meta", "    Paid Advertising-Meta", 580, False, 2994.22),
    ("income_statement", None, "paid_tiktok", "    Paid Advertising-TikTok", 590, False, 1693.25),
    ("income_statement", None, "search_google", "    Search Advertising-Google", 600, False, 2122.37),
    ("income_statement", None, "selling_marketing_header", "  Selling Expense - Marketing", 610, True, 16424.21),
    ("income_statement", None, "photoshoot", "    Photoshoot", 620, False, 7010.21),
    ("income_statement", None, "sample_expense", "    Sample Expense", 630, False, 9414.00),
    ("income_statement", None, "selling_merchant_header", "  Selling Expense - Merchant Fees", 640, True, 0),
    ("income_statement", None, "shopify_fees", "    Shopify Fees", 650, False, 0),
    ("income_statement", None, "total_expenses", "  Total Expenses", 660, True, 59509.13),

    # ─ NET ────────────────────────────────────────
    ("income_statement", None, "net_operating_income", "Net Operating Income", 700, True, -53016.11),

    ("income_statement", None, "other_income_header", "Other Income", 710, True, 13.39),
    ("income_statement", None, "other_income_main", "  Other Income", 720, False, 13.39),
    ("income_statement", None, "other_expenses_header", "Other Expenses", 730, True, 4.39),
    ("income_statement", None, "unrealized_gain_loss_header", "  Unrealized Gain or Loss", 740, True, 4.39),
    ("income_statement", None, "exchange_gain_loss", "    Exchange Gain or Loss", 750, False, 4.39),
    ("income_statement", None, "net_other_income", "Net Other Income", 760, True, 9.00),

    ("income_statement", None, "net_income", "Net Income", 800, True, -53007.11),
]

ALL_LINES = BS_LINES + PL_LINES


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
                    (entity_id, fiscal_year, ki_num, start_month, end_month, is_consolidated, status, base_currency, notes)
                VALUES (%s, %s, %s, %s, %s, false, 'finalized', 'USD', %s)
                RETURNING id
                """,
                [ENTITY_ID, FISCAL_YEAR, KI_NUM, START_MONTH, END_MONTH,
                 "HOI 2025 US GAAP Accrual Basis — manual import from QBO PDF (BS 03/20, PL 03/19)"],
            )
            stmt_id = cur.fetchone()[0]
            print(f"신규 statement_id={stmt_id} 생성")

        # line_items 일괄 INSERT
        for line in ALL_LINES:
            (st, code, key, label, order, is_header, amt) = line
            cur.execute(
                """
                INSERT INTO financial_statement_line_items
                    (statement_id, statement_type, account_code, line_key, label,
                     sort_order, is_section_header,
                     auto_amount, auto_debit, auto_credit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0)
                """,
                [stmt_id, st, code, key, label, order, is_header, amt],
            )

        conn.commit()
        cur.close()

        print(f"✓ {len(ALL_LINES)} line_items 입력 완료 (statement_id={stmt_id})")
        print(f"  - BS: {len(BS_LINES)} lines (Total Assets $425,572.25)")
        print(f"  - PL: {len(PL_LINES)} lines (Net Income -$53,007.11)")

    except Exception as e:
        conn.rollback()
        print(f"✗ 실패: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

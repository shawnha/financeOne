"""HOI Inc. Chart of Accounts (2025-12-31 Finalized).

Source: BS_123125_Finalized_032026.pdf + PL_123125_Finalized_031926.pdf
QuickBooks Online 양식 (Accrual Basis).

각 entry: (code, name, category, normal_side, parent_code, sort_order)
- code: 'HOI-BS-####' / 'HOI-PL-####' — 카테고리 prefix + 4자리 (BS=1xxx 자산/2xxx 부채/3xxx 자본, PL=4xxx 수익/5xxx 비용)
- parent_code: app-level 트리. NULL=루트 카테고리. (parent_code FK 는 마이그레이션에서 제거됨)
"""

# (code, name, category, normal_side, parent_code, sort_order)
HOI_COA: list[tuple[str, str, str, str, str | None, int]] = [
    # ── BS Assets ──────────────────────────────────────────────────────────
    ("HOI-BS-1000", "Assets",                                          "Assets",      "debit",  None,           1000),
    ("HOI-BS-1010", "Current Assets",                                  "Assets",      "debit",  "HOI-BS-1000",  1010),
    ("HOI-BS-1011", "Mercury Checking (3509) - 1",                     "Assets",      "debit",  "HOI-BS-1010",  1011),
    ("HOI-BS-1020", "Channel Clearing Account",                        "Assets",      "debit",  "HOI-BS-1010",  1020),
    ("HOI-BS-1021", "Amazon - US Clearing Account",                    "Assets",      "debit",  "HOI-BS-1020",  1021),
    ("HOI-BS-1022", "Shopify - 3exks1-rc 3 Clearing Account",          "Assets",      "debit",  "HOI-BS-1020",  1022),
    ("HOI-BS-1023", "Shopify - 3exks1-rc 3 Other Payment Gateway Clearing Account", "Assets", "debit", "HOI-BS-1020", 1023),
    ("HOI-BS-1024", "Shopify - 3exks1-rc 3 PayPal Clearing Account",   "Assets",      "debit",  "HOI-BS-1020",  1024),
    ("HOI-BS-1025", "TikTok Clearing Account",                         "Assets",      "debit",  "HOI-BS-1020",  1025),
    ("HOI-BS-1030", "Inventory Asset",                                 "Assets",      "debit",  "HOI-BS-1010",  1030),
    ("HOI-BS-1100", "Other Assets",                                    "Assets",      "debit",  "HOI-BS-1000",  1100),
    ("HOI-BS-1101", "Industrious Office Security Deposit",             "Assets",      "debit",  "HOI-BS-1100",  1101),
    ("HOI-BS-1102", "Investment in Subsidiary",                        "Assets",      "debit",  "HOI-BS-1100",  1102),

    # ── BS Liabilities ─────────────────────────────────────────────────────
    ("HOI-BS-2000", "Liabilities",                                     "Liabilities", "credit", None,           2000),
    ("HOI-BS-2010", "Current Liabilities",                             "Liabilities", "credit", "HOI-BS-2000",  2010),
    ("HOI-BS-2011", "Accounts Payable",                                "Liabilities", "credit", "HOI-BS-2010",  2011),
    ("HOI-BS-2012", "Accounts Payable (A/P)",                          "Liabilities", "credit", "HOI-BS-2011",  2012),
    ("HOI-BS-2013", "Accounts Payable (A/P) - EUR",                    "Liabilities", "credit", "HOI-BS-2011",  2013),
    ("HOI-BS-2020", "Credit Cards",                                    "Liabilities", "credit", "HOI-BS-2010",  2020),
    ("HOI-BS-2021", "Mercury Credit - 1",                              "Liabilities", "credit", "HOI-BS-2020",  2021),
    ("HOI-BS-2030", "Channel Sales Tax Payable",                       "Liabilities", "credit", "HOI-BS-2010",  2030),
    ("HOI-BS-2031", "Amazon Sales Sales Tax",                          "Liabilities", "credit", "HOI-BS-2030",  2031),
    ("HOI-BS-2032", "Shopify Sales Tax",                               "Liabilities", "credit", "HOI-BS-2030",  2032),
    ("HOI-BS-2100", "Long-term Liabilities",                           "Liabilities", "credit", "HOI-BS-2000",  2100),
    ("HOI-BS-2101", "Loan from HOCL",                                  "Liabilities", "credit", "HOI-BS-2100",  2101),

    # ── BS Equity ──────────────────────────────────────────────────────────
    ("HOI-BS-3000", "Equity",                                          "Equity",      "credit", None,           3000),
    ("HOI-BS-3010", "Additional Paid-In Capital",                      "Equity",      "credit", "HOI-BS-3000",  3010),
    ("HOI-BS-3020", "Capital Stock",                                   "Equity",      "credit", "HOI-BS-3000",  3020),
    ("HOI-BS-3030", "Retained Earnings",                               "Equity",      "credit", "HOI-BS-3000",  3030),
    ("HOI-BS-3031", "Net Income",                                      "Equity",      "credit", "HOI-BS-3030",  3031),

    # ── PL Income ──────────────────────────────────────────────────────────
    ("HOI-PL-4000", "Income",                                          "Revenue",     "credit", None,           4000),
    ("HOI-PL-4010", "Channel Refund Adjustment",                       "Revenue",     "credit", "HOI-PL-4000",  4010),
    ("HOI-PL-4011", "Shopify Refund Adjustment",                       "Revenue",     "credit", "HOI-PL-4010",  4011),
    ("HOI-PL-4020", "Channel Sales",                                   "Revenue",     "credit", "HOI-PL-4000",  4020),
    ("HOI-PL-4021", "Amazon Sales",                                    "Revenue",     "credit", "HOI-PL-4020",  4021),
    ("HOI-PL-4022", "Shopify Sales",                                   "Revenue",     "credit", "HOI-PL-4020",  4022),
    ("HOI-PL-4023", "Shopify Discount",                                "Revenue",     "credit", "HOI-PL-4022",  4023),
    ("HOI-PL-4024", "Tiktok Sales",                                    "Revenue",     "credit", "HOI-PL-4020",  4024),
    ("HOI-PL-4030", "Channel Shipping Income",                         "Revenue",     "credit", "HOI-PL-4000",  4030),
    ("HOI-PL-4031", "Amazon Shipping Income",                          "Revenue",     "credit", "HOI-PL-4030",  4031),
    ("HOI-PL-4032", "Shopify Shipping Income",                         "Revenue",     "credit", "HOI-PL-4030",  4032),

    # ── PL COGS ────────────────────────────────────────────────────────────
    ("HOI-PL-5000", "Cost of Goods Sold",                              "Expense",     "debit",  None,           5000),
    ("HOI-PL-5010", "Channel Selling Fees",                            "Expense",     "debit",  "HOI-PL-5000",  5010),
    ("HOI-PL-5011", "Amazon Selling Fees",                             "Expense",     "debit",  "HOI-PL-5010",  5011),
    ("HOI-PL-5012", "Shopify Selling Fees",                            "Expense",     "debit",  "HOI-PL-5010",  5012),
    ("HOI-PL-5013", "TikTok Selling Fees",                             "Expense",     "debit",  "HOI-PL-5010",  5013),
    ("HOI-PL-5020", "Cost of Goods Sold (line)",                       "Expense",     "debit",  "HOI-PL-5000",  5020),
    ("HOI-PL-5030", "z-Inventory (Increase/Decrease)",                 "Expense",     "debit",  "HOI-PL-5000",  5030),

    # ── PL Operating Expenses ──────────────────────────────────────────────
    ("HOI-PL-6000", "Expenses",                                        "Expense",     "debit",  None,           6000),
    ("HOI-PL-6010", "Administrative Expense - Legal & Professional Fees", "Expense",  "debit",  "HOI-PL-6000",  6010),
    ("HOI-PL-6011", "Bank Service Charges",                            "Expense",     "debit",  "HOI-PL-6010",  6011),
    ("HOI-PL-6012", "GDRP Representative Fees",                        "Expense",     "debit",  "HOI-PL-6010",  6012),
    ("HOI-PL-6013", "License and Permit",                              "Expense",     "debit",  "HOI-PL-6010",  6013),
    ("HOI-PL-6014", "Registered Agent Fees",                           "Expense",     "debit",  "HOI-PL-6010",  6014),
    ("HOI-PL-6015", "Telephone Expense",                               "Expense",     "debit",  "HOI-PL-6010",  6015),
    ("HOI-PL-6020", "Channel Subscription Fees",                       "Expense",     "debit",  "HOI-PL-6000",  6020),
    ("HOI-PL-6021", "Amazon Subscription Fees",                        "Expense",     "debit",  "HOI-PL-6020",  6021),
    ("HOI-PL-6030", "General Expense - Dues & Subscription",           "Expense",     "debit",  "HOI-PL-6000",  6030),
    ("HOI-PL-6031", "Dues and subscriptions",                          "Expense",     "debit",  "HOI-PL-6030",  6031),
    ("HOI-PL-6032", "Shopify API Integration (3PL)",                   "Expense",     "debit",  "HOI-PL-6030",  6032),
    ("HOI-PL-6040", "General Expense - Insurance",                     "Expense",     "debit",  "HOI-PL-6000",  6040),
    ("HOI-PL-6041", "Annual Customs Bond Fee (3PL)",                   "Expense",     "debit",  "HOI-PL-6040",  6041),
    ("HOI-PL-6050", "General Expense - Rent/Lease",                    "Expense",     "debit",  "HOI-PL-6000",  6050),
    ("HOI-PL-6051", "Office Rent-Beverly Hills",                       "Expense",     "debit",  "HOI-PL-6050",  6051),
    ("HOI-PL-6060", "General Expenses - Supplies & Materials",         "Expense",     "debit",  "HOI-PL-6000",  6060),
    ("HOI-PL-6061", "Office Supplies Purchase",                        "Expense",     "debit",  "HOI-PL-6060",  6061),
    ("HOI-PL-6070", "Selling Expense - 3PL",                           "Expense",     "debit",  "HOI-PL-6000",  6070),
    ("HOI-PL-6071", "BOL",                                             "Expense",     "debit",  "HOI-PL-6070",  6071),
    ("HOI-PL-6072", "Fulfillment",                                     "Expense",     "debit",  "HOI-PL-6070",  6072),
    ("HOI-PL-6073", "Storage",                                         "Expense",     "debit",  "HOI-PL-6070",  6073),
    ("HOI-PL-6080", "Selling Expense - Advertising",                   "Expense",     "debit",  "HOI-PL-6000",  6080),
    ("HOI-PL-6081", "Awareness Ad Expense-Creator",                    "Expense",     "debit",  "HOI-PL-6080",  6081),
    ("HOI-PL-6082", "Paid Advertising-Meta",                           "Expense",     "debit",  "HOI-PL-6080",  6082),
    ("HOI-PL-6083", "Paid Advertising-TikTok",                         "Expense",     "debit",  "HOI-PL-6080",  6083),
    ("HOI-PL-6084", "Search Advertising-Google",                       "Expense",     "debit",  "HOI-PL-6080",  6084),
    ("HOI-PL-6090", "Selling Expense - Marketing",                     "Expense",     "debit",  "HOI-PL-6000",  6090),
    ("HOI-PL-6091", "Photoshoot",                                      "Expense",     "debit",  "HOI-PL-6090",  6091),
    ("HOI-PL-6092", "Sample Expense",                                  "Expense",     "debit",  "HOI-PL-6090",  6092),
    ("HOI-PL-6100", "Selling Expense - Merchant Fees",                 "Expense",     "debit",  "HOI-PL-6000",  6100),
    ("HOI-PL-6101", "Shopify Fees",                                    "Expense",     "debit",  "HOI-PL-6100",  6101),

    # ── PL Other Income/Expenses ───────────────────────────────────────────
    ("HOI-PL-7000", "Other Income",                                    "Revenue",     "credit", None,           7000),
    ("HOI-PL-7010", "Other Income (line)",                             "Revenue",     "credit", "HOI-PL-7000",  7010),
    ("HOI-PL-8000", "Other Expenses",                                  "Expense",     "debit",  None,           8000),
    ("HOI-PL-8010", "Unrealized Gain or Loss",                         "Expense",     "debit",  "HOI-PL-8000",  8010),
    ("HOI-PL-8011", "Exchange Gain or Loss",                           "Expense",     "debit",  "HOI-PL-8010",  8011),
]

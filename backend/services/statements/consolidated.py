"""연결재무제표 및 전체 재무제표 일괄 생성."""

from datetime import date, timedelta
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from backend.services.gaap_conversion_service import convert_kgaap_to_usgaap
from backend.services.cta_service import translate_entity_to_usd, translate_entity_to_krw
from backend.services.intercompany_service import get_eliminations
from .helpers import _get_or_create_statement, _insert_line_item
from .balance_sheet import generate_balance_sheet
from .income_statement import generate_income_statement
from .cash_flow import generate_cash_flow_statement
from .trial_balance import generate_trial_balance
from .deficit import generate_deficit_treatment
from .qbo_reports import generate_qbo_balance_sheet, generate_qbo_income_statement


def _entity_currency(cur, entity_id: int) -> str:
    cur.execute("SELECT currency FROM entities WHERE id = %s", [entity_id])
    row = cur.fetchone()
    return (row[0] if row else "KRW").upper()


# --- 전체 재무제표 생성 ---

def generate_all_statements(
    conn: PgConnection,
    entity_id: int,
    fiscal_year: int,
    start_month: int = 1,
    end_month: int = 12,
) -> dict:
    """5종 재무제표 일괄 생성. financial_statement_line_items에 저장.

    HOI (USD) → QBO Report API 사용 (영어, US GAAP 양식).
    한국 entity (KRW) → 분개 기반 자동 생성 (한글, K-GAAP 양식).

    Returns:
        {"statement_id": int, "validation": {...per statement...}}
    """
    start_date = date(fiscal_year, start_month, 1)
    if end_month == 12:
        end_date = date(fiscal_year, 12, 31)
    else:
        end_date = date(fiscal_year, end_month + 1, 1) - timedelta(days=1)

    cur = conn.cursor()
    stmt_id = _get_or_create_statement(cur, entity_id, fiscal_year, start_month, end_month)

    # 기존 line_items 삭제 (재생성 안전)
    cur.execute(
        "DELETE FROM financial_statement_line_items WHERE statement_id = %s",
        [stmt_id],
    )

    currency = _entity_currency(cur, entity_id)
    use_qbo = currency == "USD"

    if use_qbo:
        # HOI (US GAAP) — QBO Report API 사용
        bs = generate_qbo_balance_sheet(conn, cur, stmt_id, entity_id, fiscal_year, end_date, start_date)
        inc = generate_qbo_income_statement(conn, cur, stmt_id, entity_id, start_date, end_date)
        # QBO 는 Cash Flow / Trial Balance / Deficit Treatment 제공 안함 → empty placeholder
        cf = {"opening_cash": 0.0, "cash_inflows": 0.0, "cash_outflows": 0.0,
              "net_cash": 0.0, "ending_cash": 0.0, "loop_valid": True}
        tb = {"total_debit": 0.0, "total_credit": 0.0, "is_balanced": True,
              "difference": 0.0, "account_count": 0}
        dt = {"prior_retained": 0.0, "net_income": float(inc.get("net_income", 0.0)),
              "ending_retained": 0.0, "is_deficit": False}
    else:
        # K-GAAP — 분개 기반 5종 자동 생성
        bs = generate_balance_sheet(conn, cur, stmt_id, entity_id, fiscal_year, end_date, start_date)
        inc = generate_income_statement(conn, cur, stmt_id, entity_id, start_date, end_date)
        cf = generate_cash_flow_statement(conn, cur, stmt_id, entity_id, start_date, end_date)
        tb = generate_trial_balance(conn, cur, stmt_id, entity_id, end_date)
        dt = generate_deficit_treatment(conn, cur, stmt_id, entity_id, fiscal_year, start_date, end_date)

    # base_currency 설정
    cur.execute(
        "UPDATE financial_statements SET base_currency = %s WHERE id = %s",
        [currency, stmt_id],
    )

    cur.close()

    return {
        "statement_id": stmt_id,
        "fiscal_year": fiscal_year,
        "start_month": start_month,
        "end_month": end_month,
        "base_currency": currency,
        "validation": {
            "balance_sheet": bs,
            "income_statement": inc,
            "cash_flow": cf,
            "trial_balance": tb,
            "deficit_treatment": dt,
        },
    }


# --- 연결재무제표 생성 ---

HOI_ENTITY_ID = 1  # 모회사


def _get_subsidiaries(cur, parent_id: int) -> list[int]:
    """재귀적으로 모든 자회사 ID 조회."""
    cur.execute(
        """
        WITH RECURSIVE subs AS (
            SELECT id FROM entities WHERE parent_id = %s
            UNION ALL
            SELECT e.id FROM entities e JOIN subs s ON e.parent_id = s.id
        )
        SELECT id FROM subs
        """,
        [parent_id],
    )
    return [row[0] for row in cur.fetchall()]


def _get_entity_currency(cur, entity_id: int) -> str:
    cur.execute("SELECT currency FROM entities WHERE id = %s", [entity_id])
    row = cur.fetchone()
    return row[0] if row else "KRW"


def generate_consolidated_statements(
    conn: PgConnection,
    fiscal_year: int,
    start_month: int = 1,
    end_month: int = 12,
    base_currency: str = "USD",
) -> dict:
    """연결재무제표 생성. base_currency='USD' 또는 'KRW'.

    USD 기준 (기본, US GAAP):
      1. HOI: K-GAAP → US GAAP 코드 변환만 (USD)
      2. HOK/HOR: GAAP 변환 + KRW→USD 환산 (CTA → AOCI 3300)

    KRW 기준 (K-GAAP):
      1. HOI: USD→KRW 환산 (CTA → 39200 해외사업환산손익)
      2. HOK/HOR: 그대로 (KRW)
      3. 코드 체계: K-GAAP standard_accounts.code 사용

    공통:
      - 합산
      - 내부거래 상계
      - 저장 (별도 ki_num 으로 USD/KRW 분리)
    """
    base_currency = base_currency.upper()
    if base_currency not in ("USD", "KRW"):
        raise ValueError(f"base_currency must be USD or KRW, got {base_currency}")

    start_date = date(fiscal_year, start_month, 1)
    if end_month == 12:
        end_date = date(fiscal_year, 12, 31)
    else:
        end_date = date(fiscal_year, end_month + 1, 1) - timedelta(days=1)

    cur = conn.cursor()

    # 자회사 탐색
    subsidiary_ids = _get_subsidiaries(cur, HOI_ENTITY_ID)
    all_entity_ids = [HOI_ENTITY_ID] + subsidiary_ids

    # ki_num 분기: USD=99, KRW=98 (단독 statement default=3 과 unique 충돌 방지)
    ki_num = 99 if base_currency == "USD" else 98

    # 연결 statement 헤더 생성
    cur.execute(
        """
        SELECT id FROM financial_statements
        WHERE entity_id = %s AND fiscal_year = %s
          AND start_month = %s AND end_month = %s
          AND is_consolidated = TRUE
          AND ki_num = %s
        """,
        [HOI_ENTITY_ID, fiscal_year, start_month, end_month, ki_num],
    )
    row = cur.fetchone()
    if row:
        stmt_id = row[0]
        cur.execute("DELETE FROM financial_statement_line_items WHERE statement_id = %s", [stmt_id])
        cur.execute("DELETE FROM consolidation_adjustments WHERE statement_id = %s", [stmt_id])
        cur.execute(
            "UPDATE financial_statements SET status = 'draft', base_currency = %s, updated_at = NOW() WHERE id = %s",
            [base_currency, stmt_id],
        )
    else:
        cur.execute(
            """
            INSERT INTO financial_statements
                (entity_id, fiscal_year, ki_num, start_month, end_month, is_consolidated, base_currency, status)
            VALUES (%s, %s, %s, %s, %s, TRUE, %s, 'draft')
            RETURNING id
            """,
            [HOI_ENTITY_ID, fiscal_year, ki_num, start_month, end_month, base_currency],
        )
        stmt_id = cur.fetchone()[0]

    # 각 법인별 잔액 수집 (target currency 기준)
    consolidated_balances: dict[str, dict] = {}  # code → {name, category, balance}
    cta_by_entity = {}
    entity_details = []

    # 카테고리 정규화 헬퍼 (USD vs KRW 양쪽 모두 처리)
    def _norm_cat(cat: str) -> str:
        if base_currency == "USD":
            mapping = {"자산": "Assets", "부채": "Liabilities", "자본": "Equity",
                       "수익": "Revenue", "비용": "Expenses",
                       "Income": "Revenue", "Expense": "Expenses",
                       "Cost of Goods Sold": "Expenses"}
            return mapping.get(cat, cat)
        else:
            mapping = {"Assets": "자산", "Liabilities": "부채", "Equity": "자본",
                       "Revenue": "수익", "Income": "수익",
                       "Expense": "비용", "Expenses": "비용",
                       "Cost of Goods Sold": "비용"}
            return mapping.get(cat, cat)

    for eid in all_entity_ids:
        currency = _get_entity_currency(cur, eid)

        if base_currency == "USD" and currency == "USD":
            # USD 모드 + HOI: GAAP 변환만
            balances = get_all_account_balances(conn, eid, to_date=end_date)
            period_balances = get_all_account_balances(conn, eid, from_date=start_date, to_date=end_date)
            usgaap_cum = convert_kgaap_to_usgaap(conn, balances)
            usgaap_per = convert_kgaap_to_usgaap(conn, period_balances)
            # A/L/E 는 누적, R/E 는 기간
            for b in usgaap_cum:
                cat = _norm_cat(b["us_gaap_category"])
                if cat not in ("Assets", "Liabilities", "Equity"):
                    continue
                code = b["us_gaap_code"]
                consolidated_balances.setdefault(code, {
                    "name": b["us_gaap_name"], "category": cat, "balance": Decimal("0"),
                })
                consolidated_balances[code]["balance"] += Decimal(str(b["balance"]))
            for b in usgaap_per:
                cat = _norm_cat(b["us_gaap_category"])
                if cat not in ("Revenue", "Expenses"):
                    continue
                code = b["us_gaap_code"]
                consolidated_balances.setdefault(code, {
                    "name": b["us_gaap_name"], "category": cat, "balance": Decimal("0"),
                })
                consolidated_balances[code]["balance"] += Decimal(str(b["balance"]))
            entity_details.append({"entity_id": eid, "currency": "USD", "cta": 0})

        elif base_currency == "USD" and currency == "KRW":
            # USD 모드 + 한국 법인: K-GAAP→US GAAP + KRW→USD 환산
            try:
                translation = translate_entity_to_usd(conn, eid, fiscal_year, start_date, end_date)
                for tb in translation["translated_balances"]:
                    code = tb["us_gaap_code"]
                    cat = _norm_cat(tb["category"])
                    consolidated_balances.setdefault(code, {
                        "name": tb["us_gaap_name"], "category": cat, "balance": Decimal("0"),
                    })
                    consolidated_balances[code]["balance"] += Decimal(str(tb["usd_balance"]))

                cta_amount = Decimal(str(translation["cta_amount"]))
                cta_by_entity[eid] = float(cta_amount)
                consolidated_balances.setdefault("3300", {
                    "name": "Accumulated Other Comprehensive Income (CTA)",
                    "category": "Equity", "balance": Decimal("0"),
                })
                consolidated_balances["3300"]["balance"] += cta_amount
                cur.execute(
                    """INSERT INTO consolidation_adjustments
                        (statement_id, adjustment_type, account_code, description,
                         original_amount, adjusted_amount, source_entity_id, exchange_rate)
                    VALUES (%s, 'cta', '3300', %s, 0, %s, %s, %s)""",
                    [stmt_id, f"CTA for entity {eid}", float(cta_amount), eid,
                     translation["rates_used"]["closing"]],
                )
                entity_details.append({"entity_id": eid, "currency": "KRW",
                                       "cta": float(cta_amount), "rates": translation["rates_used"]})
            except Exception as e:
                entity_details.append({"entity_id": eid, "currency": "KRW", "error": str(e)})

        elif base_currency == "KRW" and currency == "KRW":
            # KRW 모드 + 한국 법인: 환산 불필요, K-GAAP 코드 그대로
            balances = get_all_account_balances(conn, eid, to_date=end_date)
            period_balances = get_all_account_balances(conn, eid, from_date=start_date, to_date=end_date)
            for b in balances:
                cat = _norm_cat(b["category"])
                if cat not in ("자산", "부채", "자본"):
                    continue
                code = b["code"]
                consolidated_balances.setdefault(code, {
                    "name": b["name"], "category": cat, "balance": Decimal("0"),
                })
                consolidated_balances[code]["balance"] += Decimal(str(b["balance"]))
            for b in period_balances:
                cat = _norm_cat(b["category"])
                if cat not in ("수익", "비용"):
                    continue
                code = b["code"]
                consolidated_balances.setdefault(code, {
                    "name": b["name"], "category": cat, "balance": Decimal("0"),
                })
                consolidated_balances[code]["balance"] += Decimal(str(b["balance"]))
            entity_details.append({"entity_id": eid, "currency": "KRW", "cta": 0})

        elif base_currency == "KRW" and currency == "USD":
            # KRW 모드 + HOI: USD→KRW 환산
            try:
                translation = translate_entity_to_krw(conn, eid, fiscal_year, start_date, end_date)
                for tb in translation["translated_balances"]:
                    code = tb["code"]
                    cat = _norm_cat(tb["category"])
                    consolidated_balances.setdefault(code, {
                        "name": tb["name"], "category": cat, "balance": Decimal("0"),
                    })
                    consolidated_balances[code]["balance"] += Decimal(str(tb["krw_balance"]))

                cta_amount = Decimal(str(translation["cta_amount"]))
                cta_by_entity[eid] = float(cta_amount)
                consolidated_balances.setdefault("39200", {
                    "name": "해외사업환산손익 (CTA)",
                    "category": "자본", "balance": Decimal("0"),
                })
                consolidated_balances["39200"]["balance"] += cta_amount
                cur.execute(
                    """INSERT INTO consolidation_adjustments
                        (statement_id, adjustment_type, account_code, description,
                         original_amount, adjusted_amount, source_entity_id, exchange_rate)
                    VALUES (%s, 'cta', '39200', %s, 0, %s, %s, %s)""",
                    [stmt_id, f"해외사업환산손익 entity {eid}", float(cta_amount), eid,
                     translation["rates_used"]["closing"]],
                )
                entity_details.append({"entity_id": eid, "currency": "USD→KRW",
                                       "cta": float(cta_amount), "rates": translation["rates_used"]})
            except Exception as e:
                entity_details.append({"entity_id": eid, "currency": "USD", "error": str(e)})

    # 내부거래 상계 — 확정된 내부거래의 분개를 조회하여 계정별 차감
    from backend.services.exchange_rate_service import get_closing_rate as _get_closing
    eliminations = get_eliminations(conn, all_entity_ids, start_date, end_date)
    total_eliminated = Decimal("0")
    for elim in eliminations:
        elim_amount = Decimal(str(elim["amount"]))
        elim_currency = elim.get("currency", "KRW")

        # KRW 금액을 USD로 변환
        if elim_currency != "USD":
            try:
                elim_rate = _get_closing(conn, elim_currency, "USD", end_date)
                elim_amount_usd = (elim_amount * elim_rate).quantize(Decimal("0.01"))
            except Exception:
                elim_amount_usd = Decimal("0")
        else:
            elim_amount_usd = elim_amount

        total_eliminated += elim_amount_usd

        # 내부거래 분개의 계정 조회하여 연결 잔액에서 차감
        for tx_id_col in ["transaction_a_id", "transaction_b_id"]:
            tx_id = elim.get(tx_id_col)
            if not tx_id:
                continue
            cur.execute(
                """
                SELECT sa.code, jel.debit_amount, jel.credit_amount
                FROM journal_entry_lines jel
                JOIN journal_entries je ON jel.journal_entry_id = je.id
                JOIN standard_accounts sa ON jel.standard_account_id = sa.id
                WHERE je.transaction_id = %s
                """,
                [tx_id],
            )
            for je_row in cur.fetchall():
                acct_code, debit, credit = je_row
                # GAAP 변환 후 코드 찾기 (매핑된 코드가 consolidated_balances에 있을 수 있음)
                for cb_code in list(consolidated_balances.keys()):
                    if cb_code == acct_code or consolidated_balances[cb_code].get("_orig_code") == acct_code:
                        bal_adj = Decimal(str(debit or 0)) - Decimal(str(credit or 0))
                        if elim_currency != "USD":
                            bal_adj = (bal_adj * elim_rate).quantize(Decimal("0.01"))
                        consolidated_balances[cb_code]["balance"] -= bal_adj
                        break

        cur.execute(
            """
            INSERT INTO consolidation_adjustments
                (statement_id, adjustment_type, account_code, description,
                 original_amount, adjusted_amount, source_entity_id)
            VALUES (%s, 'intercompany_elimination', 'ELIM', %s, %s, %s, %s)
            """,
            [stmt_id, elim.get("description", ""), float(elim_amount), float(elim_amount_usd), elim["entity_a_id"]],
        )

    # ── line items 저장 (P3-47/49: USD/KRW 양 통화 모두 지원) ──
    bs_type = "consolidated_balance_sheet"
    is_type = "consolidated_income_statement"
    bs_order = 100
    is_order = 100
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")
    total_equity = Decimal("0")
    total_revenue = Decimal("0")
    total_expense = Decimal("0")

    asset_cats = {"Assets", "자산"}
    liab_cats = {"Liabilities", "부채"}
    equity_cats = {"Equity", "자본"}
    revenue_cats = {"Revenue", "수익", "Income"}
    expense_cats = {"Expenses", "Expense", "비용", "Cost of Goods Sold"}

    for code, data in sorted(consolidated_balances.items()):
        cat = data["category"]
        bal = data["balance"]

        if cat in asset_cats:
            total_assets += bal
            stmt_type, line_prefix, sort_o = bs_type, "cons", bs_order
            bs_order += 10
        elif cat in liab_cats:
            total_liabilities += bal
            stmt_type, line_prefix, sort_o = bs_type, "cons", bs_order
            bs_order += 10
        elif cat in equity_cats:
            total_equity += bal
            stmt_type, line_prefix, sort_o = bs_type, "cons", bs_order
            bs_order += 10
        elif cat in revenue_cats:
            total_revenue += bal
            stmt_type, line_prefix, sort_o = is_type, "is", is_order
            is_order += 10
        elif cat in expense_cats:
            total_expense += bal
            stmt_type, line_prefix, sort_o = is_type, "is", is_order
            is_order += 10
        else:
            continue

        _insert_line_item(cur, stmt_id, {
            "statement_type": stmt_type, "account_code": code,
            "line_key": f"{line_prefix}_{code}", "label": f"{data['name']} ({code})",
            "sort_order": sort_o,
            "auto_amount": float(bal), "auto_debit": 0, "auto_credit": 0,
            "is_section_header": False,
        })

    # Net Income = Revenue - Expense
    net_income_total = total_revenue - total_expense
    # BS Equity 에 별도 line 으로 가산 — 양 통화 모두 적용
    earnings_code = "3700" if base_currency == "USD" else "37800"
    earnings_label = "Current Period Earnings" if base_currency == "USD" else "당기순손익 (당기)"
    _insert_line_item(cur, stmt_id, {
        "statement_type": bs_type, "account_code": earnings_code,
        "line_key": "cons_current_earnings", "label": earnings_label,
        "sort_order": bs_order,
        "auto_amount": float(net_income_total), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": False,
    })
    bs_order += 10
    total_equity += net_income_total

    # BS 합계 행 — 통화별 라벨
    if base_currency == "USD":
        bs_totals = [
            ("cons_total_assets", "Total Assets", total_assets),
            ("cons_total_liabilities", "Total Liabilities", total_liabilities),
            ("cons_total_equity", "Total Equity", total_equity),
            ("cons_total_le", "Total Liabilities & Equity", total_liabilities + total_equity),
        ]
        is_totals = [
            ("is_total_revenue", "Total Revenue", total_revenue),
            ("is_total_expense", "Total Expenses", total_expense),
            ("is_net_income", "Net Income", net_income_total),
        ]
    else:
        bs_totals = [
            ("cons_total_assets", "자산총계", total_assets),
            ("cons_total_liabilities", "부채총계", total_liabilities),
            ("cons_total_equity", "자본총계", total_equity),
            ("cons_total_le", "부채와자본총계", total_liabilities + total_equity),
        ]
        is_totals = [
            ("is_total_revenue", "수익총계", total_revenue),
            ("is_total_expense", "비용총계", total_expense),
            ("is_net_income", "당기순손익", net_income_total),
        ]

    for key, label, amount in bs_totals:
        _insert_line_item(cur, stmt_id, {
            "statement_type": bs_type, "line_key": key, "label": label,
            "sort_order": bs_order,
            "auto_amount": float(amount), "auto_debit": 0, "auto_credit": 0,
            "is_section_header": True,
        })
        bs_order += 10

    for key, label, amount in is_totals:
        _insert_line_item(cur, stmt_id, {
            "statement_type": is_type, "line_key": key, "label": label,
            "sort_order": is_order,
            "auto_amount": float(amount), "auto_debit": 0, "auto_credit": 0,
            "is_section_header": True,
        })
        is_order += 10

    is_balanced = abs(total_assets - (total_liabilities + total_equity)) < Decimal("0.01")

    cur.close()

    return {
        "statement_id": stmt_id,
        "fiscal_year": fiscal_year,
        "is_consolidated": True,
        "base_currency": base_currency,
        "entities": entity_details,
        "cta_by_entity": cta_by_entity,
        "eliminations_count": len(eliminations),
        "total_eliminated": float(total_eliminated),
        "validation": {
            "total_assets": float(total_assets),
            "total_liabilities": float(total_liabilities),
            "total_equity": float(total_equity),
            "total_revenue": float(total_revenue),
            "total_expense": float(total_expense),
            "net_income": float(net_income_total),
            "is_balanced": is_balanced,
            "difference": float(total_assets - total_liabilities - total_equity),
        },
    }

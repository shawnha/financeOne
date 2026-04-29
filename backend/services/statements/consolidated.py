"""연결재무제표 및 전체 재무제표 일괄 생성."""

from datetime import date, timedelta
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from backend.services.gaap_conversion_service import convert_kgaap_to_usgaap
from backend.services.cta_service import translate_entity_to_usd
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
) -> dict:
    """연결재무제표 생성 (US GAAP, USD 기준).

    1. HOI 자회사 탐색
    2. HOI: 잔액 → GAAP 코드 변환 (USD, 환율 불필요)
    3. HOK/HOR: 잔액 → GAAP 변환 → CTA 환산 (KRW→USD)
    4. 합산 (US GAAP 코드 기준)
    5. 내부거래 상계
    6. CTA → AOCI (30400/3300)
    7. 저장
    """
    start_date = date(fiscal_year, start_month, 1)
    if end_month == 12:
        end_date = date(fiscal_year, 12, 31)
    else:
        end_date = date(fiscal_year, end_month + 1, 1) - timedelta(days=1)

    cur = conn.cursor()

    # 자회사 탐색
    subsidiary_ids = _get_subsidiaries(cur, HOI_ENTITY_ID)
    all_entity_ids = [HOI_ENTITY_ID] + subsidiary_ids

    # 연결 statement 헤더 생성
    cur.execute(
        """
        SELECT id FROM financial_statements
        WHERE entity_id = %s AND fiscal_year = %s
          AND start_month = %s AND end_month = %s
          AND is_consolidated = TRUE
        """,
        [HOI_ENTITY_ID, fiscal_year, start_month, end_month],
    )
    row = cur.fetchone()
    if row:
        stmt_id = row[0]
        cur.execute("DELETE FROM financial_statement_line_items WHERE statement_id = %s", [stmt_id])
        cur.execute("DELETE FROM consolidation_adjustments WHERE statement_id = %s", [stmt_id])
        cur.execute(
            "UPDATE financial_statements SET status = 'draft', base_currency = 'USD', updated_at = NOW() WHERE id = %s",
            [stmt_id],
        )
    else:
        # ki_num 분기: 단독 statement(default=3) 와 unique constraint 충돌 방지를 위해
        # consolidated 는 ki_num=99 사용
        cur.execute(
            """
            INSERT INTO financial_statements
                (entity_id, fiscal_year, ki_num, start_month, end_month, is_consolidated, base_currency, status)
            VALUES (%s, %s, 99, %s, %s, TRUE, 'USD', 'draft')
            RETURNING id
            """,
            [HOI_ENTITY_ID, fiscal_year, start_month, end_month],
        )
        stmt_id = cur.fetchone()[0]

    # 각 법인별 USD 잔액 수집
    consolidated_balances: dict[str, dict] = {}  # us_gaap_code → {name, category, balance}
    cta_by_entity = {}
    entity_details = []

    for eid in all_entity_ids:
        currency = _get_entity_currency(cur, eid)

        if currency == "USD":
            # HOI: 환율 변환 불필요, GAAP 코드 변환만
            balances = get_all_account_balances(conn, eid, to_date=end_date)
            usgaap = convert_kgaap_to_usgaap(conn, balances)
            for b in usgaap:
                code = b["us_gaap_code"]
                if code not in consolidated_balances:
                    consolidated_balances[code] = {
                        "name": b["us_gaap_name"],
                        "category": b["us_gaap_category"],
                        "balance": Decimal("0"),
                    }
                consolidated_balances[code]["balance"] += Decimal(str(b["balance"]))
            entity_details.append({"entity_id": eid, "currency": "USD", "cta": 0})
        else:
            # KRW 법인: GAAP 변환 + CTA 환산
            try:
                translation = translate_entity_to_usd(conn, eid, fiscal_year, start_date, end_date)
                for tb in translation["translated_balances"]:
                    code = tb["us_gaap_code"]
                    if code not in consolidated_balances:
                        consolidated_balances[code] = {
                            "name": tb["us_gaap_name"],
                            "category": tb["category"],
                            "balance": Decimal("0"),
                        }
                    consolidated_balances[code]["balance"] += Decimal(str(tb["usd_balance"]))

                cta_amount = Decimal(str(translation["cta_amount"]))
                cta_by_entity[eid] = float(cta_amount)

                # CTA → AOCI (3300)
                if "3300" not in consolidated_balances:
                    consolidated_balances["3300"] = {
                        "name": "Accumulated Other Comprehensive Income (CTA)",
                        "category": "Equity",
                        "balance": Decimal("0"),
                    }
                consolidated_balances["3300"]["balance"] += cta_amount

                # 감사 추적
                cur.execute(
                    """
                    INSERT INTO consolidation_adjustments
                        (statement_id, adjustment_type, account_code, description,
                         original_amount, adjusted_amount, source_entity_id, exchange_rate)
                    VALUES (%s, 'cta', '3300', %s, 0, %s, %s, %s)
                    """,
                    [
                        stmt_id, f"CTA for entity {eid}",
                        float(cta_amount), eid,
                        translation["rates_used"]["closing"],
                    ],
                )
                entity_details.append({
                    "entity_id": eid, "currency": "KRW",
                    "cta": float(cta_amount), "rates": translation["rates_used"],
                })
            except Exception as e:
                # 환율 없음 등 → 해당 법인 건너뜀 + 경고
                entity_details.append({
                    "entity_id": eid, "currency": "KRW",
                    "error": str(e),
                })

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

    # ── net_income 자동 합산 → retained_earnings ──
    # Revenue (수익) - Expense (비용) = net_income
    # 이를 Equity 의 retained_earnings 에 가산해야 BS 항등식 성립
    net_income_total = Decimal("0")
    pl_categories = {"Revenue", "Income", "Expense", "Cost of Goods Sold"}
    for code, data in list(consolidated_balances.items()):
        cat = data["category"]
        bal = data["balance"]
        if cat in ("Revenue", "Income"):
            net_income_total += bal  # 수익 +
        elif cat in ("Expense", "Cost of Goods Sold"):
            net_income_total -= bal  # 비용 -

    # Retained Earnings 코드 — 3200 (Retained Earnings) 우선, 없으면 신규 생성
    retained_code = "3200"
    if net_income_total != 0:
        if retained_code in consolidated_balances:
            consolidated_balances[retained_code]["balance"] += net_income_total
        else:
            consolidated_balances[retained_code] = {
                "name": "Retained Earnings (Net Income for Period)",
                "category": "Equity",
                "balance": net_income_total,
            }

    # line items 저장 — PL 카테고리는 BS 에 표시 안 함 (retained_earnings 로 합산 완료)
    st = "consolidated_balance_sheet"
    order = 100
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")
    total_equity = Decimal("0")

    for code, data in sorted(consolidated_balances.items()):
        cat = data["category"]
        bal = data["balance"]

        if cat == "Assets":
            total_assets += bal
        elif cat == "Liabilities":
            total_liabilities += bal
        elif cat == "Equity":
            total_equity += bal
        elif cat in pl_categories:
            # PL 항목은 BS 에 표시 안 함 (이미 retained_earnings 로 합산됨)
            continue

        _insert_line_item(cur, stmt_id, {
            "statement_type": st,
            "account_code": code,
            "line_key": f"cons_{code}",
            "label": f"{data['name']} ({code})",
            "sort_order": order,
            "auto_amount": float(bal),
            "auto_debit": 0,
            "auto_credit": 0,
            "is_section_header": False,
        })
        order += 10

    # 합계 행
    for key, label, amount in [
        ("cons_total_assets", "Total Assets", total_assets),
        ("cons_total_liabilities", "Total Liabilities", total_liabilities),
        ("cons_total_equity", "Total Equity", total_equity),
        ("cons_total_le", "Total Liabilities & Equity", total_liabilities + total_equity),
    ]:
        _insert_line_item(cur, stmt_id, {
            "statement_type": st,
            "line_key": key,
            "label": label,
            "sort_order": order,
            "auto_amount": float(amount),
            "auto_debit": 0, "auto_credit": 0,
            "is_section_header": True,
        })
        order += 10

    is_balanced = abs(total_assets - (total_liabilities + total_equity)) < Decimal("0.01")

    cur.close()

    return {
        "statement_id": stmt_id,
        "fiscal_year": fiscal_year,
        "is_consolidated": True,
        "base_currency": "USD",
        "entities": entity_details,
        "cta_by_entity": cta_by_entity,
        "eliminations_count": len(eliminations),
        "total_eliminated": float(total_eliminated),
        "validation": {
            "total_assets": float(total_assets),
            "total_liabilities": float(total_liabilities),
            "total_equity": float(total_equity),
            "net_income": float(net_income_total),
            "is_balanced": is_balanced,
            "difference": float(total_assets - total_liabilities - total_equity),
        },
    }

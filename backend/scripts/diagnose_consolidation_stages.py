"""P3-46 단계별 진단 — consolidated.py 의 -$250K 차이가 어느 단계에서 발생하는지 식별.

4 stages:
  Stage 1: 각 entity raw 잔액 (journal_entry_lines 합계)
  Stage 2: K-GAAP → US GAAP 코드 변환 후
  Stage 3: KRW entity 의 USD 환산 후 + CTA
  Stage 4: 내부거래 상계 후
  Stage 5: net_income 합산 시도 (Revenue - Expense)

각 stage 마다 Total Assets / Liabilities / Equity / NI / Diff 를 출력해서
어디서 -$250K 가 깨지는지 시각적으로 식별.
"""
import json
import os
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from backend.services.bookkeeping_engine import get_all_account_balances
from backend.services.gaap_conversion_service import convert_kgaap_to_usgaap
from backend.services.cta_service import translate_entity_to_usd
from backend.services.intercompany_service import get_eliminations
from backend.services.exchange_rate_service import get_closing_rate

FISCAL_YEAR = 2026
START_DATE = date(2026, 1, 1)
END_DATE = date(2026, 4, 30)
OUT = "/Users/admin/Desktop/claude/financeOne/.claude-tmp/consolidation-stages.json"


def D(x):
    return Decimal(str(x or 0))


def f(x):
    return float(x or 0)


def categorize(bal: dict) -> str:
    """category 라벨 정규화 — K-GAAP 한글 → 영문."""
    cat = bal.get("us_gaap_category") or bal.get("category", "")
    mapping = {
        "자산": "Assets",
        "부채": "Liabilities",
        "자본": "Equity",
        "수익": "Revenue",
        "비용": "Expenses",
        "Revenue": "Revenue",
        "Expense": "Expenses",
        "Expenses": "Expenses",
        "Income": "Revenue",
    }
    return mapping.get(cat, cat or "OTHER")


def sum_by_category(items: list[dict], balance_key: str) -> dict:
    by_cat = {"Assets": Decimal("0"), "Liabilities": Decimal("0"),
              "Equity": Decimal("0"), "Revenue": Decimal("0"),
              "Expenses": Decimal("0"), "OTHER": Decimal("0")}
    other_seen = set()
    for item in items:
        cat = categorize(item)
        amt = D(item.get(balance_key, 0))
        if cat in by_cat:
            by_cat[cat] += amt
        else:
            by_cat["OTHER"] += amt
            other_seen.add(cat)
    return {k: f(v) for k, v in by_cat.items()}, sorted(other_seen)


def stage_summary(label: str, totals: dict, other_seen: list = None) -> dict:
    a = totals.get("Assets", 0)
    l = totals.get("Liabilities", 0)
    e = totals.get("Equity", 0)
    r = totals.get("Revenue", 0)
    ex = totals.get("Expenses", 0)
    ni = r - ex
    diff_no_ni = a - l - e
    diff_with_ni = a - l - e - ni
    return {
        "stage": label,
        "totals": totals,
        "other_categories_seen": other_seen or [],
        "net_income": ni,
        "diff_excluding_NI": diff_no_ni,
        "diff_including_NI": diff_with_ni,
    }


def main():
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    conn.cursor().execute("SET search_path TO financeone, public")

    HOI, HOK, HOR = 1, 2, 3
    stages: dict[str, list[dict]] = {}

    # ============== STAGE 1: raw 잔액 ==============
    stages["stage1_raw"] = []
    for eid, name, currency in [(HOI, "HOI", "USD"), (HOK, "HOK", "KRW"), (HOR, "HOR", "KRW")]:
        balances = get_all_account_balances(conn, eid, to_date=END_DATE)
        period = get_all_account_balances(conn, eid, from_date=START_DATE, to_date=END_DATE)

        # cumulative for A/L/E, period for R/E
        full_items = []
        for b in balances:
            full_items.append({**b, "us_gaap_category": b["category"]})

        period_items = []
        for b in period:
            period_items.append({**b, "us_gaap_category": b["category"]})

        all_for_sum = full_items + period_items
        # 정규화: K-GAAP 한글 카테고리만 사용 — A/L/E는 cumulative, R/E는 period

        # sum cumulative for A/L/E
        cum_totals, cum_other = sum_by_category(full_items, "balance")
        per_totals, per_other = sum_by_category(period_items, "balance")
        # merge: A/L/E from cum, R/E from per
        merged = {
            "Assets": cum_totals.get("Assets", 0),
            "Liabilities": cum_totals.get("Liabilities", 0),
            "Equity": cum_totals.get("Equity", 0),
            "Revenue": per_totals.get("Revenue", 0),
            "Expenses": per_totals.get("Expenses", 0),
            "OTHER": cum_totals.get("OTHER", 0) + per_totals.get("OTHER", 0),
        }
        stages["stage1_raw"].append({
            "entity_id": eid, "name": name, "currency": currency,
            **stage_summary(f"Stage 1 — {name} raw", merged, list(set(cum_other + per_other))),
        })

    # ============== STAGE 2: K-GAAP → US GAAP 변환 후 ==============
    stages["stage2_gaap_converted"] = []
    for eid, name, currency in [(HOI, "HOI", "USD"), (HOK, "HOK", "KRW"), (HOR, "HOR", "KRW")]:
        balances = get_all_account_balances(conn, eid, to_date=END_DATE)
        period = get_all_account_balances(conn, eid, from_date=START_DATE, to_date=END_DATE)
        usgaap_cum = convert_kgaap_to_usgaap(conn, balances)
        usgaap_per = convert_kgaap_to_usgaap(conn, period)

        cum_totals, cum_other = sum_by_category(usgaap_cum, "balance")
        per_totals, per_other = sum_by_category(usgaap_per, "balance")
        merged = {
            "Assets": cum_totals.get("Assets", 0),
            "Liabilities": cum_totals.get("Liabilities", 0),
            "Equity": cum_totals.get("Equity", 0),
            "Revenue": per_totals.get("Revenue", 0),
            "Expenses": per_totals.get("Expenses", 0),
            "OTHER": cum_totals.get("OTHER", 0) + per_totals.get("OTHER", 0),
        }
        stages["stage2_gaap_converted"].append({
            "entity_id": eid, "name": name, "currency": currency,
            **stage_summary(f"Stage 2 — {name} GAAP", merged, list(set(cum_other + per_other))),
            "unmapped_count": sum(1 for b in usgaap_cum if not b.get("is_mapped")),
        })

    # ============== STAGE 3: USD 환산 + CTA ==============
    stages["stage3_usd_translated"] = []
    consolidated_balances: dict = {}  # 누적 sum

    # HOI: 환율 변환 불필요
    hoi_balances = get_all_account_balances(conn, HOI, to_date=END_DATE)
    hoi_period = get_all_account_balances(conn, HOI, from_date=START_DATE, to_date=END_DATE)
    hoi_us = convert_kgaap_to_usgaap(conn, hoi_balances)
    hoi_us_per = convert_kgaap_to_usgaap(conn, hoi_period)

    # HOI: Assets/Liab/Equity = cumulative, Revenue/Expense = period
    for b in hoi_us:
        cat = categorize(b)
        if cat in ("Assets", "Liabilities", "Equity"):
            code = b["us_gaap_code"]
            consolidated_balances.setdefault(code, {"name": b["us_gaap_name"], "category": cat, "balance": Decimal("0")})
            consolidated_balances[code]["balance"] += D(b["balance"])
    for b in hoi_us_per:
        cat = categorize(b)
        if cat in ("Revenue", "Expenses"):
            code = b["us_gaap_code"]
            consolidated_balances.setdefault(code, {"name": b["us_gaap_name"], "category": cat, "balance": Decimal("0")})
            consolidated_balances[code]["balance"] += D(b["balance"])

    hoi_totals, hoi_other = sum_by_category(
        [{"us_gaap_category": v["category"], "balance": float(v["balance"])} for v in consolidated_balances.values()],
        "balance",
    )
    stages["stage3_usd_translated"].append({
        "entity_id": HOI, "name": "HOI (USD direct)", "currency": "USD",
        **stage_summary("Stage 3 — HOI direct", hoi_totals, hoi_other),
    })

    # KRW entities
    for eid, name in [(HOK, "HOK"), (HOR, "HOR")]:
        try:
            translation = translate_entity_to_usd(conn, eid, FISCAL_YEAR, START_DATE, END_DATE)
        except Exception as e:
            stages["stage3_usd_translated"].append({
                "entity_id": eid, "name": name, "error": str(e),
            })
            continue

        tb_items = translation["translated_balances"]
        ent_totals, ent_other = sum_by_category(tb_items, "usd_balance")
        cta = translation["cta_amount"]
        rates = translation["rates_used"]
        summary = translation["summary"]

        stages["stage3_usd_translated"].append({
            "entity_id": eid, "name": name, "currency": "KRW→USD",
            **stage_summary(f"Stage 3 — {name} translated", ent_totals, ent_other),
            "cta_amount": cta,
            "rates_used": rates,
            "cta_service_summary": summary,
        })

        for tb in tb_items:
            code = tb["us_gaap_code"]
            cat = categorize(tb)
            consolidated_balances.setdefault(code, {"name": tb["us_gaap_name"], "category": cat, "balance": Decimal("0")})
            consolidated_balances[code]["balance"] += D(tb["usd_balance"])

        # CTA → AOCI (3300)
        consolidated_balances.setdefault("3300", {"name": "AOCI (CTA)", "category": "Equity", "balance": Decimal("0")})
        consolidated_balances["3300"]["balance"] += D(cta)

    # 누적 stage3 summary (모든 entity 합산)
    after_translate_items = [
        {"us_gaap_category": v["category"], "balance": float(v["balance"])}
        for v in consolidated_balances.values()
    ]
    cum_totals, cum_other = sum_by_category(after_translate_items, "balance")
    stages["stage3_consolidated_after_translate"] = stage_summary(
        "Stage 3 합산 후", cum_totals, cum_other
    )

    # ============== STAGE 4: 내부거래 상계 ==============
    cur = conn.cursor()
    eliminations = get_eliminations(conn, [HOI, HOK, HOR], START_DATE, END_DATE)
    elim_log = []
    elim_total_usd = Decimal("0")

    for elim in eliminations:
        elim_amount = D(elim["amount"])
        elim_currency = elim.get("currency", "KRW")
        if elim_currency != "USD":
            try:
                elim_rate = get_closing_rate(conn, elim_currency, "USD", END_DATE)
                elim_amount_usd = (elim_amount * D(elim_rate)).quantize(Decimal("0.01"))
            except Exception:
                elim_amount_usd = Decimal("0")
        else:
            elim_amount_usd = elim_amount
        elim_total_usd += elim_amount_usd
        elim_log.append({
            "amount_orig": float(elim_amount),
            "currency": elim_currency,
            "amount_usd": float(elim_amount_usd),
            "description": elim.get("description", ""),
        })

        # 코드 매칭 차감 — consolidated.py 의 동일 로직 재현
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
                for cb_code in list(consolidated_balances.keys()):
                    if cb_code == acct_code:
                        bal_adj = D(debit) - D(credit)
                        if elim_currency != "USD":
                            try:
                                rate = D(get_closing_rate(conn, elim_currency, "USD", END_DATE))
                                bal_adj = (bal_adj * rate).quantize(Decimal("0.01"))
                            except Exception:
                                bal_adj = Decimal("0")
                        consolidated_balances[cb_code]["balance"] -= bal_adj
                        break

    after_elim_items = [
        {"us_gaap_category": v["category"], "balance": float(v["balance"])}
        for v in consolidated_balances.values()
    ]
    elim_totals, elim_other = sum_by_category(after_elim_items, "balance")
    stages["stage4_after_elimination"] = {
        **stage_summary("Stage 4 상계 후", elim_totals, elim_other),
        "elimination_count": len(eliminations),
        "elimination_total_usd": float(elim_total_usd),
        "elimination_log": elim_log,
    }

    # ============== STAGE 5: net_income 합산 시도 (조정 plan) ==============
    # Revenue/Expense 잔액을 retained_earnings (3000) 또는 별도 net_income 계정에 가산
    # 시뮬레이션 — 실제 코드 변경 안함
    sim_balances = {k: dict(v) for k, v in consolidated_balances.items()}
    revenue_total = Decimal("0")
    expense_total = Decimal("0")
    for code, v in sim_balances.items():
        if v["category"] == "Revenue":
            revenue_total += D(v["balance"])
        elif v["category"] == "Expenses":
            expense_total += D(v["balance"])

    # 시뮬레이션 1: net_income = revenue - expense 를 별도 Equity line 으로 추가
    sim_balances["__SIM_NI__"] = {
        "name": "Net Income (Period)",
        "category": "Equity",
        "balance": revenue_total - expense_total,
    }
    sim_items = [
        {"us_gaap_category": v["category"], "balance": float(v["balance"])}
        for v in sim_balances.values()
    ]
    sim_totals, sim_other = sum_by_category(sim_items, "balance")
    stages["stage5_with_net_income"] = stage_summary("Stage 5 NI 가산 후", sim_totals, sim_other)

    cur.close()
    conn.close()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as out:
        json.dump(stages, out, ensure_ascii=False, indent=2, default=str)

    # 콘솔 출력
    print(f"진단 결과: {OUT}\n")

    def fmt(name, st):
        t = st["totals"]
        ni = st["net_income"]
        d1 = st["diff_excluding_NI"]
        d2 = st["diff_including_NI"]
        print(f"  {name}")
        print(f"    A={t['Assets']:>15,.2f}  L={t['Liabilities']:>15,.2f}  E={t['Equity']:>15,.2f}")
        print(f"    R={t['Revenue']:>15,.2f}  EX={t['Expenses']:>15,.2f}  NI={ni:>15,.2f}")
        print(f"    diff(A-L-E)={d1:>15,.2f}    diff(A-L-E-NI)={d2:>15,.2f}")
        if st.get("other_categories_seen"):
            print(f"    other categories: {st['other_categories_seen']}")

    print("=== Stage 1 — Raw 잔액 (entity 별) ===")
    for s in stages["stage1_raw"]:
        fmt(f"{s['name']} ({s['currency']})", s)

    print("\n=== Stage 2 — K-GAAP → US GAAP 변환 후 ===")
    for s in stages["stage2_gaap_converted"]:
        fmt(f"{s['name']} ({s['currency']})  unmapped={s['unmapped_count']}", s)

    print("\n=== Stage 3 — USD 환산 + CTA (entity 별) ===")
    for s in stages["stage3_usd_translated"]:
        if "error" in s:
            print(f"  {s['name']}: ERROR {s['error']}")
            continue
        fmt(f"{s['name']} ({s['currency']})", s)
        if "cta_amount" in s:
            print(f"    CTA={s['cta_amount']:>15,.2f}  rates={s['rates_used']}")
            print(f"    cta_service summary: {s['cta_service_summary']}")

    print("\n=== Stage 3 합산 (consolidated_balances after translate) ===")
    fmt("ALL", stages["stage3_consolidated_after_translate"])

    print("\n=== Stage 4 — 내부거래 상계 후 ===")
    fmt("ALL", stages["stage4_after_elimination"])
    print(f"    eliminations={stages['stage4_after_elimination']['elimination_count']}건  "
          f"total=${stages['stage4_after_elimination']['elimination_total_usd']:,.2f}")

    print("\n=== Stage 5 — Net Income 가산 시뮬레이션 ===")
    fmt("ALL+NI", stages["stage5_with_net_income"])


if __name__ == "__main__":
    main()

"""C 옵션 진단 — 연결재무제표 BS 항등식 -$250K 차이 원인 분석.

3개 축으로 데이터 dump:
  C-1: Entity 별 BS 자체 검증 (HOI/HOK/HOR raw 잔액 항등식)
  C-2: HOI 분개 vs QBO Report 차이
  C-3: 미매핑 transaction 비율

산출물: JSON 파일 (HTML 리포트 입력)
"""
import json
import os
from datetime import date
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

load_dotenv()

FISCAL_YEAR = 2026
END_DATE = date(2026, 4, 30)
START_DATE = date(2026, 1, 1)
OUT = "/Users/admin/Desktop/claude/financeOne/.claude-tmp/consolidation-diagnosis.json"


def _money(v):
    return float(v) if v is not None else 0.0


def diagnose_entity_bs(conn, entity_id: int, name: str) -> dict:
    """Entity 별 BS 자체 검증 — standard_account category 별 raw 잔액 합산."""
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # entity 정보
    cur.execute("SELECT name, currency FROM entities WHERE id = %s", [entity_id])
    e_name, currency = cur.fetchone()

    # journal_entry_lines 기준 잔액 (표준계정별)
    cur.execute(
        """
        SELECT sa.code, sa.name, sa.category, sa.normal_side,
               COALESCE(SUM(jel.debit_amount), 0) AS dr,
               COALESCE(SUM(jel.credit_amount), 0) AS cr
        FROM journal_entry_lines jel
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        JOIN standard_accounts sa ON jel.standard_account_id = sa.id
        WHERE je.entity_id = %s
          AND je.entry_date <= %s
        GROUP BY sa.code, sa.name, sa.category, sa.normal_side
        ORDER BY sa.code
        """,
        [entity_id, END_DATE],
    )
    lines = cur.fetchall()

    by_cat = {"자산": Decimal("0"), "부채": Decimal("0"), "자본": Decimal("0"),
              "수익": Decimal("0"), "비용": Decimal("0"),
              "Assets": Decimal("0"), "Liabilities": Decimal("0"), "Equity": Decimal("0"),
              "Revenue": Decimal("0"), "Expense": Decimal("0"),
              "OTHER": Decimal("0")}
    other_categories = set()

    detail = []
    for code, n, cat, side, dr, cr in lines:
        # 정상잔액 방향에 따른 잔액
        if side == "debit":
            bal = Decimal(str(dr)) - Decimal(str(cr))
        else:
            bal = Decimal(str(cr)) - Decimal(str(dr))
        if cat in by_cat:
            by_cat[cat] += bal
        else:
            by_cat["OTHER"] += bal
            other_categories.add(cat)
        detail.append({
            "code": code, "name": n, "category": cat,
            "debit": _money(dr), "credit": _money(cr), "balance": _money(bal),
        })

    assets = by_cat["자산"] + by_cat["Assets"]
    liab = by_cat["부채"] + by_cat["Liabilities"]
    equity = by_cat["자본"] + by_cat["Equity"]
    revenue = by_cat["수익"] + by_cat["Revenue"]
    expense = by_cat["비용"] + by_cat["Expense"]
    net_income = revenue - expense
    equity_with_ni = equity + net_income
    diff = assets - liab - equity_with_ni

    cur.close()
    return {
        "entity_id": entity_id, "name": e_name, "currency": currency,
        "as_of": str(END_DATE),
        "totals": {
            "assets": _money(assets), "liabilities": _money(liab),
            "equity_raw": _money(equity), "revenue": _money(revenue),
            "expense": _money(expense), "net_income": _money(net_income),
            "equity_with_ni": _money(equity_with_ni),
            "bs_diff": _money(diff),  # 0 이어야 항등식 OK
        },
        "is_balanced": abs(float(diff)) < 0.01,
        "other_categories_seen": sorted(other_categories),
        "line_count": len(detail),
    }


def diagnose_hoi_vs_qbo(conn) -> dict:
    """HOI 분개 vs QBO Report API 비교."""
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # 1) HOI 분개 잔액
    cur.execute(
        """
        SELECT COUNT(*) FROM journal_entries WHERE entity_id = 1
        """
    )
    je_count = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COALESCE(SUM(debit_amount),0), COALESCE(SUM(credit_amount),0)
        FROM journal_entry_lines jel
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE je.entity_id = 1 AND je.entry_date <= %s
        """,
        [END_DATE],
    )
    je_dr, je_cr = cur.fetchone()

    # 2) QBO Report API 결과 (financial_statement_line_items 의 HOI BS draft 사용)
    cur.execute(
        """
        SELECT id, status FROM financial_statements
        WHERE entity_id = 1 AND fiscal_year = %s
          AND start_month = 1 AND end_month = %s
          AND is_consolidated IS NOT TRUE
        ORDER BY id DESC LIMIT 1
        """,
        [FISCAL_YEAR, END_DATE.month],
    )
    row = cur.fetchone()
    qbo_totals = None
    if row:
        sid, _status = row
        cur.execute(
            """
            SELECT label, COALESCE(auto_amount, manual_amount, 0) AS amt
            FROM financial_statement_line_items
            WHERE statement_id = %s AND statement_type = 'balance_sheet'
              AND label ILIKE 'TOTAL %%'
            ORDER BY sort_order
            """,
            [sid],
        )
        qbo_totals = {}
        for label, amt in cur.fetchall():
            qbo_totals[label.strip()] = _money(amt)

    # 3) qbo_transaction_lines 가 분개에 들어갔는지 확인
    cur.execute("SELECT COUNT(*) FROM qbo_transaction_lines")
    qbo_lines = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(DISTINCT t.id)
        FROM transactions t
        WHERE t.entity_id = 1
        """
    )
    hoi_tx = cur.fetchone()[0]

    cur.close()
    return {
        "hoi_journal_entries_count": je_count,
        "hoi_journal_total_debit": _money(je_dr),
        "hoi_journal_total_credit": _money(je_cr),
        "hoi_journal_balanced": abs(float(je_dr) - float(je_cr)) < 0.01,
        "qbo_transaction_lines": qbo_lines,
        "hoi_transactions": hoi_tx,
        "qbo_report_totals": qbo_totals,
    }


def diagnose_mapping_coverage(conn) -> dict:
    """미매핑 transaction 비율 + 신뢰도 분포."""
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'transactions' AND table_schema = 'financeone'")
    tx_cols = {r[0] for r in cur.fetchall()}
    has_confidence = "confidence" in tx_cols
    has_mapping_source = "mapping_source" in tx_cols

    # 전체 / 매핑 / 미매핑
    by_entity = {}
    cur.execute(
        """
        SELECT entity_id,
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE standard_account_id IS NOT NULL) AS mapped_std,
          COUNT(*) FILTER (WHERE internal_account_id IS NOT NULL) AS mapped_int,
          COUNT(*) FILTER (WHERE standard_account_id IS NULL) AS unmapped_std
        FROM transactions
        GROUP BY entity_id
        ORDER BY entity_id
        """
    )
    for eid, total, m_std, m_int, u_std in cur.fetchall():
        by_entity[eid] = {
            "total": total,
            "mapped_standard": m_std,
            "mapped_internal": m_int,
            "unmapped_standard": u_std,
            "coverage_std_pct": round(100 * m_std / total, 1) if total else 0,
            "coverage_int_pct": round(100 * m_int / total, 1) if total else 0,
        }

    # mapping_source 분포 (있을 때만)
    source_dist = None
    if has_mapping_source:
        cur.execute(
            """
            SELECT mapping_source, COUNT(*) FROM transactions
            WHERE mapping_source IS NOT NULL
            GROUP BY mapping_source ORDER BY 2 DESC
            """
        )
        source_dist = [{"source": r[0], "count": r[1]} for r in cur.fetchall()]

    # 신뢰도 분포 (있을 때만)
    confidence_dist = None
    if has_confidence:
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE confidence >= 0.9) AS high,
              COUNT(*) FILTER (WHERE confidence >= 0.7 AND confidence < 0.9) AS mid,
              COUNT(*) FILTER (WHERE confidence < 0.7) AS low,
              COUNT(*) FILTER (WHERE confidence IS NULL) AS none
            FROM transactions
            """
        )
        h, m, l, n = cur.fetchone()
        confidence_dist = {"high>=0.9": h, "mid 0.7-0.9": m, "low<0.7": l, "null": n}

    # mapping_rules 사이즈
    cur.execute("SELECT entity_id, COUNT(*) FROM mapping_rules GROUP BY entity_id ORDER BY 1")
    rules_by_entity = {r[0]: r[1] for r in cur.fetchall()}

    # standard_account_keywords 사이즈
    cur.execute("SELECT COUNT(*) FROM standard_account_keywords")
    keyword_count = cur.fetchone()[0]

    cur.close()
    return {
        "by_entity": by_entity,
        "mapping_source_distribution": source_dist,
        "confidence_distribution": confidence_dist,
        "mapping_rules_by_entity": rules_by_entity,
        "standard_account_keywords": keyword_count,
    }


def main():
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    try:
        result = {
            "fiscal_year": FISCAL_YEAR,
            "as_of": str(END_DATE),
            "C1_entity_bs": [
                diagnose_entity_bs(conn, 1, "HOI"),
                diagnose_entity_bs(conn, 2, "HOK"),
                diagnose_entity_bs(conn, 3, "HOR"),
            ],
            "C2_hoi_vs_qbo": diagnose_hoi_vs_qbo(conn),
            "C3_mapping_coverage": diagnose_mapping_coverage(conn),
        }
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"진단 완료. 결과: {OUT}")
        # 콘솔 요약
        print("\n=== C-1 Entity BS 항등식 ===")
        for e in result["C1_entity_bs"]:
            t = e["totals"]
            balanced = "✓" if e["is_balanced"] else "✗"
            print(f"  {balanced} {e['name']:>4} ({e['currency']}): "
                  f"A={t['assets']:>15,.0f} L={t['liabilities']:>15,.0f} "
                  f"E+NI={t['equity_with_ni']:>15,.0f} diff={t['bs_diff']:>15,.0f}")
            if e["other_categories_seen"]:
                print(f"      other categories: {e['other_categories_seen']}")
        print("\n=== C-2 HOI vs QBO ===")
        c2 = result["C2_hoi_vs_qbo"]
        print(f"  분개 entries: {c2['hoi_journal_entries_count']}")
        print(f"  분개 D=C 균형: {c2['hoi_journal_balanced']}  (D={c2['hoi_journal_total_debit']:,.0f} / C={c2['hoi_journal_total_credit']:,.0f})")
        print(f"  HOI transactions: {c2['hoi_transactions']}, qbo_transaction_lines: {c2['qbo_transaction_lines']}")
        print(f"  QBO Report 양식 totals: {c2['qbo_report_totals']}")
        print("\n=== C-3 매핑 충실도 ===")
        for eid, m in result["C3_mapping_coverage"]["by_entity"].items():
            print(f"  entity={eid}  total={m['total']:>5}  std={m['coverage_std_pct']}%  int={m['coverage_int_pct']}%")
        print(f"  mapping_source: {result['C3_mapping_coverage']['mapping_source_distribution']}")
        print(f"  confidence: {result['C3_mapping_coverage']['confidence_distribution']}")
        print(f"  mapping_rules: {result['C3_mapping_coverage']['mapping_rules_by_entity']}")
        print(f"  standard_account_keywords: {result['C3_mapping_coverage']['standard_account_keywords']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

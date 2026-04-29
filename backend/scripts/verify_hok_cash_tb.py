"""HOK 26년 1-3월 현금(10100) 시산표 차변/대변 검증.

질문: 현금 차변 2,855,956 / 대변 297,050 이 맞는지?
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # statement_id=4 의 시산표에서 현금 라인 조회
    cur.execute("""
        SELECT account_code, label, auto_debit, auto_credit, auto_amount
        FROM financial_statement_line_items
        WHERE statement_id = 4
          AND statement_type = 'trial_balance'
          AND account_code = '10100'
    """)
    row = cur.fetchone()
    print("=== statement_id=4 시산표 — 현금(10100) 라인 ===")
    if row:
        print(f"  label: {row[1]}")
        print(f"  차변(debit_total): {float(row[2]):>15,.0f}")
        print(f"  대변(credit_total): {float(row[3]):>15,.0f}")
        print(f"  잔액(balance): {float(row[4]):>15,.0f}")
    else:
        print("  현금 라인 없음")
    print()

    # 원본 journal_entry_lines 에서 현금 차변/대변 직접 합산 (entity 2, 26년 1-3월)
    cur.execute("""
        SELECT
            COALESCE(SUM(jel.debit_amount), 0) AS sum_debit,
            COALESCE(SUM(jel.credit_amount), 0) AS sum_credit,
            COUNT(*) AS line_count
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.journal_entry_id
        JOIN standard_accounts sa ON sa.id = jel.standard_account_id
        WHERE je.entity_id = 2
          AND sa.code = '10100'
          AND je.entry_date >= '2026-01-01'
          AND je.entry_date <= '2026-03-31'
    """)
    r2 = cur.fetchone()
    print("=== journal_entry_lines 직접 합산 (entity=2 / 현금 / 26-01~26-03) ===")
    print(f"  차변 합: {float(r2[0]):>15,.0f}")
    print(f"  대변 합: {float(r2[1]):>15,.0f}")
    print(f"  line 수: {r2[2]}")
    print()

    # 25년 12-31 opening balance 도 포함될 가능성 (시산표는 누적)
    cur.execute("""
        SELECT
            COALESCE(SUM(jel.debit_amount), 0) AS sum_debit,
            COALESCE(SUM(jel.credit_amount), 0) AS sum_credit,
            COUNT(*) AS line_count
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.journal_entry_id
        JOIN standard_accounts sa ON sa.id = jel.standard_account_id
        WHERE je.entity_id = 2
          AND sa.code = '10100'
          AND je.entry_date <= '2026-03-31'
    """)
    r3 = cur.fetchone()
    print("=== journal_entry_lines 누적 (entity=2 / 현금 / ~26-03 전체) ===")
    print(f"  차변 합: {float(r3[0]):>15,.0f}")
    print(f"  대변 합: {float(r3[1]):>15,.0f}")
    print(f"  잔액 (debit-credit): {float(r3[0]) - float(r3[1]):>15,.0f}")
    print(f"  line 수: {r3[2]}")
    print()

    # 현금 거래 sample
    cur.execute("""
        SELECT je.entry_date, jel.debit_amount, jel.credit_amount, jel.description
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.journal_entry_id
        JOIN standard_accounts sa ON sa.id = jel.standard_account_id
        WHERE je.entity_id = 2 AND sa.code = '10100'
          AND je.entry_date <= '2026-03-31'
        ORDER BY je.entry_date
        LIMIT 15
    """)
    print("=== 현금 거래 sample (최대 15건) ===")
    for row in cur.fetchall():
        d = float(row[1]) if row[1] else 0
        c = float(row[2]) if row[2] else 0
        side = "차" if d > 0 else "대"
        amt = d if d > 0 else c
        print(f"  {row[0]}  {side} {amt:>13,.0f}  {(row[3] or '')[:40]}")

    conn.close()


if __name__ == "__main__":
    main()

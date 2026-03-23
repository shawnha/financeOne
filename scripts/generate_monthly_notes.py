"""월별 재무 요약 Obsidian 노트 자동 생성

사용법:
    source .venv/bin/activate
    python scripts/generate_monthly_notes.py --year 2026 --month 3
    python scripts/generate_monthly_notes.py --year 2026  # 전체 월
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

VAULT_PATH = os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    "/Users/admin/Desktop/claude/financeone/obsidian-vault",
)

ENTITIES = {1: "HOI", 2: "한아원코리아", 3: "한아원리테일"}


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def get_monthly_summary(conn, entity_id: int, year: int, month: int) -> dict:
    """월별 재무 요약 데이터 추출."""
    cur = conn.cursor()

    # 수입/지출
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense,
            COUNT(*) AS tx_count,
            COUNT(*) FILTER (WHERE is_confirmed = TRUE) AS confirmed_count,
            COUNT(*) FILTER (WHERE is_confirmed = FALSE) AS unconfirmed_count
        FROM transactions
        WHERE entity_id = %s
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
        """,
        [entity_id, year, month],
    )
    row = cur.fetchone()
    income, expense, tx_count, confirmed, unconfirmed = row

    # 잔고 (해당 월말 기준)
    cur.execute(
        """
        SELECT COALESCE(SUM(balance), 0)
        FROM balance_snapshots
        WHERE entity_id = %s
          AND date <= make_date(%s, %s, 28)
        """,
        [entity_id, year, month],
    )
    balance = cur.fetchone()[0]

    # 상위 지출처
    cur.execute(
        """
        SELECT counterparty, SUM(amount) AS total
        FROM transactions
        WHERE entity_id = %s AND type = 'out'
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
          AND counterparty IS NOT NULL
        GROUP BY counterparty
        ORDER BY total DESC
        LIMIT 5
        """,
        [entity_id, year, month],
    )
    top_expenses = [(r[0], float(r[1])) for r in cur.fetchall()]

    # 상위 수입처
    cur.execute(
        """
        SELECT counterparty, SUM(amount) AS total
        FROM transactions
        WHERE entity_id = %s AND type = 'in'
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
          AND counterparty IS NOT NULL
        GROUP BY counterparty
        ORDER BY total DESC
        LIMIT 5
        """,
        [entity_id, year, month],
    )
    top_incomes = [(r[0], float(r[1])) for r in cur.fetchall()]

    cur.close()

    return {
        "income": float(income),
        "expense": float(expense),
        "net": float(income - expense),
        "balance": float(balance),
        "tx_count": tx_count,
        "confirmed": confirmed,
        "unconfirmed": unconfirmed,
        "top_expenses": top_expenses,
        "top_incomes": top_incomes,
    }


def format_krw(amount: float) -> str:
    """금액 포맷팅."""
    if amount >= 0:
        return f"₩{amount:,.0f}"
    return f"-₩{abs(amount):,.0f}"


def generate_note(entity_id: int, entity_name: str, year: int, month: int, data: dict) -> str:
    """Obsidian 마크다운 노트 생성."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    top_exp_lines = ""
    for name, amt in data["top_expenses"]:
        top_exp_lines += f"- [[{name}]] — {format_krw(amt)}\n"
    if not top_exp_lines:
        top_exp_lines = "- (없음)\n"

    top_inc_lines = ""
    for name, amt in data["top_incomes"]:
        top_inc_lines += f"- [[{name}]] — {format_krw(amt)}\n"
    if not top_inc_lines:
        top_inc_lines = "- (없음)\n"

    confirmation_pct = (
        f"{data['confirmed'] / data['tx_count'] * 100:.0f}%"
        if data["tx_count"] > 0
        else "N/A"
    )

    note = f"""---
tags: [월별리포트, 재무, {entity_name}]
entity: {entity_name}
entity_id: {entity_id}
year: {year}
month: {month}
generated: {now}
---

# {year}년 {month}월 재무 요약 — {entity_name}

## 현금흐름

| 항목 | 금액 |
|------|------|
| 수입 합계 | {format_krw(data['income'])} |
| 지출 합계 | {format_krw(data['expense'])} |
| 순현금흐름 | {format_krw(data['net'])} |
| 잔고 | {format_krw(data['balance'])} |

## 거래 현황

- 총 거래: **{data['tx_count']}건**
- 확정: {data['confirmed']}건 / 미확정: {data['unconfirmed']}건
- 확정율: **{confirmation_pct}**

## 상위 지출처
{top_exp_lines}
## 상위 수입처
{top_inc_lines}
## 주요 이슈

> [!note] 자동 생성 노트
> 이 노트는 FinanceOne에서 자동으로 생성되었습니다.
> 수동 메모를 아래에 추가하세요.

## 다음 달 액션

- [ ] 미확정 거래 {data['unconfirmed']}건 확인
"""
    return note


def generate_counterparty_note(name: str, entity_name: str, first_seen: str) -> str:
    """거래처 Obsidian 노트 생성."""
    return f"""---
tags: [거래처, {entity_name}]
entity: {entity_name}
first_seen: {first_seen}
---

# {name}

## 기본 정보
- 법인: {entity_name}
- 첫 거래일: {first_seen}

## 거래 이력

> [!info] 자동 생성
> 이 노트는 FinanceOne에서 거래처 첫 등장 시 자동 생성되었습니다.

## 메모

"""


def save_note(filepath: Path, content: str, overwrite: bool = False):
    """노트 저장. 기존 파일이 있으면 overwrite 옵션에 따라."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if filepath.exists() and not overwrite:
        print(f"  [SKIP] {filepath.name} (이미 존재)")
        return False
    filepath.write_text(content, encoding="utf-8")
    print(f"  [CREATED] {filepath.name}")
    return True


def generate_monthly(year: int, month: int | None = None):
    """월별 재무 노트 생성."""
    conn = get_conn()
    months = [month] if month else list(range(1, 13))
    vault = Path(VAULT_PATH)
    created = 0

    for m in months:
        for eid, ename in ENTITIES.items():
            data = get_monthly_summary(conn, eid, year, m)
            if data["tx_count"] == 0:
                continue

            content = generate_note(eid, ename, year, m, data)
            filepath = vault / "월별 리포트" / str(year) / f"{year}-{m:02d}-{ename}.md"
            if save_note(filepath, content):
                created += 1

    conn.close()
    print(f"\n총 {created}개 노트 생성 완료")
    return created


def generate_counterparties(year: int, month: int | None = None):
    """새 거래처 노트 자동 생성."""
    conn = get_conn()
    cur = conn.cursor()
    vault = Path(VAULT_PATH)

    date_filter = ""
    params: list = []
    if year and month:
        date_filter = "AND EXTRACT(YEAR FROM t.date) = %s AND EXTRACT(MONTH FROM t.date) = %s"
        params = [year, month]
    elif year:
        date_filter = "AND EXTRACT(YEAR FROM t.date) = %s"
        params = [year]

    cur.execute(
        f"""
        SELECT DISTINCT t.counterparty, t.entity_id, MIN(t.date) AS first_seen
        FROM transactions t
        WHERE t.counterparty IS NOT NULL AND t.counterparty != ''
          {date_filter}
        GROUP BY t.counterparty, t.entity_id
        ORDER BY first_seen
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    created = 0
    for name, eid, first_seen in rows:
        ename = ENTITIES.get(eid, "Unknown")
        # 파일명에 사용할 수 없는 문자 제거
        safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
        filepath = vault / "거래처" / f"{safe_name}.md"
        content = generate_counterparty_note(name, ename, str(first_seen))
        if save_note(filepath, content):
            created += 1

    print(f"\n총 {created}개 거래처 노트 생성 완료")
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinanceOne → Obsidian 노트 자동 생성")
    parser.add_argument("--year", type=int, required=True, help="연도 (예: 2026)")
    parser.add_argument("--month", type=int, help="월 (1-12, 미지정 시 전체)")
    parser.add_argument("--counterparties", action="store_true", help="거래처 노트도 생성")
    parser.add_argument("--overwrite", action="store_true", help="기존 노트 덮어쓰기")
    args = parser.parse_args()

    print(f"=== FinanceOne → Obsidian 노트 생성 ===")
    print(f"Vault: {VAULT_PATH}")
    print(f"기간: {args.year}년 {f'{args.month}월' if args.month else '전체'}\n")

    print("--- 월별 재무 요약 ---")
    generate_monthly(args.year, args.month)

    if args.counterparties:
        print("\n--- 거래처 노트 ---")
        generate_counterparties(args.year, args.month)

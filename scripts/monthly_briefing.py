"""CEO 월간 브리핑 생성 — Obsidian 노트 + NotebookLM 소스

사용법:
    source .venv/bin/activate
    python scripts/monthly_briefing.py --year 2026 --month 3
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import date, datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

VAULT_PATH = os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    "/Users/admin/Desktop/claude/financeone/obsidian-vault",
)

ENTITIES = {1: ("HOI", "USD"), 2: ("한아원코리아", "KRW"), 3: ("한아원리테일", "KRW")}


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def format_currency(amount: float, currency: str) -> str:
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"₩{amount:,.0f}"


def get_group_summary(conn, year: int, month: int) -> dict:
    """3법인 그룹 전체 요약."""
    cur = conn.cursor()
    summaries = {}

    for eid, (ename, currency) in ENTITIES.items():
        cur.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0),
                COUNT(*),
                COUNT(*) FILTER (WHERE is_confirmed = FALSE)
            FROM transactions
            WHERE entity_id = %s
              AND EXTRACT(YEAR FROM date) = %s
              AND EXTRACT(MONTH FROM date) = %s
            """,
            [eid, year, month],
        )
        row = cur.fetchone()
        summaries[ename] = {
            "income": float(row[0]),
            "expense": float(row[1]),
            "net": float(row[0] - row[1]),
            "tx_count": row[2],
            "unconfirmed": row[3],
            "currency": currency,
        }

    # 이상 거래 (금액 상위 5%)
    cur.execute(
        """
        SELECT t.entity_id, t.date, t.amount, t.counterparty, t.description, e.name
        FROM transactions t
        JOIN entities e ON t.entity_id = e.id
        WHERE EXTRACT(YEAR FROM t.date) = %s
          AND EXTRACT(MONTH FROM t.date) = %s
          AND t.amount > (
              SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY amount)
              FROM transactions
              WHERE EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
          )
        ORDER BY t.amount DESC
        LIMIT 10
        """,
        [year, month, year, month],
    )
    anomalies = []
    for row in cur.fetchall():
        anomalies.append({
            "entity": row[5],
            "date": str(row[1]),
            "amount": float(row[2]),
            "counterparty": row[3] or "",
            "description": row[4],
        })

    cur.close()
    return {"entities": summaries, "anomalies": anomalies}


def generate_briefing(year: int, month: int) -> str:
    """CEO 브리핑 Obsidian 노트 생성."""
    conn = get_conn()
    data = get_group_summary(conn, year, month)
    conn.close()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 법인별 요약 테이블
    entity_rows = ""
    for ename, s in data["entities"].items():
        entity_rows += (
            f"| {ename} | {format_currency(s['income'], s['currency'])} | "
            f"{format_currency(s['expense'], s['currency'])} | "
            f"{format_currency(s['net'], s['currency'])} | "
            f"{s['tx_count']}건 | {s['unconfirmed']}건 |\n"
        )

    # 이상 거래
    anomaly_lines = ""
    if data["anomalies"]:
        for a in data["anomalies"]:
            anomaly_lines += f"- **{a['entity']}** {a['date']} — ₩{a['amount']:,.0f} ({a['counterparty']}: {a['description']})\n"
    else:
        anomaly_lines = "- 이상 거래 없음\n"

    # 전체 액션 아이템
    total_unconfirmed = sum(s["unconfirmed"] for s in data["entities"].values())
    total_tx = sum(s["tx_count"] for s in data["entities"].values())

    briefing = f"""---
tags: [CEO브리핑, 월별리포트, 그룹]
year: {year}
month: {month}
generated: {now}
type: briefing
---

# {year}년 {month}월 CEO 브리핑 — 한아원 그룹

> [!summary] 핵심 요약
> {total_tx}건 거래 처리, 미확정 {total_unconfirmed}건 잔여.

## 법인별 현금흐름

| 법인 | 수입 | 지출 | 순현금흐름 | 거래 | 미확정 |
|------|------|------|-----------|------|--------|
{entity_rows}

## 이상 거래 (상위 5%)
{anomaly_lines}

## 주요 이슈

> [!warning] 확인 필요
> 미확정 거래 {total_unconfirmed}건이 남아있습니다. [[거래내역]] 페이지에서 확인하세요.

## 이번 달 액션

- [ ] 미확정 거래 {total_unconfirmed}건 처리
- [ ] 이상 거래 {len(data['anomalies'])}건 검토
- [ ] 월말 재무제표 생성 확인

## 관련 노트

- [[{year}-{month:02d}-HOI]]
- [[{year}-{month:02d}-한아원코리아]]
- [[{year}-{month:02d}-한아원리테일]]

---

> [!info] 자동 생성
> `scripts/monthly_briefing.py`로 생성됨 ({now})
"""
    return briefing


def main():
    parser = argparse.ArgumentParser(description="CEO 월간 브리핑 노트 생성")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    args = parser.parse_args()

    print(f"=== CEO 브리핑 생성: {args.year}년 {args.month}월 ===")

    content = generate_briefing(args.year, args.month)

    vault = Path(VAULT_PATH)
    filepath = vault / "월별 리포트" / str(args.year) / f"{args.year}-{args.month:02d}-CEO-브리핑.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    filepath.write_text(content, encoding="utf-8")
    print(f"[CREATED] {filepath}")
    print(f"\nNotebookLM 소스로 사용하려면 이 파일을 NotebookLM에 업로드하세요:")
    print(f"  {filepath}")


if __name__ == "__main__":
    main()

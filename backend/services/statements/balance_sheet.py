"""재무상태표 생성 — K-GAAP 공시 그룹 기반 집계."""

from datetime import date
from decimal import Decimal
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from .helpers import _insert_line_item, _section_header


# ── 공시 그룹 정의 ────────────────────────────────
# 각 macro 그룹에는 K-GAAP 상세 sub_category와 legacy sub_category를 모두 포함.
# 실제 DB에 존재하는 값: 당좌자산/재고자산/투자자산/유형자산/기타비유동 + 유동자산/비유동자산(legacy)
BS_GROUPS = {
    "자산": [
        ("current_assets", "유동자산", ["당좌자산", "재고자산", "유동자산"]),
        ("noncurrent_assets", "비유동자산", ["투자자산", "유형자산", "기타비유동", "기타비유동자산", "비유동자산"]),
    ],
    "부채": [
        ("current_liab", "유동부채", ["유동부채"]),
        ("noncurrent_liab", "비유동부채", ["비유동부채"]),
    ],
    "자본": [
        ("equity", "자본", ["자본금", "자본잉여금", "이익잉여금", "기타포괄손익누계액", "기타자본"]),
    ],
}

# 공시 소그룹 라벨 (sub_category 표시용)
SUB_LABEL = {
    "당좌자산": "당좌자산",
    "재고자산": "재고자산",
    "유동자산": "기타유동자산",
    "투자자산": "투자자산",
    "유형자산": "유형자산",
    "기타비유동": "기타비유동자산",
    "기타비유동자산": "기타비유동자산",
    "비유동자산": "기타비유동자산",
    "유동부채": "유동부채",
    "비유동부채": "비유동부채",
    "자본금": "자본금",
    "자본잉여금": "자본잉여금",
    "이익잉여금": "이익잉여금",
}


def _emit_group(
    items: list,
    st: str,
    balances: list,
    category: str,
    macro_key: str,
    macro_label: str,
    sub_list: list[str],
    order: int,
    net_income_adj: dict | None = None,
) -> tuple[Decimal, int]:
    """macro 그룹 하나를 출력: 헤더 → 각 sub 그룹(헤더 + 계정들 + 소계) → macro 소계.

    net_income_adj: {account_code: Decimal} — 특정 계정에 당기순이익 가산용.
    계정이 전혀 없으면 매크로 헤더도 생략 (noise 방지).
    """
    # 해당 macro에 속한 계정 모음 (sub별 그룹핑 유지)
    grouped: list[tuple[str, list]] = []
    seen: set[str] = set()
    for sub in sub_list:
        if sub in seen:
            continue
        seen.add(sub)
        sub_accounts = [
            b for b in balances
            if b["category"] == category and (b.get("subcategory") or "") == sub
        ]
        if sub_accounts:
            grouped.append((sub, sub_accounts))

    has_accounts = any(accts for _, accts in grouped)
    if not has_accounts:
        return Decimal("0"), order

    items.append(_section_header(st, f"{macro_key}_header", f"  {macro_label}", order))
    order += 10
    macro_total = Decimal("0")

    for sub, sub_accounts in grouped:
        sub_ko = SUB_LABEL.get(sub, sub)
        items.append(_section_header(st, f"{macro_key}_{sub}_header", f"    {sub_ko}", order))
        order += 10
        sub_total = Decimal("0")
        for b in sub_accounts:
            bal = Decimal(str(b["balance"]))
            label_suffix = ""
            if net_income_adj and b["code"] in net_income_adj:
                bal += net_income_adj[b["code"]]
                label_suffix = " (당기순이익 포함)"
            items.append({
                "statement_type": st,
                "account_code": b["code"],
                "line_key": f"{macro_key}_{b['code']}",
                "label": f"      {b['name']}{label_suffix}",
                "sort_order": order,
                "auto_amount": float(bal),
                "auto_debit": float(b["debit_total"]),
                "auto_credit": float(b["credit_total"]),
            })
            sub_total += bal
            order += 10
        items.append({
            "statement_type": st,
            "line_key": f"{macro_key}_{sub}_subtotal",
            "label": f"    {sub_ko} 소계",
            "sort_order": order,
            "auto_amount": float(sub_total),
            "auto_debit": 0, "auto_credit": 0,
        })
        order += 10
        macro_total += sub_total

    items.append({
        "statement_type": st,
        "line_key": f"{macro_key}_total",
        "label": f"  {macro_label} 합계",
        "sort_order": order,
        "auto_amount": float(macro_total),
        "auto_debit": 0, "auto_credit": 0,
    })
    order += 10
    return macro_total, order


# --- 재무상태표 ---

def generate_balance_sheet(
    conn: PgConnection,
    cur,
    stmt_id: int,
    entity_id: int,
    fiscal_year: int,
    as_of_date: date,
    start_date: date,
) -> dict:
    """재무상태표 생성. 자산 = 부채 + 자본 검증.

    공시 그룹(K-GAAP 당좌/재고/투자/유형 등) 소계 + macro(유동/비유동) 합계 2단계.

    Returns: {"total_assets", "total_liabilities", "total_equity", "is_balanced"}
    """
    balances = get_all_account_balances(conn, entity_id, to_date=as_of_date)

    # 당기순이익 계산 (수익 - 비용, 해당 기간) — 이익잉여금에 가산
    period_balances = get_all_account_balances(conn, entity_id, from_date=start_date, to_date=as_of_date)
    net_income = Decimal("0")
    for b in period_balances:
        if b["category"] == "수익":
            net_income += Decimal(str(b["balance"]))
        elif b["category"] == "비용":
            net_income -= Decimal(str(b["balance"]))

    st = "balance_sheet"
    items = []
    order = 100

    # ── 자산 ──
    items.append(_section_header(st, "assets_section", "자산", order))
    order += 10
    total_current_assets, order = _emit_group(
        items, st, balances, "자산",
        "current_assets", "유동자산",
        BS_GROUPS["자산"][0][2], order,
    )
    total_noncurrent_assets, order = _emit_group(
        items, st, balances, "자산",
        "noncurrent_assets", "비유동자산",
        BS_GROUPS["자산"][1][2], order,
    )
    total_assets = total_current_assets + total_noncurrent_assets
    items.append({
        "statement_type": st, "line_key": "total_assets",
        "label": "자산 총계", "sort_order": order,
        "auto_amount": float(total_assets), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # ── 부채 ──
    items.append(_section_header(st, "liabilities_section", "부채", order))
    order += 10
    total_current_liab, order = _emit_group(
        items, st, balances, "부채",
        "current_liab", "유동부채",
        BS_GROUPS["부채"][0][2], order,
    )
    total_noncurrent_liab, order = _emit_group(
        items, st, balances, "부채",
        "noncurrent_liab", "비유동부채",
        BS_GROUPS["부채"][1][2], order,
    )
    total_liabilities = total_current_liab + total_noncurrent_liab
    items.append({
        "statement_type": st, "line_key": "total_liabilities",
        "label": "부채 총계", "sort_order": order,
        "auto_amount": float(total_liabilities), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 20

    # ── 자본 ── (단일 macro이므로 상위 section header 생략)
    # 이익잉여금/결손금 중 하나에만 당기순이익 가산. 우선순위:
    # 미처리결손금(37800) → 이월결손금(37600) → 이익준비금(37100) → 이익잉여금 subcat 아무 계정
    equity_balances = [b for b in balances if b["category"] == "자본"]
    equity_codes = {b["code"] for b in equity_balances}
    re_balances = [b for b in equity_balances if (b.get("subcategory") or "") == "이익잉여금"]
    ni_target = None
    for cand in ("37800", "37600", "37100"):
        if cand in equity_codes:
            ni_target = cand
            break
    if ni_target is None and re_balances:
        ni_target = re_balances[0]["code"]

    # 자본/이익잉여금 계정이 전혀 없고 당기순이익이 존재하면 37800을 합성 주입
    synthetic_balances = list(balances)
    if ni_target is None and net_income != 0:
        ni_target = "37800"
        synthetic_balances = synthetic_balances + [{
            "account_id": None, "code": "37800", "name": "미처리결손금",
            "category": "자본", "subcategory": "이익잉여금",
            "normal_side": "credit",
            "debit_total": 0, "credit_total": 0, "balance": 0,
        }]

    equity_adj = {ni_target: net_income} if ni_target else {}
    total_equity, order = _emit_group(
        items, st, synthetic_balances, "자본",
        "equity", "자본",
        BS_GROUPS["자본"][0][2], order,
        net_income_adj=equity_adj,
    )

    items.append({
        "statement_type": st, "line_key": "total_equity",
        "label": "자본 총계", "sort_order": order,
        "auto_amount": float(total_equity), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 10

    liab_plus_equity = total_liabilities + total_equity
    items.append({
        "statement_type": st, "line_key": "total_liabilities_equity",
        "label": "부채 및 자본 총계", "sort_order": order,
        "auto_amount": float(liab_plus_equity), "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })

    for item in items:
        _insert_line_item(cur, stmt_id, item)

    is_balanced = total_assets == liab_plus_equity
    return {
        "total_assets": float(total_assets),
        "total_liabilities": float(total_liabilities),
        "total_equity": float(total_equity),
        "net_income": float(net_income),
        "is_balanced": is_balanced,
        "difference": float(total_assets - liab_plus_equity),
    }

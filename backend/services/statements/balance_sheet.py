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
        ("noncurrent_assets", "비유동자산", ["투자자산", "유형자산", "무형자산", "기타비유동", "기타비유동자산", "비유동자산"]),
    ],
    "부채": [
        ("current_liab", "유동부채", ["유동부채"]),
        ("noncurrent_liab", "비유동부채", ["비유동부채"]),
    ],
    "자본": [
        # PDF 양식: Ⅰ. 자본금 / Ⅱ. 자본잉여금 / Ⅲ. 자본조정 / Ⅳ. 기타포괄손익누계액 / Ⅴ. 결손금
        ("equity_capital", "자본금", ["자본금"]),
        ("equity_surplus", "자본잉여금", ["자본잉여금"]),
        ("equity_adjust", "자본조정", ["자본조정"]),
        ("equity_aoci", "기타포괄손익누계액", ["기타포괄손익누계액"]),
        ("equity_retained", "결손금", ["이익잉여금", "기타자본"]),  # 결손 회사 표기
    ],
}

# 공시 소그룹 라벨 (sub_category 표시용) — K-GAAP 확정 결산 양식
# (1) 당좌자산 / (2) 재고자산 식 괄호 번호는 macro_key 단위로 부여 (자산: 1=당좌, 2=재고)
SUB_LABEL = {
    "당좌자산": "당좌자산",
    "재고자산": "재고자산",
    "유동자산": "기타유동자산",
    "투자자산": "투자자산",
    "유형자산": "유형자산",
    "무형자산": "무형자산",
    "기타비유동": "기타비유동자산",
    "기타비유동자산": "기타비유동자산",
    "비유동자산": "기타비유동자산",
    "유동부채": "유동부채",
    "비유동부채": "비유동부채",
    "자본금": "자본금",
    "자본잉여금": "자본잉여금",
    "자본조정": "자본조정",
    "기타포괄손익누계액": "기타포괄손익누계액",
    "이익잉여금": "결손금",  # K-GAAP 결손 회사는 "결손금" 으로 표시
}

# macro_key 별 sub 그룹의 괄호 번호 prefix (PDF 양식과 일치)
SUB_NUMBER_PREFIX = {
    "current_assets": {"당좌자산": "(1)", "재고자산": "(2)", "유동자산": "(3)"},
    "noncurrent_assets": {"투자자산": "(1)", "유형자산": "(2)", "무형자산": "(3)",
                           "기타비유동": "(4)", "기타비유동자산": "(4)", "비유동자산": "(4)"},
    # 부채/자본 sub는 prefix 안 붙임 (PDF 도 동일)
}

# macro_key 별 로마자 prefix (Ⅰ. 유동자산, Ⅱ. 비유동자산 등 — 동일 grand-section 안에서 순서대로)
MACRO_ROMAN = {
    "current_assets": "Ⅰ.",
    "noncurrent_assets": "Ⅱ.",
    "current_liab": "Ⅰ.",
    "noncurrent_liab": "Ⅱ.",
    "equity_capital": "Ⅰ.",
    "equity_surplus": "Ⅱ.",
    "equity_adjust": "Ⅲ.",
    "equity_aoci": "Ⅳ.",
    "equity_retained": "Ⅴ.",
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
    """K-GAAP PDF 확정 결산 양식 출력:
        Ⅰ. 유동자산                              505,508,004    (macro 헤더 + 합계)
          (1) 당좌자산                           469,811,609    (sub 헤더 + 소계, prefix)
            현금                                          0    (item, 인덴트 6 space)
            보통예금                            161,065,312
            ...
          (2) 재고자산                            35,696,395
            상품                                 35,696,395

    별도 "소계" 줄 없음 (sub 헤더에 sub_total 직접 표시).
    별도 "합계" 줄 없음 (macro 헤더에 macro_total 직접 표시).
    grand_total 만 별도 줄 (caller 가 처리).

    net_income_adj: {account_code: Decimal} — 특정 계정에 당기순이익 가산.
    계정이 전혀 없으면 매크로 헤더 자체 생략 (noise 방지).
    """
    # 해당 macro에 속한 계정 모음 (sub별 그룹핑 유지) — 먼저 sub_total 계산
    grouped: list[tuple[str, list, Decimal]] = []
    seen: set[str] = set()
    for sub in sub_list:
        if sub in seen:
            continue
        seen.add(sub)
        sub_accounts = [
            b for b in balances
            if b["category"] == category and (b.get("subcategory") or "") == sub
        ]
        sub_total = Decimal("0")
        for b in sub_accounts:
            bal = Decimal(str(b["balance"]))
            if net_income_adj and b["code"] in net_income_adj:
                bal += net_income_adj[b["code"]]
            sub_total += bal
        if sub_accounts:
            grouped.append((sub, sub_accounts, sub_total))

    has_accounts = any(accts for _, accts, _ in grouped)
    if not has_accounts:
        return Decimal("0"), order

    macro_total = sum((st_ for _, _, st_ in grouped), Decimal("0"))

    # ── macro 헤더 — "Ⅰ. 유동자산" + 총액 표시
    roman = MACRO_ROMAN.get(macro_key, "")
    macro_label_full = f"  {roman} {macro_label}".rstrip() if roman else f"  {macro_label}"
    items.append({
        "statement_type": st,
        "line_key": f"{macro_key}_header",
        "label": macro_label_full,
        "sort_order": order,
        "auto_amount": float(macro_total),
        "auto_debit": 0, "auto_credit": 0,
        "is_section_header": True,
    })
    order += 10

    sub_prefix_map = SUB_NUMBER_PREFIX.get(macro_key, {})
    # sub 가 1개이고 macro_label 와 sub_label 가 겹치면 (예: 유동부채/유동부채) sub 헤더 생략
    skip_sub_header = (
        len(grouped) == 1 and SUB_LABEL.get(grouped[0][0], grouped[0][0]) == macro_label
    )

    for sub, sub_accounts, sub_total in grouped:
        if not skip_sub_header:
            sub_ko = SUB_LABEL.get(sub, sub)
            prefix = sub_prefix_map.get(sub, "")
            sub_label_full = f"    {prefix} {sub_ko}".rstrip() if prefix else f"    {sub_ko}"
            items.append({
                "statement_type": st,
                "line_key": f"{macro_key}_{sub}_header",
                "label": sub_label_full,
                "sort_order": order,
                "auto_amount": float(sub_total),
                "auto_debit": 0, "auto_credit": 0,
                "is_section_header": True,
            })
            order += 10
        # 인덴트 — sub 헤더가 있으면 6 space, 없으면 4 space
        item_indent = "      " if not skip_sub_header else "    "
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
                "label": f"{item_indent}{b['name']}{label_suffix}",
                "sort_order": order,
                "auto_amount": float(bal),
                "auto_debit": float(b["debit_total"]),
                "auto_credit": float(b["credit_total"]),
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
        "label": "자산총계", "sort_order": order,
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
        "label": "부채총계", "sort_order": order,
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

    # ── 자본 grand-section header
    items.append(_section_header(st, "equity_section", "자본", order))
    order += 10

    # 5개 macro 모두 호출 (Ⅰ. 자본금 / Ⅱ. 자본잉여금 / ... / Ⅴ. 결손금)
    total_equity = Decimal("0")
    for macro_key, macro_label, sub_list in BS_GROUPS["자본"]:
        sub_total, order = _emit_group(
            items, st, synthetic_balances, "자본",
            macro_key, macro_label,
            sub_list, order,
            net_income_adj=equity_adj,
        )
        total_equity += sub_total

    items.append({
        "statement_type": st, "line_key": "total_equity",
        "label": "자본총계", "sort_order": order,
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

"""재무제표 라벨 한→영 번역 (연결재무제표 / lang=en 출력용).

생성은 항상 한국어로 이루어지고, API에서 lang=en 요청 시에만 본 모듈로 번역.
계정 라벨은 standard_accounts.name_en을 사용, 섹션/소계/합계 라벨은 LABEL_EN dict로 매핑.
"""

LABEL_EN: dict[str, str] = {
    # BS 카테고리
    "자산": "Assets",
    "부채": "Liabilities",
    "자본": "Equity",
    # BS macro
    "유동자산": "Current Assets",
    "비유동자산": "Non-current Assets",
    "유동부채": "Current Liabilities",
    "비유동부채": "Non-current Liabilities",
    # BS 공시 sub
    "당좌자산": "Quick Assets",
    "재고자산": "Inventories",
    "기타유동자산": "Other Current Assets",
    "투자자산": "Investments",
    "유형자산": "Property, Plant and Equipment",
    "기타비유동자산": "Other Non-current Assets",
    "자본금": "Paid-in Capital",
    "자본잉여금": "Capital Surplus",
    "이익잉여금": "Retained Earnings",
    "기타포괄손익누계액": "Accumulated Other Comprehensive Income",
    "기타자본": "Other Equity",
    # BS 합계 (접미사 없는 전체 매칭)
    "자산 총계": "Total Assets",
    "부채 총계": "Total Liabilities",
    "자본 총계": "Total Equity",
    "부채 및 자본 총계": "Total Liabilities and Equity",
    "부채 및 자본": "Liabilities and Equity",
    # IS 섹션
    "매출": "Revenue",
    "매출원가": "Cost of Goods Sold",
    "판매비와관리비": "Selling, General and Administrative Expenses",
    "영업외수익": "Non-operating Income",
    "영업외비용": "Non-operating Expenses",
    "법인세등": "Income Tax Expense",
    # IS 손익 소계
    "매출총이익": "Gross Profit",
    "영업이익": "Operating Income",
    "법인세차감전순이익": "Income Before Income Tax",
    "당기순이익": "Net Income",
    # 현금흐름
    "현금흐름표": "Cash Flow Statement",
    "영업활동으로 인한 현금흐름": "Cash Flows from Operating Activities",
    "투자활동으로 인한 현금흐름": "Cash Flows from Investing Activities",
    "재무활동으로 인한 현금흐름": "Cash Flows from Financing Activities",
    "현금 및 현금성자산 순증가": "Net Change in Cash and Cash Equivalents",
    "기초 현금": "Beginning Cash",
    "기말 현금": "Ending Cash",
    # 시산표
    "시산표": "Trial Balance",
    "합계": "Total",
    # 결손금 처리
    "미처리결손금": "Unappropriated Deficit",
    "이월결손금": "Retained Deficit Carried Forward",
}

SUFFIX_EN: dict[str, str] = {
    "소계": "Subtotal",
    "합계": "Total",
    "총계": "Grand Total",
}


def translate_label(label: str, account_code: str | None, name_en_map: dict[str, str]) -> str:
    """라벨(한글) → 영문 변환.

    - account_code가 있으면 name_en_map lookup
    - "X Y 소계"/"X Y 합계" 패턴은 base_ko 분리 후 EN suffix 결합
    - 그 외에는 LABEL_EN dict를 조회, 없으면 원문 유지
    """
    if not label:
        return label
    stripped = label.lstrip(" ")
    indent = " " * (len(label) - len(stripped))

    if account_code:
        # "  직원급여" 또는 "      이익잉여금 (당기순이익 포함)"
        base = stripped
        suffix = ""
        # 괄호 주석 분리
        if " (" in base and base.endswith(")"):
            paren_start = base.find(" (")
            suffix_ko = base[paren_start + 2 : -1]
            base = base[:paren_start]
            suffix_en_paren = "incl. net income" if "당기순이익" in suffix_ko else suffix_ko
            suffix = f" ({suffix_en_paren})"
        name_en = name_en_map.get(account_code, base)
        return f"{indent}{name_en}{suffix}"

    # 1) 전체 문자열 정확 매칭 (예: "부채 및 자본 총계" → "Total Liabilities and Equity")
    if stripped in LABEL_EN:
        return f"{indent}{LABEL_EN[stripped]}"

    # 2) "소계"/"합계"/"총계" 접미사 분리 후 base 번역
    for suf_ko, suf_en in SUFFIX_EN.items():
        if stripped.endswith(" " + suf_ko):
            base_ko = stripped[: -(len(suf_ko) + 1)].strip()
            base_en = LABEL_EN.get(base_ko, base_ko)
            return f"{indent}{base_en} {suf_en}"
        if stripped == suf_ko:
            return f"{indent}{suf_en}"

    return f"{indent}{stripped}"


def load_name_en_map(cur) -> dict[str, str]:
    """standard_accounts의 code → name_en 매핑 로드."""
    cur.execute(
        "SELECT code, COALESCE(name_en, name) FROM standard_accounts WHERE code IS NOT NULL"
    )
    return {row[0]: row[1] for row in cur.fetchall()}

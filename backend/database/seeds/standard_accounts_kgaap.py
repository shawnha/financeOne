"""K-GAAP 표준계정 (회계법인 상세 코드 체계) 마스터 seed.

2025 확정 결산자료 + 2026 1월 가결산 원장에서 추출된 48개 실사용 계정 + 빠진 일반
K-GAAP 표준을 포괄한다. 재무제표 공시는 parent_code (공시 표기 그룹)로 집계.

한국 BPO 실무 기준:
- 한국 법인(한아원코리아·한아원리테일) 공용
- HOI는 별도 US GAAP (여기 포함 안 함)
- 연결재무제표 영/한 토글을 위해 name_en 포함

필드 설명:
- code: K-GAAP 상세 코드 (회계법인 원장과 동일)
- name: 한글 계정명
- name_en: 영문 계정명 (연결재무제표 영문 출력용)
- category: 자산/부채/자본/수익/비용 (BS/IS 구분)
- sub_category: 공시 그룹 (유동자산→당좌자산, 판매관리비 등)
- is_from_ledger: True=회계법인 원장 실제 사용, False=표준 보완용
- sort_order: 재무제표 표기 순서

회계법인 원장 실제 사용 계정에는 sort_order를 코드 그대로 대입,
표준 보완 계정은 +1 offset.
"""

# 원장 실사용 계정 48개 (2025+2026 합집합) — from extract_ledger_codes.py
KGAAP_SEED = [
    # ── 자산 > 유동자산 > 당좌자산 ──────────────
    {"code": "10100", "name": "현금", "name_en": "Cash",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "10300", "name": "보통예금", "name_en": "Bank deposits",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "10800", "name": "외상매출금", "name_en": "Accounts receivable",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "12000", "name": "미수금", "name_en": "Non-trade receivables",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "13100", "name": "선급금", "name_en": "Prepayments",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "13400", "name": "가지급금", "name_en": "Suspense accounts",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "13500", "name": "부가세대급금", "name_en": "VAT receivable",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "13600", "name": "선납세금", "name_en": "Prepaid taxes",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},
    {"code": "13700", "name": "주.임.종단기채권",
     "name_en": "Short-term receivables from employees",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": True},

    # ── 자산 > 유동자산 > 재고자산 ──────────────
    {"code": "14600", "name": "상품", "name_en": "Merchandise inventory",
     "category": "자산", "sub_category": "재고자산", "is_from_ledger": True},

    # ── 자산 > 비유동자산 > 투자자산 ────────────
    {"code": "17900", "name": "장기대여금", "name_en": "Long-term loans receivable",
     "category": "자산", "sub_category": "투자자산", "is_from_ledger": True},

    # ── 자산 > 기타 (코드 비표준 관찰) ─────────
    # 18400 회사설정계정과목 — 26년 1월에 88,500,000 차변 등장. 실제 분류 사용자 확인 필요.
    {"code": "18400", "name": "회사설정계정과목",
     "name_en": "Company-defined account",
     "category": "자산", "sub_category": "기타비유동자산",
     "is_from_ledger": True, "note": "실제 분류 사용자 확인 필요"},

    # ── 자산 > 비유동자산 > 유형자산 ────────────
    {"code": "21200", "name": "비품", "name_en": "Furniture and fixtures",
     "category": "자산", "sub_category": "유형자산", "is_from_ledger": True},
    {"code": "21900", "name": "시설장치", "name_en": "Facilities and equipment",
     "category": "자산", "sub_category": "유형자산", "is_from_ledger": True},

    # ── 자산 > 비유동자산 > 기타 ────────────────
    # 96200 임차보증금 — 회계법인 원장 코드가 9xxxx이지만 실제는 자산 (PDF 확인).
    {"code": "96200", "name": "임차보증금", "name_en": "Leasehold deposits",
     "category": "자산", "sub_category": "기타비유동자산", "is_from_ledger": True,
     "note": "회계법인 원장에서 9xxxx로 관찰됨. BS상 자산 위치."},

    # ── 부채 > 유동부채 ──────────────────────────
    {"code": "25100", "name": "외상매입금", "name_en": "Accounts payable",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": True},
    {"code": "25400", "name": "예수금", "name_en": "Withholdings",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": True},
    {"code": "25500", "name": "부가세예수금", "name_en": "VAT payable",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": True},
    {"code": "26200", "name": "미지급비용", "name_en": "Accrued expenses",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": True},
    {"code": "27500", "name": "미지급급여", "name_en": "Accrued payroll",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": True},

    # ── 부채 > 비유동부채 ────────────────────────
    {"code": "30300", "name": "주.임.종장기차입금",
     "name_en": "Long-term borrowings from employees",
     "category": "부채", "sub_category": "비유동부채", "is_from_ledger": True},
    {"code": "31500", "name": "조건부지분인수계약부채",
     "name_en": "Conditional equity purchase obligation",
     "category": "부채", "sub_category": "비유동부채", "is_from_ledger": True},

    # ── 자본 ────────────────────────────────────
    {"code": "33100", "name": "자본금", "name_en": "Paid-in capital",
     "category": "자본", "sub_category": "자본금", "is_from_ledger": True},
    {"code": "34100", "name": "주식발행초과금",
     "name_en": "Additional paid-in capital",
     "category": "자본", "sub_category": "자본잉여금", "is_from_ledger": True},
    {"code": "37600", "name": "이월결손금",
     "name_en": "Retained deficit carried forward",
     "category": "자본", "sub_category": "이익잉여금", "is_from_ledger": True},
    {"code": "37800", "name": "미처리결손금",
     "name_en": "Unappropriated deficit",
     "category": "자본", "sub_category": "이익잉여금", "is_from_ledger": True},

    # ── 수익 > 매출 ─────────────────────────────
    {"code": "40000", "name": "손익", "name_en": "P&L closing",
     "category": "수익", "sub_category": "결산", "is_from_ledger": True,
     "note": "결산 과정의 손익 대체 계정"},
    {"code": "40100", "name": "상품매출", "name_en": "Merchandise sales",
     "category": "수익", "sub_category": "매출", "is_from_ledger": True},
    {"code": "40200", "name": "매출환입및에누리",
     "name_en": "Sales returns and allowances",
     "category": "수익", "sub_category": "매출", "is_from_ledger": True,
     "note": "매출 차감 계정"},
    {"code": "41200", "name": "서비스매출", "name_en": "Service revenue",
     "category": "수익", "sub_category": "매출", "is_from_ledger": True},

    # ── 비용 > 매출원가 ─────────────────────────
    {"code": "45100", "name": "상품매출원가",
     "name_en": "Cost of goods sold",
     "category": "비용", "sub_category": "매출원가", "is_from_ledger": True},

    # ── 비용 > 판매관리비 ────────────────────────
    {"code": "80200", "name": "직원급여", "name_en": "Salaries",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "80500", "name": "퇴직급여", "name_en": "Retirement benefits",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False,
     "note": "실제 원장엔 없었지만 표준 보완"},
    {"code": "81100", "name": "복리후생비",
     "name_en": "Employee benefits",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "81200", "name": "여비교통비",
     "name_en": "Travel and transportation",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "81300", "name": "접대비(기업업무추진비)",
     "name_en": "Business entertainment",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "81700", "name": "세금과공과금",
     "name_en": "Taxes and dues",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "81900", "name": "지급임차료", "name_en": "Rent expense",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "82100", "name": "보험료", "name_en": "Insurance",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "82400", "name": "운반비", "name_en": "Freight out",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "82900", "name": "사무용품비", "name_en": "Office supplies",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "83000", "name": "소모품비", "name_en": "Consumables",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "83100", "name": "지급수수료",
     "name_en": "Fees and commissions",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "83300", "name": "광고선전비", "name_en": "Advertising",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},
    {"code": "83900", "name": "판매수수료", "name_en": "Sales commissions",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": True},

    # ── 영업외손익 ───────────────────────────────
    {"code": "90100", "name": "이자수익", "name_en": "Interest income",
     "category": "수익", "sub_category": "영업외수익", "is_from_ledger": True},
    {"code": "90700", "name": "외환차익",
     "name_en": "Foreign exchange gain",
     "category": "수익", "sub_category": "영업외수익", "is_from_ledger": True},
    {"code": "92900", "name": "국고보조금수익",
     "name_en": "Government subsidy income",
     "category": "수익", "sub_category": "영업외수익", "is_from_ledger": True},
    {"code": "93000", "name": "잡이익",
     "name_en": "Miscellaneous income",
     "category": "수익", "sub_category": "영업외수익", "is_from_ledger": True},
    {"code": "96000", "name": "잡손실",
     "name_en": "Miscellaneous losses",
     "category": "비용", "sub_category": "영업외비용", "is_from_ledger": True},

    # ── 표준 보완 (원장엔 없지만 일반 K-GAAP 자주 쓰이는 계정) ──
    # 실제 거래가 발생할 때를 대비해 미리 마스터에 등록.
    {"code": "10200", "name": "당좌예금", "name_en": "Checking deposits",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": False},
    {"code": "10400", "name": "단기금융상품",
     "name_en": "Short-term financial instruments",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": False},
    {"code": "10900", "name": "단기대여금",
     "name_en": "Short-term loans receivable",
     "category": "자산", "sub_category": "당좌자산", "is_from_ledger": False},
    {"code": "12700", "name": "감가상각누계액(비품)",
     "name_en": "Accumulated depreciation - F&F",
     "category": "자산", "sub_category": "유형자산", "is_from_ledger": False,
     "note": "비품 차감 계정"},
    {"code": "21950", "name": "감가상각누계액(시설장치)",
     "name_en": "Accumulated depreciation - facilities",
     "category": "자산", "sub_category": "유형자산", "is_from_ledger": False,
     "note": "시설장치 차감 계정"},
    {"code": "25200", "name": "미지급금", "name_en": "Non-trade payables",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": False},
    {"code": "25300", "name": "선수금", "name_en": "Advances from customers",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": False},
    {"code": "29000", "name": "단기차입금",
     "name_en": "Short-term borrowings",
     "category": "부채", "sub_category": "유동부채", "is_from_ledger": False},
    {"code": "30400", "name": "장기차입금",
     "name_en": "Long-term borrowings",
     "category": "부채", "sub_category": "비유동부채", "is_from_ledger": False},
    {"code": "34200", "name": "감자차익",
     "name_en": "Gain on capital reduction",
     "category": "자본", "sub_category": "자본잉여금", "is_from_ledger": False},
    {"code": "37100", "name": "이익준비금",
     "name_en": "Legal reserve",
     "category": "자본", "sub_category": "이익잉여금", "is_from_ledger": False},
    {"code": "51100", "name": "감가상각비", "name_en": "Depreciation",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False},
    {"code": "82800", "name": "통신비", "name_en": "Communications",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False},
    {"code": "84000", "name": "수도광열비", "name_en": "Utilities",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False},
    {"code": "84500", "name": "차량유지비",
     "name_en": "Vehicle maintenance",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False},
    {"code": "85000", "name": "교육훈련비", "name_en": "Training",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False},
    {"code": "85100", "name": "도서인쇄비",
     "name_en": "Books and printing",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False},
    {"code": "85200", "name": "수선비", "name_en": "Repairs",
     "category": "비용", "sub_category": "판매관리비", "is_from_ledger": False},
    {"code": "93300", "name": "이자비용", "name_en": "Interest expense",
     "category": "비용", "sub_category": "영업외비용", "is_from_ledger": False},
    {"code": "93600", "name": "외환차손",
     "name_en": "Foreign exchange loss",
     "category": "비용", "sub_category": "영업외비용", "is_from_ledger": False},
    {"code": "99800", "name": "법인세등",
     "name_en": "Corporate income tax",
     "category": "비용", "sub_category": "법인세비용", "is_from_ledger": False},
]


if __name__ == "__main__":
    from_ledger = [r for r in KGAAP_SEED if r.get("is_from_ledger")]
    supplement = [r for r in KGAAP_SEED if not r.get("is_from_ledger")]
    print(f"전체 {len(KGAAP_SEED)}개")
    print(f"  - 회계법인 원장 실사용: {len(from_ledger)}")
    print(f"  - 표준 보완: {len(supplement)}")
    print()
    # 카테고리별 count
    cats: dict[str, int] = {}
    for r in KGAAP_SEED:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print("카테고리별:")
    for k, v in sorted(cats.items()):
        print(f"  {k}: {v}개")

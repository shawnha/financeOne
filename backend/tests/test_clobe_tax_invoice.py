# clobe 세금계산서 파서 + 자연키 dedup 단위테스트
import io

import openpyxl

from backend.services.parsers.clobe_tax_invoice import (
    parse_clobe_tax_invoice,
    _norm_biz,
    _dec,
    _io_to_direction,
    _parse_date,
)
from backend.services.clobe_import_service import _natural_key


_HEADER = [
    "발급일자", "작성일자", "매출 매입 유형", "과세 유형", "거래처 상호",
    "거래처 사업자등록번호", "대표 품목", "공급가액", "세액", "합계금액",
    "수정 여부", "입금 예정일자", "내 사업자번호",
]


def _build_xlsx(rows_by_sheet: dict) -> bytes:
    """{sheet_name: [ [13개 컬럼...], ... ]} → clobe 양식 xlsx bytes."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in rows_by_sheet.items():
        ws = wb.create_sheet(name)
        ws.append(_HEADER)
        for r in rows:
            ws.append(r)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _row(io_type, cp, biz, item, amount, vat, total, write="2026-04-29", tax="일반"):
    return ["2026-04-29", write, io_type, tax, cp, biz, item, amount, vat, total, "", None, "1968103665"]


# ── 순수 헬퍼 ──────────────────────────────────────────────


def test_norm_biz():
    assert _norm_biz("213-06-37712") == "2130637712"
    assert _norm_biz("2130637712") == "2130637712"
    assert _norm_biz(None) is None
    assert _norm_biz("") is None


def test_io_to_direction():
    assert _io_to_direction("매출") == "sales"
    assert _io_to_direction("매입") == "purchase"
    assert _io_to_direction("기타") is None


def test_dec_negative_and_comma():
    assert _dec("-13,425,676") == -13425676
    assert _dec("9090909.0") == 9090909
    assert _dec("") == 0


def test_parse_date_iso_and_ymd():
    assert _parse_date("2026-04-29").isoformat() == "2026-04-29"
    assert _parse_date("20260429").isoformat() == "2026-04-29"
    assert _parse_date(None) is None


# ── 파서 ──────────────────────────────────────────────────


def test_parse_basic_sales():
    data = _build_xlsx({"전체": [
        _row("매출", "이수마트약국", "2130637712", "인프라 구축비", 9090909, 909091, 10000000),
    ]})
    res = parse_clobe_tax_invoice(data)
    assert res["stats"]["valid"] == 1
    p = res["parsed"][0]
    assert p["direction"] == "sales"
    assert p["entity_biz_no"] == "1968103665"
    assert p["counterparty"] == "이수마트약국"
    assert p["counterparty_biz_no"] == "2130637712"
    assert p["amount"] == 9090909.0
    assert p["vat"] == 909091.0
    assert p["total"] == 10000000.0
    assert p["issue_date"] == "2026-04-29"


def test_parse_amend_negative_row():
    # 수정(취소) 세금계산서 = 음수 → 그대로 파싱 (drop 금지)
    data = _build_xlsx({"전체": [
        _row("매출", "이수마트약국", "2130637712", "물품 공급의 건",
             -12205160, -1220516, -13425676, write="2026-01-27"),
    ]})
    res = parse_clobe_tax_invoice(data)
    assert res["stats"]["valid"] == 1
    assert res["parsed"][0]["total"] == -13425676.0


def test_parse_direction_from_io_column():
    data = _build_xlsx({"전체": [
        _row("매출", "A", "1112223334", "x", 100, 10, 110),
        _row("매입", "B", "5556667778", "y", 200, 20, 220),
    ]})
    res = parse_clobe_tax_invoice(data)
    assert res["stats"]["sales"] == 1
    assert res["stats"]["purchase"] == 1


def test_parse_prefers_jeonche_over_split_sheets():
    # '전체' 에 데이터가 있으면 매출/매입 시트는 무시 (중복 방지)
    data = _build_xlsx({
        "전체": [_row("매출", "A", "1112223334", "x", 100, 10, 110)],
        "매출": [_row("매출", "A", "1112223334", "x", 100, 10, 110)],
        "매입": [],
    })
    res = parse_clobe_tax_invoice(data)
    assert res["stats"]["valid"] == 1


def test_parse_falls_back_to_split_sheets_when_jeonche_empty():
    data = _build_xlsx({
        "전체": [],
        "매출": [_row("매출", "A", "1112223334", "x", 100, 10, 110)],
        "매입": [_row("매입", "B", "5556667778", "y", 200, 20, 220)],
    })
    res = parse_clobe_tax_invoice(data)
    assert res["stats"]["valid"] == 2


def test_parse_skips_unknown_io_type():
    data = _build_xlsx({"전체": [
        _row("환불", "A", "1112223334", "x", 100, 10, 110),
    ]})
    res = parse_clobe_tax_invoice(data)
    assert res["stats"]["valid"] == 0
    assert res["stats"]["errors"] == 1


# ── 자연키 dedup ────────────────────────────────────────────


def test_natural_key_matches_on_total_only():
    # 기존 행은 vat=0·amount=합계로 저장됨 → amount/vat 달라도 total 같으면 동일 키
    clobe_row = {"direction": "sales", "issue_date": "2026-01-27", "total": 14725876.0}
    legacy_like = {"direction": "sales", "issue_date": "2026-01-27", "total": 14725876.0}
    assert _natural_key(2, clobe_row) == _natural_key(2, legacy_like)


def test_natural_key_negative_distinct_from_positive():
    pos = {"direction": "sales", "issue_date": "2026-01-27", "total": 13425676.0}
    neg = {"direction": "sales", "issue_date": "2026-01-27", "total": -13425676.0}
    assert _natural_key(2, pos) != _natural_key(2, neg)


def test_natural_key_entity_and_direction_scoped():
    base = {"direction": "sales", "issue_date": "2026-01-27", "total": 100.0}
    assert _natural_key(2, base) != _natural_key(3, base)
    assert _natural_key(2, base) != _natural_key(2, {**base, "direction": "purchase"})

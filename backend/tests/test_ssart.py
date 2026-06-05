# SsArt SIMS OpenAPI transform 단위테스트 (VAT 역산·면세·dedup 키)
from datetime import date

from backend.services.integrations.ssart import (
    _split_vat,
    _ymd_to_date,
    _int_or_none,
    sales_api_to_row,
    purchase_api_to_row,
)


def test_split_vat_taxable():
    supply, vat = _split_vat(1100.0, taxable=True)
    assert supply == 1000.0
    assert vat == 100.0


def test_split_vat_exempt():
    # 면세(TAX_YN=N) → 공급가=합계, 부가세 0
    supply, vat = _split_vat(5000.0, taxable=False)
    assert supply == 5000.0
    assert vat == 0.0


def test_split_vat_none():
    assert _split_vat(None, taxable=True) == (None, None)


def test_ymd_to_date():
    assert _ymd_to_date("20260530") == date(2026, 5, 30)
    assert _ymd_to_date("") is None
    assert _ymd_to_date("2026-05-30") is None  # 8자리 숫자만


def test_int_or_none():
    assert _int_or_none("7") == 7
    assert _int_or_none("") is None
    assert _int_or_none(None) is None


def _sales_api_row(tax_yn="Y", out_amt="1100.00", fin_out_amt="1100.00"):
    return {
        "TRANS_DATE": "20260530", "TRANS_SEQ": "13", "OUT_YYMMDD": "20260530", "OUT_SEQ": "6",
        "OUT_CUST_CD": "50219", "OUT_CUST_NM": "동탄)아이튼튼약국", "OUT_CUST_PRT": "아이튼튼약국",
        "PRODUCT_CD": "00077", "PRODUCT_NM": "릴리)마운자로 펜 5mg", "PRODUCT_STANDARD": "5mg",
        "OUT_QTY": "5", "IO_GU": "매출",
        "FIN_UNIT_COST": "357120.00", "FIN_OUT_AMT": fin_out_amt,
        "UNIT_COST": "357120.00", "OUT_AMT": out_amt,
        "FIN_IN_UNIT_COST": "350103.00", "IN_UNIT_COST": "350103.00",
        "TAX_YN": tax_yn, "OTHER": "",
    }


def test_sales_transform_taxable():
    r = sales_api_to_row(_sales_api_row(tax_yn="Y", fin_out_amt="1100.00", out_amt="1100.00"))
    # dedup 키 (xlsx 와 동일)
    assert r["sales_date"] == date(2026, 5, 30)
    assert r["document_no"] == "13"        # TRANS_SEQ
    assert r["row_number"] == 6            # OUT_SEQ
    assert r["product_name"] == "릴리)마운자로 펜 5mg"
    # 합계(VAT포함) → 공급가 역산
    assert r["total_amount"] == 1100.0     # FIN_OUT_AMT (장부 합계)
    assert r["supply_amount"] == 1000.0
    assert r["vat"] == 100.0
    assert r["cogs_unit_price"] == 350103.0
    assert r["payee_code"] == "50219"


def test_sales_transform_exempt():
    # 면세: 부가세 0, 공급가=합계
    r = sales_api_to_row(_sales_api_row(tax_yn="N", fin_out_amt="5000.00", out_amt="5000.00"))
    assert r["total_amount"] == 5000.0
    assert r["supply_amount"] == 5000.0
    assert r["vat"] == 0.0


def test_purchase_transform():
    a = {
        "TRANS_DATE": "20260504", "TRANS_SEQ": "1", "IN_YYMMDD": "20260504", "IN_SEQ": "3",
        "IN_CUST_CD": "20016", "IN_CUST_NM": "티제이팜",
        "PRODUCT_CD": "00014", "PRODUCT_NM": "노보노)위고비", "PRODUCT_STANDARD": "2.4mg",
        "IN_QTY": "18", "FIN_UNIT_COST": "354372.00", "FIN_IN_AMT": "6378696.00",
        "UNIT_COST": "354372.00", "IN_AMT": "6378696.00", "TAX_YN": "N", "OTHER": "",
    }
    r = purchase_api_to_row(a)
    assert r["purchase_date"] == date(2026, 5, 4)
    assert r["document_no"] == "1"
    assert r["row_number"] == 3
    assert r["quantity"] == 18.0
    assert r["total_amount"] == 6378696.0
    # 면세 → 공급가=합계
    assert r["supply_amount"] == 6378696.0
    assert r["vat"] == 0.0

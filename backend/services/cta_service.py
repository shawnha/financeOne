"""CTA (환산차이) 계산 엔진

자산/부채: 기말환율, 수익/비용: 평균환율, 자본: 역사적환율
차이 → 30400 기타포괄손익누계액 (AOCI)
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from psycopg2.extensions import connection as PgConnection

from backend.services.bookkeeping_engine import get_all_account_balances
from backend.services.gaap_conversion_service import convert_kgaap_to_usgaap
from backend.services.exchange_rate_service import (
    get_closing_rate,
    get_average_rate,
    get_historical_rate,
)


DEFAULT_EQUITY_INCEPTION_DATE = date(2023, 1, 1)

# AOCI US GAAP 코드
AOCI_CODE = "3300"
# K-GAAP 자본조정 — 해외사업환산손익 (USD 기준 entity 를 KRW 로 환산할 때 발생)
KGAAP_CTA_CODE = "39200"


def _get_equity_inception_date(conn) -> date:
    """settings 테이블에서 법인 설립일 조회. 없으면 기본값 사용."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'equity_inception_date' AND entity_id IS NULL")
        row = cur.fetchone()
        cur.close()
        if row and isinstance(row[0], str):
            return date.fromisoformat(row[0])
    except Exception:
        pass
    return DEFAULT_EQUITY_INCEPTION_DATE


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def translate_entity_to_usd(
    conn: PgConnection,
    entity_id: int,
    fiscal_year: int,
    start_date: date,
    end_date: date,
) -> dict:
    """한국 법인의 KRW 잔액을 USD로 환산 + CTA 계산.

    Returns:
        {
            "translated_balances": [...],  # US GAAP 코드 + USD 금액
            "cta_amount": Decimal,
            "rates_used": {"closing": rate, "average": rate, "historical": rate},
            "summary": {"total_assets", "total_liabilities", "total_equity", "net_income"},
        }
    """
    # 1. KRW 잔액 조회
    all_balances = get_all_account_balances(conn, entity_id, to_date=end_date)
    period_balances = get_all_account_balances(conn, entity_id, from_date=start_date, to_date=end_date)

    # 2. K-GAAP → US GAAP 변환
    usgaap_all = convert_kgaap_to_usgaap(conn, all_balances)
    usgaap_period = convert_kgaap_to_usgaap(conn, period_balances)

    # 3. 환율 조회
    closing_rate = get_closing_rate(conn, "KRW", "USD", end_date)
    average_rate = get_average_rate(conn, "KRW", "USD", start_date, end_date)
    historical_rate = get_historical_rate(conn, "KRW", "USD", _get_equity_inception_date(conn))

    # 4. 환산
    translated = []
    total_assets_usd = Decimal("0")
    total_liabilities_usd = Decimal("0")
    total_equity_usd = Decimal("0")  # 역사적환율 적용 자본

    for bal in usgaap_all:
        category = bal["us_gaap_category"]
        krw_balance = Decimal(str(bal["balance"]))

        if category in ("Assets",):
            rate = closing_rate
            usd_balance = _quantize(krw_balance * rate)
            total_assets_usd += usd_balance
        elif category in ("Liabilities",):
            rate = closing_rate
            usd_balance = _quantize(krw_balance * rate)
            total_liabilities_usd += usd_balance
        elif category in ("Equity",):
            rate = historical_rate
            usd_balance = _quantize(krw_balance * rate)
            total_equity_usd += usd_balance
        else:
            # Revenue/Expenses는 기간 잔액에서 처리
            rate = Decimal("0")
            usd_balance = Decimal("0")

        if category in ("Assets", "Liabilities", "Equity"):
            translated.append({
                "us_gaap_code": bal["us_gaap_code"],
                "us_gaap_name": bal["us_gaap_name"],
                "category": category,
                "krw_balance": float(krw_balance),
                "usd_balance": float(usd_balance),
                "rate_used": float(rate),
                "rate_type": "closing" if category in ("Assets", "Liabilities") else "historical",
            })

    # 수익/비용은 기간 잔액으로 환산 (평균환율)
    net_income_usd = Decimal("0")
    for bal in usgaap_period:
        category = bal["us_gaap_category"]
        krw_balance = Decimal(str(bal["balance"]))

        if category == "Revenue":
            usd_balance = _quantize(krw_balance * average_rate)
            net_income_usd += usd_balance
            translated.append({
                "us_gaap_code": bal["us_gaap_code"],
                "us_gaap_name": bal["us_gaap_name"],
                "category": category,
                "krw_balance": float(krw_balance),
                "usd_balance": float(usd_balance),
                "rate_used": float(average_rate),
                "rate_type": "average",
            })
        elif category == "Expenses":
            usd_balance = _quantize(krw_balance * average_rate)
            net_income_usd -= usd_balance
            translated.append({
                "us_gaap_code": bal["us_gaap_code"],
                "us_gaap_name": bal["us_gaap_name"],
                "category": category,
                "krw_balance": float(krw_balance),
                "usd_balance": float(usd_balance),
                "rate_used": float(average_rate),
                "rate_type": "average",
            })

    # 5. CTA 계산
    # 환산 후: 자산 = 부채 + 자본 + 이익잉여금(환산 순이익) + CTA
    # CTA = 자산 - 부채 - 자본 - 순이익
    cta = total_assets_usd - total_liabilities_usd - total_equity_usd - net_income_usd

    return {
        "translated_balances": translated,
        "cta_amount": float(_quantize(cta)),
        "rates_used": {
            "closing": float(closing_rate),
            "average": float(average_rate),
            "historical": float(historical_rate),
        },
        "summary": {
            "total_assets_usd": float(total_assets_usd),
            "total_liabilities_usd": float(total_liabilities_usd),
            "total_equity_usd": float(total_equity_usd),
            "net_income_usd": float(net_income_usd),
        },
    }


def translate_entity_to_krw(
    conn: PgConnection,
    entity_id: int,
    fiscal_year: int,
    start_date: date,
    end_date: date,
) -> dict:
    """USD 법인(HOI)의 잔액을 KRW로 환산 + CTA 계산.

    KRW 기준 연결재무제표용. K-GAAP standard_accounts 코드 그대로 사용
    (HOI 의 분개도 standard_accounts 에 매핑되어 있음).

    Returns: translate_entity_to_usd 와 동일 구조 (단, krw_balance/usd_balance 키만 반대)
    """
    all_balances = get_all_account_balances(conn, entity_id, to_date=end_date)
    period_balances = get_all_account_balances(conn, entity_id, from_date=start_date, to_date=end_date)

    closing_rate = get_closing_rate(conn, "USD", "KRW", end_date)
    average_rate = get_average_rate(conn, "USD", "KRW", start_date, end_date)
    historical_rate = get_historical_rate(conn, "USD", "KRW", _get_equity_inception_date(conn))

    translated = []
    total_assets_krw = Decimal("0")
    total_liabilities_krw = Decimal("0")
    total_equity_krw = Decimal("0")

    for bal in all_balances:
        category = bal["category"]
        usd_balance = Decimal(str(bal["balance"]))

        if category in ("Assets", "자산"):
            rate = closing_rate
            krw_balance = _quantize(usd_balance * rate)
            total_assets_krw += krw_balance
            cat_norm = "자산"
        elif category in ("Liabilities", "부채"):
            rate = closing_rate
            krw_balance = _quantize(usd_balance * rate)
            total_liabilities_krw += krw_balance
            cat_norm = "부채"
        elif category in ("Equity", "자본"):
            rate = historical_rate
            krw_balance = _quantize(usd_balance * rate)
            total_equity_krw += krw_balance
            cat_norm = "자본"
        else:
            continue

        translated.append({
            "code": bal["code"],
            "name": bal["name"],
            "category": cat_norm,
            "usd_balance": float(usd_balance),
            "krw_balance": float(krw_balance),
            "rate_used": float(rate),
            "rate_type": "closing" if cat_norm in ("자산", "부채") else "historical",
        })

    net_income_krw = Decimal("0")
    for bal in period_balances:
        category = bal["category"]
        usd_balance = Decimal(str(bal["balance"]))
        if category in ("Revenue", "수익", "Income"):
            krw_balance = _quantize(usd_balance * average_rate)
            net_income_krw += krw_balance
            cat_norm = "수익"
        elif category in ("Expense", "Expenses", "비용", "Cost of Goods Sold"):
            krw_balance = _quantize(usd_balance * average_rate)
            net_income_krw -= krw_balance
            cat_norm = "비용"
        else:
            continue

        translated.append({
            "code": bal["code"],
            "name": bal["name"],
            "category": cat_norm,
            "usd_balance": float(usd_balance),
            "krw_balance": float(krw_balance),
            "rate_used": float(average_rate),
            "rate_type": "average",
        })

    cta = total_assets_krw - total_liabilities_krw - total_equity_krw - net_income_krw

    return {
        "translated_balances": translated,
        "cta_amount": float(_quantize(cta)),
        "rates_used": {
            "closing": float(closing_rate),
            "average": float(average_rate),
            "historical": float(historical_rate),
        },
        "summary": {
            "total_assets_krw": float(total_assets_krw),
            "total_liabilities_krw": float(total_liabilities_krw),
            "total_equity_krw": float(total_equity_krw),
            "net_income_krw": float(net_income_krw),
        },
    }

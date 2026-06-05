# 코쿼핏(사장님 뷰) 서비스 단위 test — DB 없이 mock cursor + _fx_rate 몽키패치
"""fetch_cockpit_ceo 재무 정확성 검증 (DB 없이).

핵심:
- 법인 native 값 보존 (환산은 그룹에서만).
- 그룹 환산 합산 = Σ(native × 통화별 환율). 팬텀 1:1 절대 금지.
- 미지원 통화는 1.0 위조 대신 raise (그룹 총액 $123M 가짜 버그 회귀 방지).
- runway = balance / -net (적자일 때만, 흑자면 None).
- trend = 선택월 포함 최근 3개월.
"""

from decimal import Decimal

import pytest

from backend.services import cockpit_service as cs
from backend.services.dashboard_service import ExchangeRateNotFoundError


class _SeqCursor:
    """execute() 순서대로 미리 정한 fetchall() 결과를 돌려주는 fake cursor.

    fetch_cockpit_ceo 의 쿼리 순서: ① entities ② flow ③ balance ④ trend.
    """
    def __init__(self, fetchall_results):
        self._results = list(fetchall_results)
        self._i = -1

    def execute(self, *a, **k):
        self._i += 1

    def fetchall(self):
        if 0 <= self._i < len(self._results):
            return self._results[self._i]
        return []

    def close(self):
        pass


def _conn(fetchall_results):
    class _Conn:
        def cursor(self):
            return _SeqCursor(fetchall_results)
    return _Conn()


# KRW→USD = 1/1250, USD→KRW = 1250 (배지용). 그 외는 데이터 없음.
_RATES = {("KRW", "USD"): Decimal("0.0008"), ("USD", "KRW"): Decimal("1250")}


def _fake_fx(conn, frm, to, as_of=None):
    if frm == to:
        return Decimal("1")
    if (frm, to) in _RATES:
        return _RATES[(frm, to)]
    raise ExchangeRateNotFoundError(f"no rate {frm}->{to}")


@pytest.fixture
def patch_fx(monkeypatch):
    monkeypatch.setattr(cs, "_fx_rate", _fake_fx)


# ── 정상 케이스: USD 1법인 + KRW 1법인 ──
def _two_entity_results():
    entities = [
        (1, "HOI", "HOI", "USD"),
        (2, "HOK", "한아원코리아", "KRW"),
    ]
    flow = [
        # entity_id, op_in, op_out, nonop_in, nonop_out
        (1, Decimal("1000"), Decimal("1500"), Decimal("0"), Decimal("0")),               # HOI (USD), 비영업 없음
        (2, Decimal("1000000"), Decimal("2000000"), Decimal("500000"), Decimal("300000")),  # HOK (KRW) + 비영업 차입/대여
    ]
    balance = [
        (1, Decimal("5000")),       # HOI (USD)
        (2, Decimal("3000000")),    # HOK (KRW)
    ]
    trend = [
        ("2026-03", "USD", Decimal("-500")), ("2026-03", "KRW", Decimal("-1000000")),
        ("2026-04", "USD", Decimal("100")),  ("2026-04", "KRW", Decimal("500000")),
        ("2026-05", "USD", Decimal("-500")), ("2026-05", "KRW", Decimal("-1000000")),
    ]
    return [entities, flow, balance, trend]


def test_entity_native_values_preserved(patch_fx):
    """법인 행은 자국통화 그대로 — 환산하지 않는다."""
    r = cs.fetch_cockpit_ceo(_conn(_two_entity_results()), "USD", "2026-05")
    hok = next(e for e in r["entities"] if e["id"] == 2)
    assert hok["currency"] == "KRW"
    assert hok["income"] == Decimal("1000000")
    assert hok["expense"] == Decimal("2000000")
    assert hok["net"] == Decimal("-1000000")
    assert hok["balance"] == Decimal("3000000")


def test_group_sum_uses_per_currency_rate_not_one_to_one(patch_fx):
    """그룹 합산 = USD native + KRW×0.0008. 1:1 합산 금지 검증."""
    r = cs.fetch_cockpit_ceo(_conn(_two_entity_results()), "USD", "2026-05")
    g = r["group"]
    # 수입: 1000(USD) + 1000000×0.0008 = 1800
    assert g["income"] == Decimal("1000") + Decimal("1000000") * Decimal("0.0008")
    # 지출: 1500 + 2000000×0.0008 = 3100
    assert g["expense"] == Decimal("1500") + Decimal("2000000") * Decimal("0.0008")
    # 1:1 로 합쳤다면 income 이 1,001,000 이 됐을 것 — 그게 아님을 확인
    assert g["income"] < Decimal("10000")


def test_group_net_and_runway(patch_fx):
    """net = income - expense, runway = balance / -net (적자)."""
    r = cs.fetch_cockpit_ceo(_conn(_two_entity_results()), "USD", "2026-05")
    g = r["group"]
    assert g["net"] == g["income"] - g["expense"]
    assert g["net"] < 0
    assert g["runway_months"] == g["balance"] / (-g["net"])


def test_runway_none_when_surplus(patch_fx):
    """흑자면 runway None."""
    results = _two_entity_results()
    # HOI 수입 > 지출 + HOK 수입 > 지출 로 그룹 흑자 (영업기준, 비영업 0)
    results[1] = [
        (1, Decimal("9000"), Decimal("1000"), Decimal("0"), Decimal("0")),
        (2, Decimal("3000000"), Decimal("1000000"), Decimal("0"), Decimal("0")),
    ]
    r = cs.fetch_cockpit_ceo(_conn(results), "USD", "2026-05")
    assert r["group"]["net"] > 0
    assert r["group"]["runway_months"] is None


def test_trend_has_three_months(patch_fx):
    """추세 = 선택월 포함 최근 3개월."""
    r = cs.fetch_cockpit_ceo(_conn(_two_entity_results()), "USD", "2026-05")
    months = [p["month"] for p in r["trend"]]
    assert months == ["2026-03", "2026-04", "2026-05"]


def test_fx_badge_present(patch_fx):
    r = cs.fetch_cockpit_ceo(_conn(_two_entity_results()), "USD", "2026-05")
    assert r["fx"]["usd_krw"] == Decimal("1250")
    assert r["fx"]["as_of"] == "2026-05-31"
    assert r["display_currency"] == "USD"
    assert r["year_month"] == "2026-05"


# ── 재무 정확성 회귀 방지: 미지원 통화 1:1 위조 금지 ──
def test_unsupported_currency_raises_not_phantom_one(patch_fx):
    """환율 없는 통화(JPY)는 1.0 으로 위조해 합산하지 않고 명시적으로 실패한다."""
    entities = [
        (1, "HOI", "HOI", "USD"),
        (99, "JPN", "가상법인", "JPY"),   # 환율 데이터 없음
    ]
    flow = [(1, Decimal("1000"), Decimal("500"), Decimal("0"), Decimal("0"))]
    balance = [(1, Decimal("5000"))]
    results = [entities, flow, balance, []]
    with pytest.raises(ExchangeRateNotFoundError):
        cs.fetch_cockpit_ceo(_conn(results), "USD", "2026-05")


# ── 영업/비영업 분리 (옵션1) ──
def test_entity_income_is_operating_only(patch_fx):
    """법인 income/expense 는 영업만 — 비영업(차입·대여)은 제외."""
    r = cs.fetch_cockpit_ceo(_conn(_two_entity_results()), "USD", "2026-05")
    hok = next(e for e in r["entities"] if e["id"] == 2)
    # op_in=1,000,000 (비영업 500,000 은 income 에 안 들어감)
    assert hok["income"] == Decimal("1000000")
    assert hok["expense"] == Decimal("2000000")


def test_group_nonop_reported_separately(patch_fx):
    """제외한 비영업은 group.nonop_income/expense 로 따로 환산 보고."""
    r = cs.fetch_cockpit_ceo(_conn(_two_entity_results()), "USD", "2026-05")
    g = r["group"]
    # HOK 비영업 유입 500,000 KRW × 0.0008 = 400, 유출 300,000 × 0.0008 = 240
    assert g["nonop_income"] == Decimal("500000") * Decimal("0.0008")
    assert g["nonop_expense"] == Decimal("300000") * Decimal("0.0008")
    # 영업 income 에는 비영업이 안 섞임
    assert g["income"] == Decimal("1000") + Decimal("1000000") * Decimal("0.0008")


def test_non_operating_codes_present():
    """제외 코드 집합 회귀 방지 — 차입금·대여금·가지급금·자본금 포함, 비어있지 않음."""
    assert cs._NON_OPERATING_CODES  # 비어있으면 영업필터 무력화
    for code in ("26000", "29300", "30300", "11400", "13400", "33100"):
        assert code in cs._NON_OPERATING_CODES

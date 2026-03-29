# 수출입은행 API 환율 Fetcher 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수출입은행 Open API를 호출하여 USD/KRW, EUR/KRW 일별 환율을 exchange_rates 테이블에 적재하는 fetcher 구현

**Architecture:** `exchange_rate_fetcher.py` 서비스가 수출입은행 API를 호출하고, 기존 exchange_rates 라우터에 fetch 엔드포인트를 추가한다. 기존 `exchange_rate_service.py`(읽기 전용)는 수정하지 않는다.

**Tech Stack:** Python, httpx (기존 프로젝트 패턴), FastAPI, pytest

---

## File Structure

- **Create:** `backend/services/exchange_rate_fetcher.py` — 수출입은행 API 호출 + DB UPSERT
- **Modify:** `backend/routers/exchange_rates.py` — `POST /api/exchange-rates/fetch` 엔드포인트 추가
- **Modify:** `.env` — `KOREAEXIM_API_KEY` 추가
- **Modify:** `.env.example` — `KOREAEXIM_API_KEY` placeholder 추가
- **Create:** `backend/tests/test_exchange_rate_fetcher.py` — fetcher 테스트

---

### Task 1: .env 설정

**Files:**
- Modify: `.env`
- Modify: `.env.example`

- [ ] **Step 1: .env에 API 키 추가**

`.env` 파일 끝에 추가:
```
# 수출입은행 환율 API
KOREAEXIM_API_KEY=j7aK0vUSrmDu49FXhIUfhEj2Nu8CkRco
```

- [ ] **Step 2: .env.example 업데이트**

기존 `BOK_API_KEY=` 줄을 `KOREAEXIM_API_KEY=`로 교체:
```
# 수출입은행 환율 API
KOREAEXIM_API_KEY=
```

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "chore: add KOREAEXIM_API_KEY to .env.example"
```

(`.env`는 gitignore 대상이므로 커밋하지 않음)

---

### Task 2: exchange_rate_fetcher.py 테스트 작성

**Files:**
- Create: `backend/tests/test_exchange_rate_fetcher.py`

- [ ] **Step 1: 테스트 파일 작성**

```python
"""수출입은행 API 환율 fetcher 테스트"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.services.exchange_rate_fetcher import (
    fetch_exchange_rates,
    parse_koreaexim_response,
    save_rates_to_db,
    KoreaeximApiError,
)


# 수출입은행 API 실제 응답 형태
SAMPLE_API_RESPONSE = [
    {
        "result": 1,
        "cur_unit": "USD",
        "cur_nm": "미 달러",
        "ttb": "1,448.48",
        "tts": "1,477.91",
        "deal_bas_r": "1,463.2",
        "bkpr": "1,463",
        "yy_efee_r": "0",
        "ten_dd_efee_r": "0",
        "kftc_deal_bas_r": "1,463.2",
        "kftc_bkpr": "1,463",
    },
    {
        "result": 1,
        "cur_unit": "EUR",
        "cur_nm": "유로",
        "ttb": "1,574.51",
        "tts": "1,606.48",
        "deal_bas_r": "1,590.5",
        "bkpr": "1,590",
        "kftc_deal_bas_r": "1,590.5",
        "kftc_bkpr": "1,590",
    },
    {
        "result": 1,
        "cur_unit": "JPY(100)",
        "cur_nm": "일본 엔",
        "deal_bas_r": "978.12",
    },
]


class TestParseKoreaeximResponse:
    def test_extracts_usd_and_eur(self):
        rates = parse_koreaexim_response(SAMPLE_API_RESPONSE, date(2026, 3, 28))
        assert len(rates) == 2
        usd = next(r for r in rates if r["from_currency"] == "USD")
        assert usd["to_currency"] == "KRW"
        assert usd["rate"] == Decimal("1463.2")
        assert usd["date"] == date(2026, 3, 28)

    def test_eur_rate(self):
        rates = parse_koreaexim_response(SAMPLE_API_RESPONSE, date(2026, 3, 28))
        eur = next(r for r in rates if r["from_currency"] == "EUR")
        assert eur["rate"] == Decimal("1590.5")

    def test_ignores_other_currencies(self):
        rates = parse_koreaexim_response(SAMPLE_API_RESPONSE, date(2026, 3, 28))
        cur_units = [r["from_currency"] for r in rates]
        assert "JPY(100)" not in cur_units
        assert "JPY" not in cur_units

    def test_empty_response(self):
        rates = parse_koreaexim_response([], date(2026, 3, 28))
        assert rates == []

    def test_api_error_result_code(self):
        """result != 1 이면 해당 항목 스킵"""
        error_response = [{"result": 2, "cur_unit": "USD", "deal_bas_r": "1,463.2"}]
        rates = parse_koreaexim_response(error_response, date(2026, 3, 28))
        assert rates == []


class TestSaveRatesToDb:
    def test_upserts_rates(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        rates = [
            {"date": date(2026, 3, 28), "from_currency": "USD", "to_currency": "KRW",
             "rate": Decimal("1463.2"), "source": "koreaexim"},
        ]
        count = save_rates_to_db(conn, rates)
        assert count == 1
        cur.execute.assert_called_once()
        conn.commit.assert_called_once()

    def test_empty_rates_no_commit(self):
        conn = MagicMock()
        count = save_rates_to_db(conn, [])
        assert count == 0
        conn.commit.assert_not_called()


class TestFetchExchangeRates:
    @patch("backend.services.exchange_rate_fetcher.httpx.get")
    def test_single_date(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_API_RESPONSE
        mock_get.return_value = mock_resp

        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        result = fetch_exchange_rates(
            conn, date(2026, 3, 28), date(2026, 3, 28), api_key="test-key"
        )
        assert result["fetched_dates"] == 1
        assert result["saved_rates"] == 2  # USD + EUR

    @patch("backend.services.exchange_rate_fetcher.httpx.get")
    def test_date_range(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_API_RESPONSE
        mock_get.return_value = mock_resp

        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        result = fetch_exchange_rates(
            conn, date(2026, 3, 27), date(2026, 3, 28), api_key="test-key"
        )
        assert result["fetched_dates"] == 2
        assert mock_get.call_count == 2

    @patch("backend.services.exchange_rate_fetcher.httpx.get")
    def test_api_failure_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        conn = MagicMock()
        with pytest.raises(KoreaeximApiError, match="500"):
            fetch_exchange_rates(
                conn, date(2026, 3, 28), date(2026, 3, 28), api_key="test-key"
            )
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_exchange_rate_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.exchange_rate_fetcher'`

---

### Task 3: exchange_rate_fetcher.py 구현

**Files:**
- Create: `backend/services/exchange_rate_fetcher.py`

- [ ] **Step 1: fetcher 구현**

```python
"""수출입은행 Open API 환율 수집기

API 문서: https://www.koreaexim.go.kr/ir/HPHKIR020M01?apino=2
- 영업일에만 데이터 제공 (주말/공휴일 → 빈 응답)
- deal_bas_r: 매매기준율 (기준 환율)
- 하루 1000회 제한
"""

import logging
import os
from datetime import date, timedelta
from decimal import Decimal

import httpx
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

KOREAEXIM_URL = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"
TARGET_CURRENCIES = {"USD", "EUR"}


class KoreaeximApiError(Exception):
    pass


def parse_koreaexim_response(data: list[dict], rate_date: date) -> list[dict]:
    """API 응답에서 USD/KRW, EUR/KRW 환율만 추출."""
    rates = []
    for item in data:
        if item.get("result") != 1:
            continue
        cur_unit = item.get("cur_unit", "")
        if cur_unit not in TARGET_CURRENCIES:
            continue
        raw_rate = item.get("deal_bas_r", "0").replace(",", "")
        if not raw_rate or raw_rate == "0":
            continue
        rates.append({
            "date": rate_date,
            "from_currency": cur_unit,
            "to_currency": "KRW",
            "rate": Decimal(raw_rate),
            "source": "koreaexim",
        })
    return rates


def save_rates_to_db(conn: PgConnection, rates: list[dict]) -> int:
    """환율 데이터를 exchange_rates 테이블에 UPSERT."""
    if not rates:
        return 0
    cur = conn.cursor()
    for r in rates:
        cur.execute(
            """
            INSERT INTO exchange_rates (date, from_currency, to_currency, rate, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (date, from_currency, to_currency)
            DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source
            """,
            [r["date"], r["from_currency"], r["to_currency"], r["rate"], r["source"]],
        )
    conn.commit()
    cur.close()
    return len(rates)


def fetch_exchange_rates(
    conn: PgConnection,
    start_date: date,
    end_date: date,
    api_key: str | None = None,
) -> dict:
    """start_date ~ end_date 범위의 환율을 수출입은행 API에서 가져와 DB에 저장.

    Returns: {"fetched_dates": int, "saved_rates": int, "skipped_dates": int}
    """
    key = api_key or os.environ.get("KOREAEXIM_API_KEY", "")
    if not key:
        raise KoreaeximApiError("KOREAEXIM_API_KEY not set")

    total_saved = 0
    skipped = 0
    current = start_date
    fetched_dates = 0

    while current <= end_date:
        fetched_dates += 1
        search_date = current.strftime("%Y%m%d")
        resp = httpx.get(
            KOREAEXIM_URL,
            params={"authkey": key, "searchdate": search_date, "data": "AP01"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            raise KoreaeximApiError(
                f"API returned {resp.status_code} for {search_date}: {resp.text}"
            )

        data = resp.json()
        if not data:
            # 주말/공휴일 — 데이터 없음
            logger.info("No exchange rate data for %s (holiday/weekend)", search_date)
            skipped += 1
            current += timedelta(days=1)
            continue

        rates = parse_koreaexim_response(data, current)
        saved = save_rates_to_db(conn, rates)
        total_saved += saved
        logger.info("Saved %d rates for %s", saved, search_date)

        current += timedelta(days=1)

    return {
        "fetched_dates": fetched_dates,
        "saved_rates": total_saved,
        "skipped_dates": skipped,
    }
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_exchange_rate_fetcher.py -v`
Expected: 9 passed

- [ ] **Step 3: Commit**

```bash
git add backend/services/exchange_rate_fetcher.py backend/tests/test_exchange_rate_fetcher.py
git commit -m "feat: 수출입은행 API 환율 fetcher + 테스트"
```

---

### Task 4: 라우터에 fetch 엔드포인트 추가

**Files:**
- Modify: `backend/routers/exchange_rates.py` — `POST /api/exchange-rates/fetch` 추가

- [ ] **Step 1: 엔드포인트 추가**

`backend/routers/exchange_rates.py` 끝에 추가:

```python
from backend.services.exchange_rate_fetcher import (
    fetch_exchange_rates,
    KoreaeximApiError,
)

class FetchRequest(BaseModel):
    start_date: date
    end_date: date


@router.post("/fetch")
def fetch_rates_from_koreaexim(
    body: FetchRequest,
    conn: PgConnection = Depends(get_db),
):
    """수출입은행 API에서 환율 데이터를 가져와 DB에 저장."""
    if (body.end_date - body.start_date).days > 365:
        raise HTTPException(400, "Date range must be within 365 days")
    try:
        result = fetch_exchange_rates(conn, body.start_date, body.end_date)
        return result
    except KoreaeximApiError as e:
        raise HTTPException(502, str(e))
```

- [ ] **Step 2: 전체 테스트 실행**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/ -v`
Expected: All tests pass (기존 151 + 새 9 = 160)

- [ ] **Step 3: Commit**

```bash
git add backend/routers/exchange_rates.py .env.example
git commit -m "feat: POST /api/exchange-rates/fetch 엔드포인트 추가"
```

---

### Task 5: 실제 API 호출 테스트

- [ ] **Step 1: 서버 시작**

```bash
source .venv/bin/activate && uvicorn backend.main:app --reload
```

- [ ] **Step 2: fetch 엔드포인트 호출 (2026년 3월 전체)**

```bash
curl -X POST http://localhost:8000/api/exchange-rates/fetch \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-03-01", "end_date": "2026-03-29"}'
```

Expected: `{"fetched_dates": 29, "saved_rates": ~40, "skipped_dates": ~8}` (주말 제외)

- [ ] **Step 3: 저장된 환율 확인**

```bash
curl "http://localhost:8000/api/exchange-rates?from_currency=USD&to_currency=KRW&per_page=5"
```

Expected: USD/KRW 환율 데이터가 날짜별로 반환됨

- [ ] **Step 4: Commit all + push**

```bash
git add -A && git commit -m "chore: 수출입은행 환율 fetch 통합 테스트 완료"
```

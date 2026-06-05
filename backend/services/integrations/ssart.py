# SsArt SIMS OpenAPI 클라이언트 — 한아원홀세일 매출/매입/입출금/기초자료 자동 연동
"""SsArt(신성아트컴) SIMS OpenAPI 연동.

수동 매출관리/매입관리 xlsx 업로드를 대체하여 도매 매출·매입을 자동 pull.
응답을 기존 `wholesale_service.import_wholesale_sales/purchases` 가 받는 row dict 로
변환하므로 적재·중복제거(ON CONFLICT) 로직을 그대로 재사용한다.

핵심 주의사항 (2026-06-05 라이브 검증):
  - 인증 2단계: ACCESS_TOKEN(2주) → USE_TOKEN(48h). 모든 호출 body 에 USE_TOKEN.
  - 응답 인코딩은 cp949 (ks_c_5601-1987). UTF-8 디코딩 시 한글 깨짐.
  - 요청은 flat 파라미터 (가이드의 DATA:[{...}] 래퍼는 틀림 → 500).
  - OUT_AMT/IN_AMT = 합계금액(VAT 포함). 공급가 = ÷1.1 (TAX_YN='Y' 일 때만).
  - 레이트리밋: IP당 1분 300회 (E9999). 날짜별 조회로 호출 수 최소화.

env: SSART_API_URL, SSART_UID, SSART_PWD
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openapi.ssart.co.kr/api"
RESP_ENCODING = "cp949"          # 응답 인코딩 (EUC-KR 계열)
PAGE_SIZE = 1000                 # 하루 단위 조회라 보통 1페이지로 충분
VAT_RATE = 0.1


class SsArtError(Exception):
    """SsArt API 오류 (RESULT=N 또는 HTTP/파싱 실패)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "" or val == "null":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _ymd_to_date(val: Any) -> Optional[date]:
    s = str(val or "").strip()
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _int_or_none(val: Any) -> Optional[int]:
    s = str(val or "").strip()
    return int(s) if s.isdigit() else None


class SsArtClient:
    """SIMS OpenAPI 클라이언트. 매 인스턴스가 1회 인증 후 USE_TOKEN 재사용."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        uid: Optional[str] = None,
        pwd: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.base = (base_url or os.environ.get("SSART_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.uid = uid or os.environ.get("SSART_UID")
        self.pwd = pwd or os.environ.get("SSART_PWD")
        if not self.uid or not self.pwd:
            raise SsArtError("CONFIG", "SSART_UID / SSART_PWD 미설정")
        self._use_token: Optional[str] = None
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SsArtClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 저수준 호출 ──
    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base}{path}"
        try:
            resp = self._client.post(
                url,
                content=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise SsArtError("NETWORK", f"{path}: {e}") from e
        text = resp.content.decode(RESP_ENCODING, errors="replace")
        if resp.status_code != 200:
            raise SsArtError("HTTP", f"{path} {resp.status_code}: {text[:200]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise SsArtError("PARSE", f"{path}: 비JSON 응답 ({text[:160]})") from e

    # ── 인증 ──
    def authenticate(self) -> str:
        acc = self._post("/v1/oAuth/", {"uid": self.uid, "pwd": self.pwd})
        if acc.get("RESULT") != "Y" or not acc.get("ACCESS_TOKEN"):
            raise SsArtError(acc.get("ERRCODE", "?"), acc.get("ERRMSG") or "ACCESS_TOKEN 발급 실패")
        utk = self._post("/v1/oAuth/utk/", {"ACCESS_TOKEN": acc["ACCESS_TOKEN"]})
        if utk.get("RESULT") != "Y" or not utk.get("USE_TOKEN"):
            raise SsArtError(utk.get("ERRCODE", "?"), utk.get("ERRMSG") or "USE_TOKEN 발급 실패")
        self._use_token = utk["USE_TOKEN"]
        logger.info("SsArt 인증 성공 (USE_TOKEN 발급)")
        return self._use_token

    @property
    def use_token(self) -> str:
        if not self._use_token:
            self.authenticate()
        assert self._use_token
        return self._use_token

    # ── 페이지네이션 조회 (한 날짜 범위) ──
    def _paged(self, path: str, filters: dict) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while True:
            body = {"USE_TOKEN": self.use_token, "PAGE_NO": str(page), "PAGE_SIZE": str(PAGE_SIZE)}
            body.update(filters)
            data = self._post(path, body)
            code = data.get("ERRCODE")
            if data.get("RESULT") != "Y":
                # 결과 없음은 정상 (빈 리스트). 그 외는 에러.
                if code in ("E0001", "E0003") or str(data.get("COUNT") or "0") == "0":
                    break
                raise SsArtError(code or "?", data.get("ERRMSG") or f"{path} 조회 실패")
            chunk = data.get("DATA") or []
            rows.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                break
            page += 1
        return rows

    def _fetch_by_day(self, path: str, date_field: str, start: date, end: date) -> list[dict]:
        """날짜별로 끊어 조회 — E0005(결과과다) 회피 + 페이지네이션 단순화."""
        out: list[dict] = []
        d = start
        while d <= end:
            ymd = d.strftime("%Y%m%d")
            out.extend(self._paged(path, {date_field: f"{ymd}~{ymd}"}))
            d += timedelta(days=1)
        return out

    def fetch_sales(self, start: date, end: date) -> list[dict]:
        """매출 detail (출고일 기준) — 원시 API row 리스트."""
        return self._fetch_by_day("/v2/sales/get/", "OUT_DATE", start, end)

    def fetch_purchases(self, start: date, end: date) -> list[dict]:
        """매입 detail (입고일 기준) — 원시 API row 리스트."""
        return self._fetch_by_day("/v2/purchase/get/", "IN_DATE", start, end)


# ── 변환: API row → wholesale_service import dict ──
def _split_vat(total: Optional[float], taxable: bool) -> tuple[Optional[float], Optional[float]]:
    """합계(VAT포함) → (공급가, 부가세). 면세면 (합계, 0)."""
    if total is None:
        return None, None
    if not taxable:
        return total, 0.0
    supply = round(total / (1 + VAT_RATE))
    return float(supply), float(total - supply)


def sales_api_to_row(a: dict) -> dict:
    """매출 API row → import_wholesale_sales row dict.

    OUT_AMT/FIN_OUT_AMT = 합계(VAT포함). 공급가는 역산. dedup 키(document_no=TRANS_SEQ,
    row_number=OUT_SEQ, product_name)는 기존 매출관리 xlsx 와 동일.
    """
    taxable = (a.get("TAX_YN") or "").strip().upper() == "Y"
    fin_total = _to_float(a.get("FIN_OUT_AMT")) or 0.0   # 장부 합계
    real_total = _to_float(a.get("OUT_AMT")) or 0.0      # 실 합계
    fin_supply, fin_vat = _split_vat(fin_total, taxable)
    real_supply, _ = _split_vat(real_total, taxable)
    return {
        "sales_date": _ymd_to_date(a.get("OUT_YYMMDD")) or _ymd_to_date(a.get("TRANS_DATE")),
        "document_date": _ymd_to_date(a.get("TRANS_DATE")),
        "document_no": (str(a.get("TRANS_SEQ") or "").strip() or None),
        "row_number": _int_or_none(a.get("OUT_SEQ")),
        "payee_name": (a.get("OUT_CUST_NM") or "").strip(),
        "payee_code": (str(a.get("OUT_CUST_CD") or "").strip() or None),
        "real_payee_name": (a.get("OUT_CUST_PRT") or "").strip() or None,
        "product_name": (a.get("PRODUCT_NM") or "").strip(),
        "product_spec": (a.get("PRODUCT_STANDARD") or "").strip() or None,
        "manufacturer": None,  # detail 미제공 (제품마스터 연계 시)
        "quantity": _to_float(a.get("OUT_QTY")) or 0,
        "unit_price": _to_float(a.get("FIN_UNIT_COST")),       # 장부단가
        "discount_pct": None,
        "supply_amount": fin_supply,                            # 장부 공급가 (ex-VAT)
        "vat": fin_vat,
        "total_amount": fin_total,                              # 장부 합계 (VAT포함) → pnl revenue
        "real_unit_price": _to_float(a.get("UNIT_COST")),      # 실단가
        "real_supply_amount": real_supply,
        "real_total_amount": real_total,
        "cogs_unit_price": _to_float(a.get("FIN_IN_UNIT_COST")),   # 장부입고단가 = COGS 단가
        "cogs_real_unit_price": _to_float(a.get("IN_UNIT_COST")),
        "bank_settled": False,   # API 미제공
        "sales_rep": None,
        "note": (a.get("OTHER") or "").strip() or None,
        "raw_data": a,
    }


def purchase_api_to_row(a: dict) -> dict:
    """매입 API row → import_wholesale_purchases row dict."""
    taxable = (a.get("TAX_YN") or "").strip().upper() == "Y"
    fin_total = _to_float(a.get("FIN_IN_AMT")) or 0.0
    real_total = _to_float(a.get("IN_AMT")) or 0.0
    fin_supply, fin_vat = _split_vat(fin_total, taxable)
    real_supply, _ = _split_vat(real_total, taxable)
    return {
        "purchase_date": _ymd_to_date(a.get("IN_YYMMDD")) or _ymd_to_date(a.get("TRANS_DATE")),
        "document_date": _ymd_to_date(a.get("TRANS_DATE")),
        "document_no": (str(a.get("TRANS_SEQ") or "").strip() or None),
        "row_number": _int_or_none(a.get("IN_SEQ")),
        "payee_name": (a.get("IN_CUST_NM") or "").strip(),
        "product_name": (a.get("PRODUCT_NM") or "").strip(),
        "product_spec": (a.get("PRODUCT_STANDARD") or "").strip() or None,
        "quantity": _to_float(a.get("IN_QTY")) or 0,
        "unit_price": _to_float(a.get("FIN_UNIT_COST")),
        "supply_amount": fin_supply,
        "vat": fin_vat,
        "total_amount": fin_total,
        "real_unit_price": _to_float(a.get("UNIT_COST")),
        "real_supply_amount": real_supply,
        "real_total_amount": real_total,
        "bank_settled": False,
        "note": (a.get("OTHER") or "").strip() or None,
        "raw_data": a,
    }


# ── 동기화 오케스트레이션 (API pull → 기존 import 함수 재사용) ──
# import 함수는 commit 하지 않는다 → 호출측(라우터)이 commit.
def sync_sales(conn, entity_id: int, start: date, end: date, client: Optional[SsArtClient] = None):
    """SsArt 매출 → wholesale_sales (dedup ON CONFLICT)."""
    from backend.services.wholesale_service import import_wholesale_sales

    cli = client or SsArtClient()
    try:
        raw = cli.fetch_sales(start, end)
    finally:
        if client is None:
            cli.close()
    rows = [sales_api_to_row(a) for a in raw]
    rows = [r for r in rows if r["sales_date"] and r["product_name"] and r["payee_name"]]
    src = f"ssart_api:sales:{start:%Y%m%d}-{end:%Y%m%d}"
    return import_wholesale_sales(conn, entity_id, rows, source_file=src)


def sync_purchases(conn, entity_id: int, start: date, end: date, client: Optional[SsArtClient] = None):
    """SsArt 매입 → wholesale_purchases (dedup ON CONFLICT)."""
    from backend.services.wholesale_service import import_wholesale_purchases

    cli = client or SsArtClient()
    try:
        raw = cli.fetch_purchases(start, end)
    finally:
        if client is None:
            cli.close()
    rows = [purchase_api_to_row(a) for a in raw]
    rows = [r for r in rows if r["purchase_date"] and r["product_name"] and r["payee_name"]]
    src = f"ssart_api:purchase:{start:%Y%m%d}-{end:%Y%m%d}"
    return import_wholesale_purchases(conn, entity_id, rows, source_file=src)

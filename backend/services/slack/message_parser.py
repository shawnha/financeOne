"""Slack 메시지 파서 — 유형 분류 + 금액/VAT/태그 추출"""

import re
import json

# ── 유형 분류 ──────────────────────────────────────────

CARD_PAYMENT_KEYWORDS = ["결제완료", "결제 완료", "구매완료", "구매 완료", "법카로 결제"]
DEPOSIT_REQUEST_KEYWORDS = ["입금요청", "입금 요청", "입금 필요", "입금요청드립니다", "입금 부탁"]
TAX_INVOICE_KEYWORDS = ["세금계산서 발행", "세금계산서 요청"]
EXPENSE_KEYWORDS = ["결제", "구매", "비용", "입금", "지급", "발주", "견적", "인보이스", "invoice"]


def classify(text: str) -> str:
    if not text:
        return "other"
    for kw in CARD_PAYMENT_KEYWORDS:
        if kw in text:
            return "card_payment"
    for kw in DEPOSIT_REQUEST_KEYWORDS:
        if kw in text:
            return "deposit_request"
    for kw in TAX_INVOICE_KEYWORDS:
        if kw in text:
            return "tax_invoice"
    if extract_amount(text) is not None:
        return "expense_share"
    for kw in EXPENSE_KEYWORDS:
        if kw in text:
            return "expense_share"
    return "other"


# ── 금액 추출 ──────────────────────────────────────────

KRW_PATTERN = re.compile(r'(?:총\s*|총금액\s*[=:]\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})\s*원')
KRW_MAN_PATTERN = re.compile(r'(\d+)\s*만\s*원')
USD_PATTERN = re.compile(r'(?:US)?\$\s*([\d,]+(?:\.\d{1,2})?)')
USD_BUL_PATTERN = re.compile(r'(\d+(?:,\d+)?)\s*(?:불|달러)')
EUR_PATTERN = re.compile(r'€\s*([\d,]+(?:\.\d{1,2})?)|(\d+(?:,\d+)?)\s*(?:EURO|유로)')


def _parse_number(s: str) -> float:
    return float(s.replace(",", ""))


def extract_amount(text: str) -> dict | None:
    if not text:
        return None

    usd_matches = USD_PATTERN.findall(text)
    if usd_matches:
        amounts = [_parse_number(m) for m in usd_matches]
        return {"amount": max(amounts), "currency": "USD"}

    usd_bul = USD_BUL_PATTERN.findall(text)
    if usd_bul:
        amounts = [_parse_number(m) for m in usd_bul]
        return {"amount": max(amounts), "currency": "USD"}

    eur_matches = EUR_PATTERN.findall(text)
    for m1, m2 in eur_matches:
        val = m1 or m2
        if val:
            return {"amount": _parse_number(val), "currency": "EUR"}

    man_matches = KRW_MAN_PATTERN.findall(text)
    if man_matches:
        amounts = [int(m) * 10000 for m in man_matches]
        return {"amount": max(amounts), "currency": "KRW"}

    krw_matches = KRW_PATTERN.findall(text)
    if krw_matches:
        amounts = [_parse_number(m) for m in krw_matches]
        lines = text.split("\n")
        for line in lines:
            if any(kw in line for kw in ["합계", "총금액", "총액", "= "]):
                line_amounts = KRW_PATTERN.findall(line)
                if line_amounts:
                    return {"amount": _parse_number(line_amounts[-1]), "currency": "KRW"}
        return {"amount": max(amounts), "currency": "KRW"}

    return None


# ── 다중 항목 추출 ────────────────────────────────────

def extract_sub_amounts(text: str) -> list[dict]:
    lines = text.strip().split("\n")
    sub_items = []
    for line in lines:
        line = line.strip().lstrip("•-·")
        if any(kw in line for kw in ["합계", "총금액", "총액", "= "]):
            continue
        krw = KRW_PATTERN.findall(line)
        if krw:
            amount = _parse_number(krw[0])
            desc = KRW_PATTERN.sub("", line).strip().rstrip(":：/ ")
            sub_items.append({"amount": amount, "desc": desc[:100]})
    return sub_items if len(sub_items) >= 2 else []


# ── VAT 추출 ──────────────────────────────────────────

VAT_INCLUDED = ["VAT 포함", "vat+", "vat포함", "부가세 포함", "VAT+", "(vat+)"]
VAT_EXCLUDED = ["VAT 제외", "vat-", "vat제외", "부가세 별도", "VAT 별도", "VAT-", "(vat-)"]


def extract_vat(text: str) -> str:
    text_lower = text.lower()
    for kw in VAT_INCLUDED:
        if kw.lower() in text_lower:
            return "included"
    for kw in VAT_EXCLUDED:
        if kw.lower() in text_lower:
            return "excluded"
    return "none"


# ── 태그 추출 ─────────────────────────────────────────

TAG_PATTERN = re.compile(r'^\*?\[([^\]]+)\]', re.MULTILINE)


def extract_tag(text: str) -> str | None:
    m = TAG_PATTERN.search(text)
    return m.group(1) if m else None


# ── 원천징수 감지 ─────────────────────────────────────

WITHHOLDING_PATTERN = re.compile(r'3\.3%\s*(?:제외|공제)')


def detect_withholding(text: str) -> bool:
    return bool(WITHHOLDING_PATTERN.search(text))


# ── 날짜 추출 ─────────────────────────────────────────

DATE_PATTERN = re.compile(r'\((\d{1,2})/(\d{1,2})\)')


def extract_date_override(text: str, default_year: int = 2026) -> str | None:
    m = DATE_PATTERN.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{default_year}-{month:02d}-{day:02d}"
    return None


# ── 통합 파싱 ─────────────────────────────────────────

def parse_message(text: str, *, is_bot: bool = False, is_system: bool = False) -> dict:
    if is_bot or is_system:
        return {"message_type": "other", "skip": True}

    message_type = classify(text)
    amount_info = extract_amount(text)
    vat = extract_vat(text)
    tag = extract_tag(text)
    sub = extract_sub_amounts(text)
    withholding = detect_withholding(text)
    date_override = extract_date_override(text)

    parsed_amount = amount_info["amount"] if amount_info else None
    currency = amount_info["currency"] if amount_info else "KRW"

    vat_included = None
    if parsed_amount is not None:
        if vat == "included":
            vat_included = parsed_amount
        elif vat == "excluded":
            vat_included = round(parsed_amount * 1.1, 2)

    return {
        "message_type": message_type,
        "parsed_amount": parsed_amount,
        "parsed_amount_vat_included": vat_included,
        "currency": currency,
        "vat_flag": vat,
        "project_tag": tag,
        "sub_amounts": sub if sub else None,
        "withholding_tax": withholding,
        "date_override": date_override,
        "skip": message_type == "other" and parsed_amount is None,
    }

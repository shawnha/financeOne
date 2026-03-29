"""Slack 쓰레드 분석기 — 입금완료/취소/금액변경 이벤트 감지"""

from backend.services.slack.message_parser import extract_amount

DEPOSIT_DONE_KEYWORDS = [
    "입금완료", "입금 완료", "이체완료", "이체 완료",
    "송금완료", "송금 완료", "입금했습니다", "이체했습니다",
]

CANCEL_KEYWORDS = [
    "취소", "환불", "반품", "캔슬", "환불처리", "반품하였습니다",
]


def detect_deposit_done(text: str) -> bool:
    for kw in DEPOSIT_DONE_KEYWORDS:
        if kw in text:
            return True
    return False


def detect_cancel(text: str) -> bool:
    for kw in CANCEL_KEYWORDS:
        if kw in text:
            return True
    return False


def detect_amount_change(text: str, *, original_amount: float | None) -> float | None:
    if original_amount is None:
        return None
    result = extract_amount(text)
    if result and result["amount"] != original_amount:
        return result["amount"]
    return None


def analyze_thread(replies: list[dict], *, original_amount: float | None = None) -> dict:
    result = {
        "deposit_done": False,
        "cancelled": False,
        "new_amount": None,
        "file_urls": [],
    }

    for reply in replies:
        text = reply.get("text", "")
        files = reply.get("files", [])

        if detect_deposit_done(text):
            result["deposit_done"] = True

        if detect_cancel(text):
            result["cancelled"] = True

        amount_change = detect_amount_change(text, original_amount=original_amount)
        if amount_change is not None:
            result["new_amount"] = amount_change

        for f in files:
            url = f.get("url_private") or f.get("permalink")
            if url:
                result["file_urls"].append({"name": f.get("name", ""), "url": url})

    return result


def resolve_slack_status(message_type: str, has_check_reaction: bool, thread_events: dict) -> dict:
    if thread_events.get("cancelled"):
        return {"slack_status": "cancelled", "is_cancelled": True}

    if message_type == "card_payment":
        return {"slack_status": "done"}

    if thread_events.get("deposit_done"):
        return {"slack_status": "done"}

    if has_check_reaction:
        return {"slack_status": "done"}

    return {"slack_status": "pending"}

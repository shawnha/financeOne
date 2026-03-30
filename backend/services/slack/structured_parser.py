"""Claude Sonnet API로 Slack 경비 메시지를 구조화된 JSON으로 변환."""

import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)


# ── 프롬프트 ──────────────────────────────────────────────

SYSTEM_PROMPT = """한아원 그룹 내부 경비 Slack 메시지를 구조화된 JSON으로 변환하세요.

규칙:
- 금액은 숫자만 (콤마/원/만원 → 정수로 변환)
- VAT 별도(vat-)면 vat_amount에 10% 계산, supply_amount에 원금
- VAT 포함(vat+)면 supply_amount = 총액/1.1 (소수점 버림), vat_amount = 총액 - supply_amount
- 3.3% 원천징수 언급 시 withholding rate=3.3, amount=총액×0.033, net_amount=총액-amount
- 선금/잔금은 payment_terms.type으로 구분 (full/advance/balance/installment)
- 항목이 여러 개면 items 배열로 분리 (bullet 형식 아니어도, 문장 안의 나열도 분리)
- 확신 없는 필드는 null
- 쓰레드 댓글이 있으면 최종 상태(금액 변경, 입금 완료 등) 반영
- category는 다음 중 하나: 식비, 교통, 구독, 마케팅, 촬영, 배송, 인건비, 기타

반드시 아래 JSON 스키마만 반환하세요. 다른 텍스트 없이 JSON만 출력하세요.

{
  "summary": "1줄 요약 (한국어)",
  "vendor": "거래처/업체명 또는 null",
  "project": "프로젝트명 또는 null",
  "category": "식비|교통|구독|마케팅|촬영|배송|인건비|기타",
  "items": [{"description": "항목 설명", "amount": 숫자, "currency": "KRW|USD|EUR"}],
  "total_amount": 숫자,
  "currency": "KRW|USD|EUR",
  "vat": {"type": "none|included|excluded", "vat_amount": null, "supply_amount": null},
  "withholding_tax": {"applies": false, "rate": null, "amount": null, "net_amount": null},
  "payment_terms": {"type": "full|advance|balance|installment", "ratio": null, "related_context": null},
  "tax_invoice": false,
  "date_mentioned": "YYYY-MM-DD 또는 null",
  "urgency": "문자열 또는 null",
  "confidence": 0.0~1.0
}"""

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1024


# ── 프롬프트 빌드 ──────────────────────────────────────────

def build_user_prompt(text: str, *, thread_replies: str | None) -> str:
    """메시지 본문 + 쓰레드 댓글로 유저 프롬프트 생성."""
    prompt = f"[메시지 본문]\n{text}"

    if thread_replies:
        try:
            replies = json.loads(thread_replies)
            if replies:
                lines = []
                for r in replies:
                    sender = r.get("user", "unknown")
                    reply_text = r.get("text", "")
                    lines.append(f"{sender}: {reply_text}")
                prompt += f"\n\n[쓰레드 댓글]\n" + "\n".join(lines)
        except (json.JSONDecodeError, TypeError):
            pass

    return prompt


# ── 메인 파싱 함수 ────────────────────────────────────────

def parse_structured(
    text: str,
    *,
    thread_replies: str | None = None,
    skip: bool = False,
) -> dict | None:
    """Slack 메시지를 Claude Sonnet으로 구조화 파싱.

    Returns:
        파싱 결과 dict, 또는 실패/스킵 시 None.
    """
    if skip or not text or not text.strip():
        return None

    raw_text = None

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        user_prompt = build_user_prompt(text, thread_replies=thread_replies)

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if not response.content:
            logger.warning("structured_parse: empty content from API")
            return None
        raw_text = response.content[0].text.strip()

        # JSON 블록 추출 (```json ... ``` 감싸는 경우 대비)
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    json_lines.append(line)
            raw_text = "\n".join(json_lines)

        result = json.loads(raw_text)

        logger.info(
            "structured_parse OK: summary=%s, confidence=%.2f, tokens=%d+%d",
            result.get("summary", "?")[:30],
            result.get("confidence", 0),
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return result

    except json.JSONDecodeError as e:
        logger.warning(
            "structured_parse JSON error: %s | raw: %s",
            e,
            raw_text[:200] if raw_text is not None else "N/A",
        )
        return None
    except Exception as e:
        logger.warning("structured_parse API error: %s", e)
        return None

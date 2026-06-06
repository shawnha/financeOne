"""우리은행 통장명세에 '체크우리 *' 형태로 들어오는 우리체크카드 거래의 entity별 카드번호 매핑.

배경: 우리은행 통장명세 파서가 체크카드 결제 (적요='체크우리') 를 감지해도
카드번호는 명세에 안 나와서 추출 불가. card_number=NULL 이면 member 매핑도 실패.

이 매핑은 entity 의 우리체크카드 16자리 번호를 명시. upload.py 에서 lookup 해서
tx.card_number 를 채워주면 그 다음 `members.card_numbers` lookup 으로 holder 매핑됨.

새 entity 가 우리체크카드를 발급받으면 여기에 추가 (or 추후 card_settings 테이블로 이관).
"""

# entity_id → 16자리 우리체크카드 번호
WOORI_CHECK_CARD_NUMBERS: dict[int, str] = {
    2: "5339********5646",  # 한아원코리아 — 김대윤 명의
}


def get_woori_check_card_number(entity_id: int) -> str | None:
    """entity 의 우리체크카드 16자리 번호. 없으면 None."""
    return WOORI_CHECK_CARD_NUMBERS.get(entity_id)

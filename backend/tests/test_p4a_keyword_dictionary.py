"""P4-A 키워드 사전 단위테스트.

검증 대상:
  - DOMAIN_KEYWORDS 데이터 무결성 (중복 / 빈 / 잘못된 confidence)
  - 모든 keyword 가 stopword 가 아님
  - 모든 standard_account_code 가 5자리 숫자 형식
  - confidence 가 [0.5, 1.0] 범위
  - keyword 길이 >= 2 (한글) 또는 >= 3 (영문)
"""
import re

import pytest

from backend.scripts.expand_keyword_dictionary import DOMAIN_KEYWORDS


# Stopwords from Stage 3 design doc (D4) + P2-8 추가 한국 회사 prefix
STOPWORDS = {
    "주식회사", "(주)", "주식", "회사", "법인",
    "하나", "국민", "신한", "우리", "기업",
    "카드", "체크", "신용",
    "지점", "점", "역", "센터", "본점", "지사",
    "월", "일", "년", "원", "월급여",
    "USA", "INC", "CORP", "LLC", "LTD", "CITY", "CULVER",
    # P2-8: 추가 한국 회사 prefix (Code Reviewer 발견)
    "재단법인", "사단법인", "협동조합", "조합", "의료법인", "비영리",
}


def test_no_empty_keyword():
    for kw, code, conf in DOMAIN_KEYWORDS:
        assert kw and kw.strip(), f"빈 keyword 발견: {kw!r}"


def test_no_duplicate_keyword():
    seen = {}
    for idx, (kw, code, conf) in enumerate(DOMAIN_KEYWORDS):
        if kw in seen:
            pytest.fail(
                f"중복 keyword: {kw!r}  "
                f"({seen[kw]} → {code}, {idx} → {code})"
            )
        seen[kw] = code


def test_keyword_not_stopword():
    for kw, code, conf in DOMAIN_KEYWORDS:
        assert kw not in STOPWORDS, (
            f"stopword 가 키워드로 등록됨: {kw!r} (D4 noise filter 위반)"
        )


def test_standard_account_code_format():
    for kw, code, conf in DOMAIN_KEYWORDS:
        assert re.fullmatch(r"\d{5}", code), (
            f"잘못된 standard_account_code: {code!r} (5자리 숫자여야 함)"
        )


def test_confidence_range():
    for kw, code, conf in DOMAIN_KEYWORDS:
        assert 0.5 <= conf <= 1.0, (
            f"confidence 범위 이탈: keyword={kw!r} confidence={conf} (0.5~1.0 권장)"
        )


def test_keyword_min_length():
    """한글은 2자 이상.
    영문은 3자 이상, 단 pure uppercase brand 약자(KT, KCP 등)는 2자 허용.
    """
    for kw, code, conf in DOMAIN_KEYWORDS:
        is_hangul = any("가" <= ch <= "힣" for ch in kw)
        if is_hangul:
            assert len(kw) >= 2, f"한글 keyword 너무 짧음: {kw!r}"
        else:
            is_uppercase_brand = kw.isupper() and kw.isalpha()
            min_len = 2 if is_uppercase_brand else 3
            assert len(kw) >= min_len, (
                f"영문 keyword 너무 짧음: {kw!r} (min={min_len})"
            )


def test_dictionary_size_reasonable():
    """Phase 4 plan: ~150개 (정확한 숫자보다 범위 검증)."""
    n = len(DOMAIN_KEYWORDS)
    assert 80 <= n <= 250, f"DOMAIN_KEYWORDS 크기 이탈: {n}개 (80~250 권장)"


def test_no_overlap_with_existing_14():
    """초기 14개 키워드는 DB 에 이미 있으므로 신규 사전에서 제외."""
    existing_14 = {
        "회식", "택시", "식대", "커피", "사무용품", "인터넷",
        "전화", "임대", "월세", "급여", "보험", "광고", "수수료", "이자",
    }
    overlap = [kw for kw, _, _ in DOMAIN_KEYWORDS if kw in existing_14]
    # ON CONFLICT 로 skip 되긴 하지만, 명시적으로 중복 제외하는 게 깨끗함
    assert not overlap, f"기존 14개와 중복: {overlap}"


def test_categories_covered():
    """주요 카테고리 (50xxx) 가 모두 1개 이상 키워드 보유."""
    codes_seen = {code for _, code, _ in DOMAIN_KEYWORDS}
    must_have = {
        "50200",  # 급여
        "50300",  # 퇴직급여
        "50400",  # 복리후생비
        "50500",  # 임차료
        "50700",  # 통신비
        "50900",  # 세금과공과
        "51200",  # 차량유지비
        "51300",  # 여비교통비
        "51400",  # 소모품비
        "51500",  # 지급수수료
        "51510",  # SaaS 구독료
        "51520",  # 결제수수료
        "51600",  # 광고선전비
        "51700",  # 교육훈련비
        "51800",  # 도서인쇄비
        "52000",  # 이자비용
    }
    missing = must_have - codes_seen
    assert not missing, f"필수 카테고리 누락: {missing}"


def test_no_account_overflow():
    """P2-9: 한 standard_account_id 당 키워드 cap (≤ 25개) — 편향 방지."""
    from collections import Counter
    counter = Counter(code for _, code, _ in DOMAIN_KEYWORDS)
    over_cap = {code: n for code, n in counter.items() if n > 25}
    assert not over_cap, (
        f"한 계정에 키워드 25개 초과: {over_cap} (편향 위험, 분리 권장)"
    )


def test_no_short_english_substring_risk():
    """P0-1 회귀 방지: 영문 2-3자 키워드는 명시적 화이트리스트만 허용.
    'KT' 같은 짧은 약자가 'KTX', 'KT&G' 등에 false-positive 매칭하는 위험 차단.
    """
    SHORT_ENGLISH_WHITELIST = {
        "KFC", "BBQ",  # 식음료 브랜드, 명확
        "KCP", "AWS",  # 결제/SaaS 약자
        "SKT", "KTX",  # 통신/철도 약자 (longer-match 우선시 OK)
        "KTV",  # 외국어 약자
        "META",  # 광고 (4자)
        "Adobe Creative Cloud",  # 다단어 OK
    }
    for kw, code, conf in DOMAIN_KEYWORDS:
        is_english_only = kw.isascii() and not any(c.isspace() for c in kw)
        if is_english_only and 2 <= len(kw) <= 3 and kw.isupper():
            assert kw in SHORT_ENGLISH_WHITELIST, (
                f"짧은 영문 대문자 keyword '{kw}' 가 화이트리스트에 없음. "
                f"ILIKE substring false-positive 위험. "
                f"화이트리스트 확장 또는 keyword 구체화 (예: 'KT' → 'KT통신') 필요."
            )

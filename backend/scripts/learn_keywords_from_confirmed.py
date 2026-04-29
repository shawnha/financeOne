"""P4-5 매핑 학습 루프 — confirmed transactions 에서 키워드 자동 추출.

confirmed (mapping_source='confirmed') 거래의 counterparty 에서 자주 등장하는
브랜드/벤더 단어를 추출하여 standard_account_keywords 에 자동 INSERT.

실행 방식: 일/주 단위 cron 또는 수동. 신뢰도는 hit_count 기반 동적 산출.

기준:
  - hit_count >= 5 (최소 5번 confirmed 된 패턴)
  - 같은 counterparty pattern 이 90% 이상 같은 standard_account 에 매핑
  - keyword 길이 >= 3
  - 기존 standard_account_keywords 에 없는 것만
"""
import os
import re
import psycopg2
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()


MIN_HIT = 5
MIN_KEYWORD_LEN = 3
MIN_PURITY = 0.90  # 같은 키워드의 confirmed 매핑이 단일 std_account 로 90%+ 가야 함


# 노이즈 단어 — 키워드로 추출 안 함
STOPWORDS = {
    "주식회사", "(주)", "주식", "회사", "법인",
    "하나", "국민", "신한", "우리", "기업",  # 은행명 (별도 처리)
    "카드", "체크", "신용",
    "지점", "점", "역", "센터", "본점", "지사",
    "월", "일", "년", "원", "월급여",
}


def normalize(text: str) -> str:
    """공백/특수문자 정리."""
    if not text:
        return ""
    text = re.sub(r"[\s\(\)\[\]]+", " ", text)
    return text.strip()


def extract_words(text: str) -> list[str]:
    """counterparty 에서 의미있는 단어 추출."""
    text = normalize(text)
    # 한글/영문/숫자 단어 추출 (3자 이상)
    words = re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9]{2,}", text)
    return [w for w in words if w not in STOPWORDS]


def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # 1) confirmed 거래 + standard_account 정보
    cur.execute(
        """
        SELECT t.counterparty, t.standard_account_id
        FROM transactions t
        WHERE t.mapping_source = 'confirmed'
          AND t.standard_account_id IS NOT NULL
          AND t.counterparty IS NOT NULL
        """
    )
    rows = cur.fetchall()
    print(f"confirmed 거래: {len(rows)}건")

    # 2) 단어 추출 + standard_account 별 빈도 집계
    word_to_accounts = defaultdict(lambda: defaultdict(int))  # word → std_id → count
    for counterparty, std_id in rows:
        for word in extract_words(counterparty):
            word_to_accounts[word][std_id] += 1

    # 3) 후보 키워드 필터링
    cur.execute("SELECT keyword FROM standard_account_keywords")
    existing_keywords = {r[0] for r in cur.fetchall()}

    candidates = []
    for word, account_counts in word_to_accounts.items():
        if word in existing_keywords:
            continue
        if len(word) < MIN_KEYWORD_LEN:
            continue

        total = sum(account_counts.values())
        if total < MIN_HIT:
            continue

        # 가장 빈도 높은 std_account 의 비율
        top_std, top_count = max(account_counts.items(), key=lambda x: x[1])
        purity = top_count / total
        if purity < MIN_PURITY:
            continue

        # 신뢰도 = purity * 0.95 (글로벌 사전이라 약간 낮춤)
        confidence = round(min(0.95, purity * 0.95), 2)

        candidates.append({
            "keyword": word,
            "standard_account_id": top_std,
            "confidence": confidence,
            "hit_count": top_count,
            "purity": purity,
        })

    candidates.sort(key=lambda c: c["hit_count"], reverse=True)

    print(f"\n신규 키워드 후보: {len(candidates)}개\n")
    for c in candidates[:30]:
        cur.execute("SELECT code, name FROM standard_accounts WHERE id = %s", [c["standard_account_id"]])
        sa = cur.fetchone()
        print(f"  {c['keyword']:<20}  → {sa[0]} {sa[1]:<15}  hit={c['hit_count']}  purity={c['purity']:.2f}  conf={c['confidence']}")

    if len(candidates) > 30:
        print(f"  ... ({len(candidates) - 30}건 더)")

    # 4) INSERT
    inserted = 0
    for c in candidates:
        cur.execute(
            """
            INSERT INTO standard_account_keywords (keyword, standard_account_id, confidence)
            VALUES (%s, %s, %s)
            ON CONFLICT (keyword) DO NOTHING
            RETURNING id
            """,
            [c["keyword"], c["standard_account_id"], c["confidence"]],
        )
        if cur.fetchone():
            inserted += 1

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM standard_account_keywords")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"\n신규 INSERT: {inserted}건")
    print(f"전체 standard_account_keywords: {total}개")


if __name__ == "__main__":
    main()

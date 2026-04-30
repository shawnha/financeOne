"""P4-C 매핑 학습 루프 — confirmed transactions 에서 키워드 자동 추출.

설계 결정 (Stage 3 Eng Review):
  D3 Idempotency: ON CONFLICT (keyword) DO NOTHING (불변)
  D4 Noise filter (다층):
    1) Stopwords blacklist
    2) purity ≥ 0.90 (단일 standard_account 비율)
    3) hit_count ≥ 5
    4) keyword 길이 ≥ 3 (한글 2자, 영문 3자, 단 uppercase brand 약자 2자 허용)
    5) 영문은 lowercase 정규화 (중복 방지)
    6) 짧은 영문 대문자 (KT, KB 등) 화이트리스트 외 거부

이전 시도 교훈 (revert 됨):
  USA, CITY, CULVER 같은 광고지역명이 광고선전비 (51600) 로 잘못 등록됨.
  TIKTOK 거래의 부산물 — 실제 의미 없는 단어.
  → 이번엔 stopwords 강화 + 영문 짧은 단어 화이트리스트.

운영:
  - 일/주/월 cron 으로 실행
  - 정확도 측정 metric 기록 (.claude-tmp/mapping-metric-YYYY-MM-DD.json)
  - 새 키워드만 추가 (기존 confidence 보존)

사용법:
  source .venv/bin/activate
  python -m backend.scripts.learn_keywords_from_confirmed
  python -m backend.scripts.learn_keywords_from_confirmed --dry-run
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()


# Stage 3 D4 결정
MIN_HIT = 5
MIN_PURITY = 0.90
MIN_KEYWORD_LEN_KO = 2
MIN_KEYWORD_LEN_EN = 3


# 노이즈 필터 (Code Reviewer P2-8 + 이전 시도 교훈 반영)
STOPWORDS = {
    # 한국 회사 prefix
    "주식회사", "(주)", "주식", "회사", "법인",
    "재단법인", "사단법인", "협동조합", "조합", "의료법인", "비영리",
    # 은행명 (별도 처리, 노이즈)
    "하나", "국민", "신한", "우리", "기업",
    # 카드 노이즈
    "카드", "체크", "신용",
    # 위치 prefix
    "지점", "점", "역", "센터", "본점", "지사",
    # 시간 prefix
    "월", "일", "년", "원", "월급여",
    # 영문 회사 suffix
    "USA", "INC", "CORP", "LLC", "LTD", "CO",
    # 광고 지역명 (이전 시도에서 광고선전비로 잘못 등록된 단어들)
    "CITY", "CULVER", "STREET", "ROAD", "AVENUE", "ST", "RD", "AVE",
    # SaaS 플랫폼 노이즈
    "COM", "NET", "ORG", "WWW", "HTTP", "HTTPS",
}

# 짧은 영문 대문자 약자 (2자) 화이트리스트
SHORT_ENGLISH_WHITELIST = {
    "KFC", "BBQ",   # 식음료
    "KCP", "AWS",   # 결제/SaaS
    "SKT", "KTX",   # 통신/철도
    "KTV", "META",  # 광고
}


def normalize_text(text: str) -> str:
    """공백/특수문자 정리."""
    if not text:
        return ""
    text = re.sub(r"[\s\(\)\[\]]+", " ", text)
    return text.strip()


def extract_words(text: str) -> list[str]:
    """counterparty 에서 의미있는 단어 추출."""
    text = normalize_text(text)
    # 한글/영문/숫자 단어 추출 (2자 이상)
    words = re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9]{1,}", text)
    return words


def passes_noise_filter(word: str) -> bool:
    """다층 noise filter (D4)."""
    # 1) Stopword
    if word in STOPWORDS:
        return False
    # case-insensitive stopword check (영문)
    if word.upper() in STOPWORDS:
        return False

    # 2) 길이
    is_hangul = any("가" <= ch <= "힣" for ch in word)
    is_english = word.isascii() and word.replace(" ", "").isalnum()

    if is_hangul:
        if len(word) < MIN_KEYWORD_LEN_KO:
            return False
    elif is_english:
        # 영문 짧은 단어 (3자 이하) 는 모두 화이트리스트 체크
        # ADS/ads/Ads, INC/inc, LLC/llc 등 광고·회사 prefix 노이즈 차단
        if len(word) <= 3:
            if word.upper() not in SHORT_ENGLISH_WHITELIST:
                return False

    return True


def normalize_keyword_for_storage(word: str) -> str:
    """저장 전 정규화. 한글은 그대로, 영문 brand 약자는 대문자 보존, 일반 영문은 lowercase."""
    if not word.isascii():
        return word
    if word.isupper() and len(word) <= 4:
        # 짧은 영문 대문자는 brand 약자 가능성 → 보존
        return word
    return word.lower()


def extract_candidates(conn) -> list[dict]:
    """confirmed 거래 → 키워드 후보."""
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

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

    cur.execute("SELECT keyword FROM standard_account_keywords")
    existing = {r[0] for r in cur.fetchall()}

    cur.close()

    # 단어 → standard_account 빈도
    word_to_accounts = defaultdict(lambda: defaultdict(int))
    for counterparty, std_id in rows:
        for word in extract_words(counterparty):
            normalized = normalize_keyword_for_storage(word)
            if not passes_noise_filter(normalized):
                continue
            if normalized in existing:
                continue
            word_to_accounts[normalized][std_id] += 1

    # 후보 필터링
    candidates = []
    for word, account_counts in word_to_accounts.items():
        total = sum(account_counts.values())
        if total < MIN_HIT:
            continue

        top_std, top_count = max(account_counts.items(), key=lambda x: x[1])
        purity = top_count / total
        if purity < MIN_PURITY:
            continue

        confidence = round(min(0.95, purity * 0.95), 2)
        candidates.append({
            "keyword": word,
            "standard_account_id": top_std,
            "confidence": confidence,
            "hit_count": top_count,
            "purity": purity,
        })

    candidates.sort(key=lambda c: c["hit_count"], reverse=True)
    return candidates


def insert_candidates(conn, candidates: list[dict], dry_run: bool = False) -> int:
    """candidates → standard_account_keywords INSERT."""
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    inserted = 0
    for c in candidates:
        if dry_run:
            inserted += 1
            continue

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

    if not dry_run:
        conn.commit()
    cur.close()
    return inserted


def measure_coverage(conn) -> dict:
    """현재 매핑 정확도 측정 (Stage 3 D5).

    metric:
      - entity 별 매핑 비율
      - cascade source 분포
      - keyword count
      - 미매핑 거래수
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    metric = {"timestamp": str(date.today()), "entities": {}}

    cur.execute(
        """
        SELECT entity_id,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE standard_account_id IS NOT NULL) AS mapped_std,
               COUNT(*) FILTER (WHERE internal_account_id IS NOT NULL) AS mapped_int,
               COUNT(*) FILTER (WHERE standard_account_id IS NULL) AS unmapped
        FROM transactions
        GROUP BY entity_id
        ORDER BY entity_id
        """
    )
    for eid, total, m_std, m_int, unmapped in cur.fetchall():
        metric["entities"][eid] = {
            "total": total,
            "mapped_standard": m_std,
            "mapped_internal": m_int,
            "unmapped": unmapped,
            "coverage_std_pct": round(100 * m_std / total, 2) if total else 0,
            "coverage_int_pct": round(100 * m_int / total, 2) if total else 0,
        }

    cur.execute(
        """
        SELECT mapping_source, COUNT(*)
        FROM transactions
        WHERE mapping_source IS NOT NULL
        GROUP BY mapping_source
        ORDER BY 2 DESC
        """
    )
    metric["mapping_source"] = [{"source": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM standard_account_keywords")
    metric["standard_account_keywords"] = cur.fetchone()[0]

    cur.execute("SELECT entity_id, COUNT(*) FROM mapping_rules GROUP BY entity_id ORDER BY 1")
    metric["mapping_rules_by_entity"] = {r[0]: r[1] for r in cur.fetchall()}

    cur.close()
    return metric


def save_metric(metric: dict) -> Path:
    """metric → JSON snapshot. timestamp 가 metric 에 없으면 today 사용."""
    out_dir = Path("/Users/admin/Desktop/claude/financeOne/.claude-tmp")
    out_dir.mkdir(parents=True, exist_ok=True)
    # metric_only: timestamp 직접 사용. diff (before+after): before 의 timestamp 사용.
    timestamp = metric.get("timestamp")
    if not timestamp and "before" in metric:
        timestamp = metric["before"].get("timestamp")
    if not timestamp:
        timestamp = str(date.today())
    fname = f"mapping-metric-{timestamp}.json"
    out = out_dir / fname
    out.write_text(json.dumps(metric, ensure_ascii=False, indent=2))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="P4-C 키워드 학습 루프")
    parser.add_argument("--dry-run", action="store_true", help="INSERT 안 함, 후보만 출력")
    parser.add_argument("--metric-only", action="store_true", help="학습 안 함, metric 만 측정")
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        # Before metric
        before = measure_coverage(conn)
        print("=== BEFORE ===")
        print(f"  standard_account_keywords: {before['standard_account_keywords']}개")
        for eid, m in before["entities"].items():
            print(f"  entity={eid}  std={m['coverage_std_pct']}%  int={m['coverage_int_pct']}%  unmapped={m['unmapped']}")

        if args.metric_only:
            save_metric(before)
            return

        # 학습
        candidates = extract_candidates(conn)
        print(f"\n=== 후보 키워드 {len(candidates)}개 ===")
        for c in candidates[:20]:
            cur = conn.cursor()
            cur.execute("SET search_path TO financeone, public")
            cur.execute("SELECT code, name FROM standard_accounts WHERE id = %s", [c["standard_account_id"]])
            sa = cur.fetchone()
            cur.close()
            print(f"  {c['keyword']:<25}  → {sa[0]} {sa[1]:<15}  hit={c['hit_count']}  purity={c['purity']:.2f}  conf={c['confidence']}")
        if len(candidates) > 20:
            print(f"  ... ({len(candidates) - 20}건 더)")

        # INSERT
        inserted = insert_candidates(conn, candidates, dry_run=args.dry_run)
        action = "DRY-RUN INSERT" if args.dry_run else "INSERT"
        print(f"\n{action}: {inserted}건")

        # After metric
        after = measure_coverage(conn)
        print(f"\n=== AFTER ===")
        print(f"  standard_account_keywords: {after['standard_account_keywords']}개")

        # 비교 metric 저장
        diff = {
            "before": before,
            "after": after,
            "candidates": candidates,
            "inserted": inserted,
            "dry_run": args.dry_run,
        }
        out = save_metric(diff)
        print(f"\nmetric snapshot: {out}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

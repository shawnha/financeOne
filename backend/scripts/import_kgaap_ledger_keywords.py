"""K-GAAP 결산자료 계정별원장 → standard_account_keywords 학습 import.

Source 파일:
  - 한아원코리아 25년: 46시트
  - 도팜인 24년 + 25년: 43+53시트 (= 한아원홀세일)

각 시트 = 표준계정 (예: '29_복리후생비(81100)' → standard_code 81100).
시트 내 거래처 컬럼(col 3)을 추출 → standard_account_keywords 에 (vendor, code) 패턴 저장.

distinct (vendor, code) 페어를 카운팅 후, vendor 가 여러 standard 에 등장하면
가장 빈도 높은 standard 에 매핑하고 confidence 를 빈도 비율로 보정.

Usage:
    python -m backend.scripts.import_kgaap_ledger_keywords            # dry-run
    python -m backend.scripts.import_kgaap_ledger_keywords --apply    # 실제 적용
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import defaultdict
from typing import Iterable

import xlrd

from backend.database.connection import init_pool, get_db


LEDGER_FILES = [
    ("HOK 25년", "/Users/admin/Documents/HanahOneAll/Finance/결산자료/25년귀속 계정별원장_(주)한아원코리아.xls"),
    ("HOW 24년", "/Users/admin/Documents/HanahOneAll/도팜인/재무자료/24년 계정별원장.xls"),
    ("HOW 25년", "/Users/admin/Documents/HanahOneAll/도팜인/재무자료/25년 계정별원장.xls"),
]

SHEET_RE = re.compile(r"^\d+_.+\((\d{5})\)$")  # '29_복리후생비(81100)' → 81100
NOISE_VENDORS = {
    "", "해외사용분", "기타", "기타 거래처",
}
MIN_VENDOR_LEN = 3
MAX_VENDOR_LEN = 80


def _extract_vendors_from_sheet(sh) -> Iterable[str]:
    """시트 r4+ 의 col 3 (거래처) 추출. 노이즈 필터링."""
    # 헤더 row 3, 데이터 r4+
    for r in range(4, sh.nrows):
        try:
            v = sh.cell_value(r, 3)
        except IndexError:
            continue
        if not v:
            continue
        v = str(v).strip()
        if len(v) < MIN_VENDOR_LEN or len(v) > MAX_VENDOR_LEN:
            continue
        if v in NOISE_VENDORS:
            continue
        yield v


def _scan_files() -> dict[tuple[str, str], int]:
    """{(vendor, std_code): count} 누적."""
    pair_count: dict[tuple[str, str], int] = defaultdict(int)
    for label, path in LEDGER_FILES:
        try:
            wb = xlrd.open_workbook(path, on_demand=True)
        except FileNotFoundError:
            print(f"  SKIP (not found): {label} — {path}")
            continue
        sheet_count = 0
        row_count = 0
        for name in wb.sheet_names():
            m = SHEET_RE.match(name)
            if not m:
                continue
            std_code = m.group(1)
            sh = wb.sheet_by_name(name)
            for vendor in _extract_vendors_from_sheet(sh):
                pair_count[(vendor, std_code)] += 1
                row_count += 1
            sheet_count += 1
        print(f"  {label}: {sheet_count} sheets, {row_count} (vendor, code) entries")
    return pair_count


def _resolve_unique_keyword(pair_count: dict[tuple[str, str], int]) -> list[tuple[str, str, float]]:
    """vendor 별 최빈 standard_code 선택. confidence = 비율 * 보정.

    Returns: [(vendor, std_code, confidence), ...] — vendor 당 1개 선택.
    """
    # vendor → {std_code: count}
    by_vendor: dict[str, dict[str, int]] = defaultdict(dict)
    for (v, c), n in pair_count.items():
        by_vendor[v][c] = by_vendor[v].get(c, 0) + n

    out = []
    for vendor, code_counts in by_vendor.items():
        total = sum(code_counts.values())
        top_code, top_n = max(code_counts.items(), key=lambda kv: kv[1])
        ratio = top_n / total if total else 0
        # 빈도 충족 + 비율 보정
        if total < 2:
            confidence = 0.5  # 1회만 등장 — 약한 신호
        else:
            confidence = round(min(0.95, 0.6 + ratio * 0.35), 2)
        out.append((vendor, top_code, confidence))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.6)
    args = parser.parse_args()

    print("=" * 70)
    print("K-GAAP Ledger → standard_account_keywords import")
    print("=" * 70)
    print()
    print("Scanning files...")
    pair_count = _scan_files()
    print()
    print(f"Total distinct (vendor, code) pairs: {len(pair_count)}")
    print(f"Total occurrences: {sum(pair_count.values())}")
    print()

    keywords = _resolve_unique_keyword(pair_count)
    keywords = [k for k in keywords if k[2] >= args.min_confidence]
    keywords.sort(key=lambda x: -x[2])

    print(f"Distinct vendors after dedup: {len(keywords)} (min_confidence={args.min_confidence})")
    print()

    # 미리보기
    print("Top 10 by confidence:")
    for v, c, conf in keywords[:10]:
        print(f"  {conf:.2f}  std={c}  vendor={v[:50]}")
    print()
    print("Bottom 5 (수동 검토 권장):")
    for v, c, conf in keywords[-5:]:
        print(f"  {conf:.2f}  std={c}  vendor={v[:50]}")
    print()

    if not args.apply:
        print("DRY-RUN — to apply: rerun with --apply")
        return 0

    asyncio.run(init_pool())
    cur = next(get_db()).cursor()
    cur.execute("SET search_path TO financeone, public")

    # std_code → standard_account_id (K-GAAP)
    cur.execute("SELECT id, code FROM standard_accounts WHERE gaap_type='K_GAAP'")
    std_id_by_code = {code: sid for sid, code in cur.fetchall()}

    inserted = 0
    updated = 0
    skipped_no_std = 0

    for vendor, code, conf in keywords:
        std_id = std_id_by_code.get(code)
        if std_id is None:
            skipped_no_std += 1
            continue
        # keyword UNIQUE — UPSERT
        cur.execute(
            """
            INSERT INTO standard_account_keywords (keyword, standard_account_id, confidence)
            VALUES (%s, %s, %s)
            ON CONFLICT (keyword) DO UPDATE
                SET standard_account_id = EXCLUDED.standard_account_id,
                    confidence = GREATEST(standard_account_keywords.confidence, EXCLUDED.confidence)
            RETURNING (xmax = 0) AS inserted
            """,
            [vendor[:100], std_id, conf],
        )
        if cur.fetchone()[0]:
            inserted += 1
        else:
            updated += 1

    cur.connection.commit()
    cur.close()
    print(f"DONE — inserted: {inserted}, updated: {updated}, skipped(no std code): {skipped_no_std}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

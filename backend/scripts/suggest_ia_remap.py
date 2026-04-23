"""내부계정 → K-GAAP 표준계정 매핑 제안 스크립트.

scope: 활성 internal_accounts 전체를 이름 기반으로 재분석하여
현재 standard_account_id와 다를 경우 제안/경고를 출력.

사용:
  # dry-run (출력만)
  python3 -m backend.scripts.suggest_ia_remap --entity 2

  # 여러 법인
  python3 -m backend.scripts.suggest_ia_remap --entity 2 --entity 3

  # CSV 출력
  python3 -m backend.scripts.suggest_ia_remap --entity 2 --csv /tmp/remap.csv

  # 실제 DB 반영 (HIGH confidence NULL 채우기만)
  python3 -m backend.scripts.suggest_ia_remap --entity 2 --apply-fill

  # CHANGE_RECOMMENDED도 반영 (conf>=0.9 기존 매핑 변경)
  python3 -m backend.scripts.suggest_ia_remap --entity 2 --apply-fill --apply-change

반영 시 세 테이블 동시 UPDATE (단일 트랜잭션):
  - internal_accounts.standard_account_id
  - transactions.standard_account_id (해당 internal_account_id 참조분)
  - journal_entry_lines.standard_account_id (현금계정 제외 line — 재무제표 집계 대상)

internal_accounts.code / name / parent_id / 거래의 internal_account_id 는
전혀 손대지 않음. 분개 자체(journal_entries)도 유지, line의 표준계정만 동기화.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass
from typing import Optional

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
load_dotenv()


# ── 이름 기반 매칭 룰 ───────────────────────────────
# (pattern, std_code, confidence, note)
# 순서 중요: 먼저 match되는 것이 적용됨. 더 구체적인 규칙을 위로.
RULES: list[tuple[re.Pattern, str, float, str]] = [
    # ── 매출/수익 ────────────────────────────────
    (re.compile(r"스마트스토어\s*리뷰"), "83300", 0.75, "스마트스토어 리뷰 외주 → 광고선전비"),
    (re.compile(r"스마트스토어(?!\s*리뷰)"), "40100", 0.95, "스마트스토어 → 상품매출"),
    (re.compile(r"ODD\s*약국"), "40100", 0.90, "ODD 약국 → 상품매출"),
    (re.compile(r"상품\s*매출"), "40100", 0.95, "상품매출"),
    (re.compile(r"서비스\s*매출"), "41200", 0.95, "서비스매출"),
    (re.compile(r"시스템\s*사용료"), "41200", 0.90, "서비스매출(시스템)"),
    (re.compile(r"플랫폼\s*사용료"), "41200", 0.90, "서비스매출(플랫폼)"),
    (re.compile(r"인프라\s*구축"), "41200", 0.75, "서비스매출(인프라)"),
    (re.compile(r"(국고보조금|정부지원|지원사업)"), "92900", 0.95, "국고보조금수익"),
    (re.compile(r"이자\s*수익"), "90100", 0.95, "이자수익"),
    (re.compile(r"외환차익"), "90700", 0.95, "외환차익"),
    (re.compile(r"잡이익"), "93000", 0.90, "잡이익"),
    # ── 자산(회수/상환/보증금) ────────────────────
    (re.compile(r"매출채권(\s*회수)?"), "10800", 0.90, "외상매출금"),
    (re.compile(r"대여금\s*상환"), "10900", 0.80, "단기대여금 회수"),
    (re.compile(r"보증금\s*상환"), "96200", 0.85, "임차보증금 회수"),
    (re.compile(r"임차보증금|창고보증금"), "96200", 0.95, "임차보증금"),
    (re.compile(r"선급금(?!액)"), "13100", 0.90, "선급금"),
    (re.compile(r"선납세금"), "13600", 0.90, "선납세금"),
    (re.compile(r"부가세대급금"), "13500", 0.95, "부가세대급금"),
    # ── 부채 ──────────────────────────────────
    (re.compile(r"장기차입금"), "30400", 0.90, "장기차입금"),
    (re.compile(r"단기차입금|차입금(?!\s*상환)"), "29000", 0.85, "단기차입금"),
    (re.compile(r"차입금\s*상환"), "29000", 0.80, "차입금 상환"),
    (re.compile(r"매입채무|외상매입금"), "25100", 0.90, "외상매입금"),
    (re.compile(r"미지급급여"), "27500", 0.95, "미지급급여"),
    (re.compile(r"미지급비용"), "26200", 0.90, "미지급비용"),
    (re.compile(r"미지급금(?!여)"), "25200", 0.90, "미지급금"),
    (re.compile(r"부가세예수금"), "25500", 0.95, "부가세예수금"),
    (re.compile(r"예수금"), "25400", 0.90, "예수금"),
    # ── 자본/투자 ─────────────────────────────
    (re.compile(r"자회사\s*설립자본"), "17900", 0.50, "장기대여금(투자주식 대체)"),
    (re.compile(r"^자본금$"), "33100", 0.95, "자본금"),
    (re.compile(r"주식발행초과금"), "34100", 0.95, "주식발행초과금"),
    # ── 급여/복리 ─────────────────────────────
    (re.compile(r"^알바비$|일용잡급"), "80200", 0.80, "직원급여(알바)"),
    (re.compile(r"^상여금$"), "80200", 0.75, "직원급여(상여)"),
    (re.compile(r"직원급여|^급여$|월급"), "80200", 0.95, "직원급여"),
    (re.compile(r"퇴직급여|퇴직금"), "80500", 0.95, "퇴직급여"),
    (re.compile(r"문화비|동호회"), "81100", 0.80, "복리후생비(문화)"),
    (re.compile(r"복리후생|식비|워크샵|야식|간식|경조"), "81100", 0.90, "복리후생비"),
    # ── 판관비 ────────────────────────────────
    (re.compile(r"여비교통비|^여비$|출장"), "81200", 0.90, "여비교통비"),
    (re.compile(r"교통비"), "81200", 0.85, "여비교통비"),
    (re.compile(r"접대|기업업무추진비"), "81300", 0.95, "접대비"),
    (re.compile(r"국세|지방세|주민세|^세금$|관세|과태료|자동차세|가산세"), "81700", 0.90, "세금과공과금"),
    (re.compile(r"임차료"), "81900", 0.95, "지급임차료"),
    (re.compile(r"보험료"), "82100", 0.95, "보험료"),
    (re.compile(r"운반비|배송비|^통관$|택배"), "82400", 0.90, "운반비"),
    (re.compile(r"통신비|인터넷(?!회선)|휴대폰|전화요금"), "82800", 0.90, "통신비"),
    (re.compile(r"사무용품|사무비품"), "82900", 0.90, "사무용품비"),
    (re.compile(r"^소모품"), "83000", 0.90, "소모품비"),
    (re.compile(r"노트북\s*구매"), "83000", 0.70, "소모품비(노트북)"),
    (re.compile(r"광고선전비|광고\s*구독"), "83300", 0.95, "광고선전비"),
    (re.compile(r"광고비|^마케팅"), "83300", 0.85, "광고선전비"),
    (re.compile(r"바이럴"), "83300", 0.80, "광고선전비(바이럴)"),
    (re.compile(r"판매수수료|플랫폼\s*수수료"), "83900", 0.85, "판매수수료"),
    (re.compile(r"결제수수료"), "83100", 0.85, "지급수수료(결제)"),
    (re.compile(r"SaaS\s*구독"), "83100", 0.80, "지급수수료(SaaS)"),
    (re.compile(r"정수기\s*렌탈"), "82900", 0.65, "사무용품비(렌탈)"),
    (re.compile(r"회계법인|^법무|법률|세무(사)?"), "83100", 0.90, "지급수수료(전문가)"),
    (re.compile(r"청소"), "83100", 0.80, "지급수수료(용역)"),
    (re.compile(r"에스원|보안"), "83100", 0.75, "지급수수료(보안)"),
    (re.compile(r"보관료|창고료|3PL"), "83100", 0.80, "지급수수료(보관)"),
    (re.compile(r"수선비|수리비|^공사$|인테리어|사무실\s*공사"), "85200", 0.80, "수선비"),
    # 외주 — 광범위, 맥락에 따라 광고/수수료
    (re.compile(r"촬영\s*외주|촬영비"), "83100", 0.80, "지급수수료(촬영)"),
    (re.compile(r"디자인\s*외주|디자인비"), "83100", 0.80, "지급수수료(디자인)"),
    (re.compile(r"개발\s*외주|개발비"), "83100", 0.80, "지급수수료(개발)"),
    (re.compile(r"패키징(\s*외주)?"), "83100", 0.75, "지급수수료(패키징)"),
    (re.compile(r"제작\s*외주|제작비"), "83100", 0.75, "지급수수료(제작)"),
    (re.compile(r"외주(?!\s*수익)"), "83100", 0.70, "지급수수료(외주 fallback)"),
    (re.compile(r"지급수수료|수수료(?!수익|환급)"), "83100", 0.90, "지급수수료"),
    # ── 영업외비용 ────────────────────────────
    (re.compile(r"이자비용"), "93300", 0.95, "이자비용"),
    (re.compile(r"외환차손"), "93600", 0.95, "외환차손"),
    # ── 법인세 ────────────────────────────────
    (re.compile(r"법인세"), "99800", 0.95, "법인세등"),
    # ── 상품 매입/원가 ────────────────────────
    (re.compile(r"상품\s*사입|상품매입|제품매입|사입\s*원가"), "45100", 0.85, "상품매출원가"),
    (re.compile(r"건기식\s*사입|건기식\s*매입"), "45100", 0.80, "상품매출원가(건기식)"),
    # ── 카드 대금(EXP-101) ────────────────────
    (re.compile(r"^선결제$"), "13100", 0.65, "선급금(카드 선결제)"),
    # ── fallback ──────────────────────────────
    (re.compile(r"^잡손실$"), "96000", 0.90, "잡손실"),
    (re.compile(r"^기타$"), None, 0.0, "'기타' — 맥락 필요 (needs review)"),
]


@dataclass
class Suggestion:
    ia_id: int
    ia_code: str
    ia_name: str
    current_code: Optional[str]
    current_name: Optional[str]
    suggested_code: Optional[str]
    suggested_name: Optional[str]
    confidence: float
    reason: str
    classification: str  # FILL / FILL_LOW / CHANGE_STRONG / CHANGE_WEAK / OK / KEEP / LOW_CONF


def suggest(name: Optional[str], ia_code: Optional[str]) -> tuple[Optional[str], float, str]:
    if not name:
        return None, 0.0, "no name"
    for pat, code, conf, reason in RULES:
        if pat.search(name):
            return code, conf, reason
    # INC- prefix fallback — 수익 기본 추정
    if ia_code and ia_code.upper().startswith("INC"):
        return "40100", 0.40, "INC- prefix (default 상품매출 추정)"
    # EXP- prefix fallback — 판관비 기본 추정
    if ia_code and ia_code.upper().startswith("EXP"):
        return "83100", 0.30, "EXP- prefix (default 지급수수료 추정)"
    return None, 0.0, "no rule matched"


def classify(current: Optional[str], suggested: Optional[str], conf: float) -> str:
    if current is None and suggested is None:
        return "LOW_CONF"
    if current is None:
        return "FILL" if conf >= 0.80 else "FILL_LOW"
    if suggested is None:
        return "KEEP"
    if current == suggested:
        return "OK"
    if conf >= 0.90:
        return "CHANGE_STRONG"
    if conf >= 0.75:
        return "CHANGE_WEAK"
    return "KEEP_SUSPICIOUS"


def load_accounts(conn, entity_ids: list[int]) -> list[Suggestion]:
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # standard_accounts 코드 → name 매핑
    cur.execute("SELECT code, name FROM standard_accounts WHERE is_active")
    std_map = {row[0]: row[1] for row in cur.fetchall()}

    cur.execute(
        """
        SELECT ia.id, ia.code, ia.name, ia.entity_id,
               ia.standard_account_id, sa.code, sa.name,
               (SELECT COUNT(*) FROM transactions t WHERE t.internal_account_id = ia.id) AS tx_count
        FROM internal_accounts ia
        LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
        WHERE ia.is_active = TRUE AND ia.entity_id = ANY(%s)
        ORDER BY ia.entity_id, ia.code
        """,
        [entity_ids],
    )
    rows = cur.fetchall()
    cur.close()

    out: list[Suggestion] = []
    for r in rows:
        ia_id, ia_code, ia_name, entity_id, cur_sa_id, cur_code, cur_name, tx_count = r
        sug_code, conf, reason = suggest(ia_name, ia_code)
        cls = classify(cur_code, sug_code, conf)
        out.append(Suggestion(
            ia_id=ia_id, ia_code=ia_code, ia_name=ia_name,
            current_code=cur_code, current_name=cur_name,
            suggested_code=sug_code,
            suggested_name=std_map.get(sug_code) if sug_code else None,
            confidence=conf, reason=reason, classification=cls,
        ))
    return out


def print_report(suggestions: list[Suggestion]) -> None:
    by_cls: dict[str, list[Suggestion]] = {}
    for s in suggestions:
        by_cls.setdefault(s.classification, []).append(s)

    order = ["FILL", "CHANGE_STRONG", "CHANGE_WEAK", "KEEP_SUSPICIOUS", "FILL_LOW", "LOW_CONF", "OK", "KEEP"]

    for cls in order:
        items = by_cls.get(cls, [])
        if not items:
            continue
        desc = {
            "FILL": "🟢 NULL → 채우기 (HIGH confidence, apply-fill 대상)",
            "FILL_LOW": "🟡 NULL → 채우기 (LOW confidence, 수동 검토 권장)",
            "CHANGE_STRONG": "🟠 변경 권장 (기존과 다름, conf≥0.9, apply-change 대상)",
            "CHANGE_WEAK": "🟡 변경 제안 (기존과 다름, conf 0.75~0.9, 수동 검토)",
            "KEEP_SUSPICIOUS": "🔴 의심 (conf<0.75, 기존 유지 but 검토)",
            "LOW_CONF": "⚪ 매칭 실패 + 현재 NULL (수동 매핑 필요)",
            "OK": "✅ 일치 (조치 불필요)",
            "KEEP": "⚫ 규칙 없음, 기존 유지",
        }[cls]
        print(f"\n{'='*100}\n{desc} — {len(items)}건\n{'='*100}")
        print(f"{'id':>4}  {'ia_code':<15s}  {'ia_name':<22s}  {'current':<20s}  {'suggested':<22s}  {'conf':>5s}  reason")
        for s in sorted(items, key=lambda x: (x.ia_code or "")):
            cur_disp = f"{s.current_code or '(NULL)'} {s.current_name or ''}"[:20]
            sug_disp = f"{s.suggested_code or '-'} {s.suggested_name or ''}"[:22]
            print(f"{s.ia_id:>4}  {s.ia_code[:15]:<15s}  {(s.ia_name or '')[:22]:<22s}  {cur_disp:<20s}  {sug_disp:<22s}  {s.confidence:>5.2f}  {s.reason}")

    # 요약
    print(f"\n{'='*100}\n분류 요약")
    print(f"{'='*100}")
    for cls in order:
        cnt = len(by_cls.get(cls, []))
        if cnt:
            print(f"  {cls:<18s} {cnt:>4}건")
    print(f"  {'TOTAL':<18s} {len(suggestions):>4}건")


def write_csv(suggestions: list[Suggestion], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "ia_id", "ia_code", "ia_name", "current_code", "current_name",
            "suggested_code", "suggested_name", "confidence", "classification", "reason",
        ])
        for s in sorted(suggestions, key=lambda x: (x.classification, x.ia_code or "")):
            w.writerow([
                s.ia_id, s.ia_code, s.ia_name,
                s.current_code or "", s.current_name or "",
                s.suggested_code or "", s.suggested_name or "",
                f"{s.confidence:.2f}", s.classification, s.reason,
            ])
    print(f"\n✓ CSV saved: {path}")


def apply_updates(conn, suggestions: list[Suggestion], target_cls: set[str]) -> dict:
    """target_cls 에 해당하는 제안을 DB에 반영.

    UPDATE internal_accounts.standard_account_id
    + UPDATE transactions.standard_account_id WHERE internal_account_id=X
    + UPDATE journal_entry_lines.standard_account_id (현금 제외 line) — 재무제표 반영
    단일 트랜잭션.
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    # std code → id 매핑
    cur.execute("SELECT id, code FROM standard_accounts")
    code_to_id = {row[1]: row[0] for row in cur.fetchall()}

    # 현금계정 id (동기화 제외 대상)
    cur.execute("SELECT id FROM standard_accounts WHERE code='10100'")
    cash_row = cur.fetchone()
    cash_id = cash_row[0] if cash_row else None

    applied_ia = 0
    applied_tx = 0
    applied_jel = 0
    skipped = 0
    for s in suggestions:
        if s.classification not in target_cls:
            continue
        if not s.suggested_code or s.suggested_code not in code_to_id:
            skipped += 1
            continue
        sa_id = code_to_id[s.suggested_code]

        cur.execute(
            "UPDATE internal_accounts SET standard_account_id=%s WHERE id=%s",
            [sa_id, s.ia_id],
        )
        applied_ia += cur.rowcount

        cur.execute(
            "UPDATE transactions SET standard_account_id=%s WHERE internal_account_id=%s",
            [sa_id, s.ia_id],
        )
        applied_tx += cur.rowcount

        # 분개 line 동기화: 이 internal_account를 참조하는 transaction의 JE 중
        # 현금계정이 아닌 line의 standard_account_id를 교체
        if cash_id is not None:
            cur.execute(
                """
                UPDATE journal_entry_lines jel
                SET standard_account_id = %s
                FROM journal_entries je, transactions t
                WHERE jel.journal_entry_id = je.id
                  AND je.transaction_id = t.id
                  AND t.internal_account_id = %s
                  AND jel.standard_account_id <> %s
                """,
                [sa_id, s.ia_id, cash_id],
            )
            applied_jel += cur.rowcount
        else:
            cur.execute(
                """
                UPDATE journal_entry_lines jel
                SET standard_account_id = %s
                FROM journal_entries je, transactions t
                WHERE jel.journal_entry_id = je.id
                  AND je.transaction_id = t.id
                  AND t.internal_account_id = %s
                """,
                [sa_id, s.ia_id],
            )
            applied_jel += cur.rowcount

    conn.commit()
    cur.close()
    return {
        "ia_updated": applied_ia,
        "tx_updated": applied_tx,
        "jel_updated": applied_jel,
        "skipped": skipped,
    }


def sync_je_lines(conn, entity_ids: list[int]) -> int:
    """분개 line의 standard_account_id를 transactions와 동기화.

    remap 이전에 생성된 분개들은 transactions.standard_account_id 갱신 후에도
    journal_entry_lines.standard_account_id는 옛 값 유지 → 재무제표에 반영 안 됨.
    이를 일괄 동기화. 현금계정(10100) line은 유지.
    """
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    cur.execute("SELECT id FROM standard_accounts WHERE code='10100'")
    cash_row = cur.fetchone()
    cash_id = cash_row[0] if cash_row else -1
    cur.execute(
        """
        UPDATE journal_entry_lines jel
        SET standard_account_id = t.standard_account_id
        FROM journal_entries je, transactions t
        WHERE jel.journal_entry_id = je.id
          AND je.transaction_id = t.id
          AND je.entity_id = ANY(%s)
          AND jel.standard_account_id <> t.standard_account_id
          AND jel.standard_account_id <> %s
          AND t.standard_account_id IS NOT NULL
        """,
        [entity_ids, cash_id],
    )
    synced = cur.rowcount
    conn.commit()
    cur.close()
    return synced


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", type=int, action="append", required=True,
                    help="대상 entity_id (여러 번 지정 가능)")
    ap.add_argument("--csv", type=str, help="CSV 출력 경로")
    ap.add_argument("--apply-fill", action="store_true",
                    help="FILL 분류(현재 NULL + conf>=0.8)만 DB 반영")
    ap.add_argument("--apply-change", action="store_true",
                    help="CHANGE_STRONG 분류(conf>=0.9, 기존 매핑 변경)도 반영")
    ap.add_argument("--sync-je-lines", action="store_true",
                    help="분개 line의 standard_account_id를 transactions와 동기화 "
                         "(이전에 remap 적용됐지만 JE 반영이 누락된 경우). "
                         "현금계정(10100) line은 제외, 해당 entity 범위 내만.")
    args = ap.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        suggestions = load_accounts(conn, args.entity)
        print_report(suggestions)
        if args.csv:
            write_csv(suggestions, args.csv)

        target: set[str] = set()
        if args.apply_fill:
            target.add("FILL")
        if args.apply_change:
            target.add("CHANGE_STRONG")

        if target:
            print(f"\n⚠️  DB 반영 대상 classification: {sorted(target)}")
            result = apply_updates(conn, suggestions, target)
            print(f"   internal_accounts UPDATE:  {result['ia_updated']}건")
            print(f"   transactions UPDATE:       {result['tx_updated']}건")
            print(f"   journal_entry_lines UPDATE: {result['jel_updated']}건")
            print(f"   skipped (코드 없음):        {result['skipped']}건")
        else:
            print("\n[dry-run] DB 변경 없음. --apply-fill 또는 --apply-change 플래그로 반영.")

        if args.sync_je_lines:
            print(f"\n⚠️  JE lines 동기화 실행 (entity={args.entity})")
            synced = sync_je_lines(conn, args.entity)
            print(f"   journal_entry_lines synced: {synced}건")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

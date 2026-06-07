# 운영 감시·브리핑 봇 — 읽기전용 DB 조회 → 로컬 Gemma 요약 → 텔레그램 (쓰기·자격증명 0)
"""
사장님 운영 비서 (B안: 가벼운 봇 + 로컬 Gemma).

데이터는 머신 밖으로 안 나갑니다 — 요약은 로컬 Ollama(gemma4:12b)가 하고,
DB는 읽기전용 조회만, 회계 정확성 경로(분개·매핑·재무제표)는 절대 안 건드립니다.

사용법:
    source .venv/bin/activate
    python scripts/ops_briefing.py --mode health            # 화면 출력(dry-run)
    python scripts/ops_briefing.py --mode health --send     # 텔레그램 전송
    python scripts/ops_briefing.py --mode briefing [--send]

env: DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
     OLLAMA_URL(기본 http://localhost:11434), OLLAMA_MODEL(기본 gemma4:12b)
"""
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
import httpx
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:12b")
STALE_HOURS = 26  # daily cron(24h) + 여유


def _db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    return conn, cur


def gather_health(cur) -> dict:
    """sync 헬스 — org별 last_sync 신선도 + 오늘 들어온 거래수."""
    now = datetime.now(timezone.utc)
    cur.execute(
        "SELECT key, entity_id, value FROM settings "
        "WHERE key LIKE 'codef_last_sync_production_%' ORDER BY entity_id, key"
    )
    orgs = []
    stale = []
    for key, eid, val in cur.fetchall():
        org = key.replace("codef_last_sync_production_", "")
        try:
            ts = datetime.fromisoformat(val).astimezone(timezone.utc)
            hrs = (now - ts).total_seconds() / 3600
        except Exception:
            ts, hrs = None, 9999
        orgs.append({"org": org, "entity": eid, "last": val[:16] if val else None, "hours": round(hrs, 1)})
        if hrs > STALE_HOURS:
            stale.append(f"{org}(e{eid}, {round(hrs)}h 전)")
    cur.execute(
        "SELECT source_type, COUNT(*) FROM transactions "
        "WHERE created_at::date = CURRENT_DATE GROUP BY source_type ORDER BY 2 DESC"
    )
    today = {r[0]: r[1] for r in cur.fetchall()}
    return {"orgs": orgs, "stale": stale, "today_counts": today}


def _fmt(amount, currency: str) -> str:
    """통화별 금액 표기 — USD는 $, KRW는 원. 절대 섞어 합산하지 않음."""
    if currency == "USD":
        a = float(amount)
        return f"-${abs(a):,.2f}" if a < 0 else f"${a:,.2f}"
    return f"{int(amount):,}원"


def gather_briefing(cur) -> dict:
    """주간 재무 브리핑 — 법인별 최신 현금잔액(계좌 합산) + 이번주 순현금. HOI 포함, 통화별 구분."""
    # 계좌별 스냅샷이 여러 개라 최신 날짜분을 합산 (LIMIT 1 은 한 계좌만 잡힘)
    cur.execute(
        """
        SELECT e.id, e.name, e.currency,
               COALESCE((
                 SELECT SUM(bs.balance) FROM balance_snapshots bs
                 WHERE bs.entity_id = e.id
                   AND bs.date = (SELECT MAX(date) FROM balance_snapshots WHERE entity_id = e.id)
               ), 0) AS cash
        FROM entities e WHERE e.id IN (1, 2, 3, 13) ORDER BY e.id
        """
    )
    cash = [{"name": r[1], "currency": r[2], "cash": r[3] or 0} for r in cur.fetchall()]
    cur.execute(
        """
        SELECT e.name, e.currency,
               SUM(CASE WHEN t.type='in' THEN t.amount ELSE 0 END) AS inflow,
               SUM(CASE WHEN t.type='out' THEN t.amount ELSE 0 END) AS outflow
        FROM transactions t JOIN entities e ON e.id = t.entity_id
        WHERE t.date >= CURRENT_DATE - INTERVAL '7 days' AND t.entity_id IN (1,2,3,13)
        GROUP BY e.id, e.name, e.currency ORDER BY e.id
        """
    )
    week = [{"name": r[0], "currency": r[1], "in": r[2] or 0, "out": r[3] or 0} for r in cur.fetchall()]
    return {"cash": cash, "week": week}


def gemma_summarize(role: str, facts: str) -> str:
    """로컬 Gemma(think:false)로 한국어 요약. 외부 전송 없음."""
    prompt = (
        f"너는 한아원 그룹 CEO의 운영 비서다. 아래 사실만 근거로 {role}.\n"
        f"규칙: 한국어, 군더더기 없이 핵심만, 숫자는 그대로, 과장·추측 금지, "
        f"문장은 마침표로 끝낼 것.\n\n[사실]\n{facts}"
    )
    try:
        r = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "think": False,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": 400, "temperature": 0.3},
            },
            timeout=120.0,
        )
        return (r.json().get("message", {}).get("content") or "").strip() or "(Gemma 응답 없음)"
    except Exception as e:
        return f"(Gemma 요약 실패: {type(e).__name__} — 원본 사실 첨부)\n\n{facts}"


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("⚠️ TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 전송 생략")
        return False
    r = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat, "text": text},
        timeout=20.0,
    )
    return r.status_code == 200


def build_health(cur) -> str:
    h = gather_health(cur)
    lines = ["[sync 상태]"]
    for o in h["orgs"]:
        mark = "⚠️" if o["hours"] > STALE_HOURS else "✓"
        lines.append(f"  {mark} {o['org']}(e{o['entity']}) 마지막 {o['last']} ({o['hours']}h 전)")
    lines.append("[오늘 들어온 거래]")
    for st, n in h["today_counts"].items():
        lines.append(f"  {st}: {n}건")
    facts = "\n".join(lines)
    role = ("오늘 자동 동기화가 정상인지 1~2문장으로 보고하라. "
            "stale(26h 초과)이나 거래 0건인 기관이 있으면 콕 집어 경고하라")
    summary = gemma_summarize(role, facts)
    return f"📡 동기화 헬스체크\n\n{summary}\n\n— — —\n{facts}"


def build_briefing(cur) -> str:
    b = gather_briefing(cur)
    lines = ["[법인별 최신 현금잔액]"]
    for c in b["cash"]:
        lines.append(f"  {c['name']}: {_fmt(c['cash'], c['currency'])}")
    lines.append("[최근 7일 순현금]")
    for w in b["week"]:
        net = w["in"] - w["out"]
        lines.append(
            f"  {w['name']}: 수입 {_fmt(w['in'], w['currency'])} - "
            f"지출 {_fmt(w['out'], w['currency'])} = {_fmt(net, w['currency'])}"
        )
    facts = "\n".join(lines)
    role = ("이번 주 현금 상황을 사장님께 3~4문장으로 브리핑하라. 법인별 특이점 위주로. "
            "HOI는 USD($), 한국 법인은 원(KRW)이니 통화를 절대 섞어 합산하지 마라")
    summary = gemma_summarize(role, facts)
    return f"💰 주간 재무 브리핑\n\n{summary}\n\n— — —\n{facts}"


def _build(mode: str) -> str:
    """모드별 메시지 생성 (자체 DB 연결)."""
    conn, cur = _db()
    try:
        return build_health(cur) if mode == "health" else build_briefing(cur)
    finally:
        conn.close()


HELP_TEXT = (
    "🤖 한아원 운영비서\n"
    "  /health 또는 '상태' → 동기화 헬스체크\n"
    "  /briefing 또는 '브리핑' → 재무 브리핑\n"
    "  자유롭게 물어보셔도 됩니다 (예: 이번주 현금 어때?)"
)


def _route(text: str) -> str:
    """요청 → 'health'|'briefing'|'help'. 키워드 우선, 애매하면 로컬 Gemma 분류."""
    t = (text or "").strip().lower()
    if any(k in t for k in ["/health", "상태", "헬스", "동기화", "sync"]):
        return "health"
    if any(k in t for k in ["/briefing", "브리핑", "현금", "재무", "잔액", "briefing"]):
        return "briefing"
    if any(k in t for k in ["/help", "/start", "도움", "help"]):
        return "help"
    ans = gemma_summarize(
        "사용자 요청이 'health'(동기화/상태 점검)인지 'briefing'(현금/재무/잔액)인지 "
        "'other'인지 딱 한 단어로만 답하라",
        f"요청: {text}",
    ).lower()
    return "health" if "health" in ans else "briefing" if "brief" in ans else "help"


def _tg_get_updates(offset, timeout=30):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        return r.json().get("result", [])
    except Exception:
        return []


def run_listener():
    """on-demand 요청 수신 + 스케줄 push 를 한 프로세스에서 (getUpdates 단일 소비자).

    스케줄: 매일 09:15~ health, 월요일 09:30~ briefing (Mac 로컬시간 기준).
    """
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    print(f"[listener] 시작 — chat={chat_id} model={OLLAMA_MODEL}", flush=True)
    # 시작 시 백로그 비우기 (오래된 요청에 답하지 않도록)
    drain = _tg_get_updates(None, timeout=0)
    offset = (drain[-1]["update_id"] + 1) if drain else None
    sent = {"health": None, "briefing": None}
    while True:
        try:
            now = datetime.now()
            today = now.date()
            # 스케줄 push (창 안에서 1회만)
            if now.hour == 9 and 15 <= now.minute < 45 and sent["health"] != today:
                send_telegram(_build("health")); sent["health"] = today
                print(f"[listener] {now:%H:%M} health push", flush=True)
            if now.weekday() == 0 and now.hour == 9 and 30 <= now.minute < 59 and sent["briefing"] != today:
                send_telegram(_build("briefing")); sent["briefing"] = today
                print(f"[listener] {now:%H:%M} briefing push", flush=True)
            # on-demand 요청 처리
            for u in _tg_get_updates(offset):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str((msg.get("chat") or {}).get("id")) != chat_id:
                    continue  # 인가된 챗만 응답
                route = _route(msg.get("text", ""))
                print(f"[listener] req '{msg.get('text','')[:20]}' → {route}", flush=True)
                send_telegram(HELP_TEXT if route == "help" else _build(route))
        except Exception as e:
            print(f"[listener] error: {type(e).__name__}: {e}", flush=True)
            time.sleep(5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["health", "briefing", "listen"], default="health")
    ap.add_argument("--send", action="store_true", help="텔레그램 전송 (없으면 화면 출력만)")
    args = ap.parse_args()

    if args.mode == "listen":
        run_listener()
        return

    conn, cur = _db()
    try:
        text = build_health(cur) if args.mode == "health" else build_briefing(cur)
    finally:
        conn.close()

    print(text)
    if args.send:
        ok = send_telegram(text)
        print("\n[텔레그램]", "전송됨 ✓" if ok else "전송 실패")
    else:
        print("\n(dry-run — 전송하려면 --send)")


if __name__ == "__main__":
    main()

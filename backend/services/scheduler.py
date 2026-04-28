"""백그라운드 sync 스케줄러.

AsyncIOScheduler로 FastAPI 이벤트 루프에 묶어 in-process 실행.

Codef 카드·은행 sync를 30분마다 모든 등록된 (entity_id, organization) 조합에
대해 자동 실행. 결과는 기존 `codef_last_sync_*` 설정과 `codef_api_log` 테이블에
기록된다.

주의: backend 재시작하면 스케줄러도 재시작 — 현재 APScheduler 메모리 job store
사용 (배포 환경이 단일 프로세스인 한 이중 실행 위험 없음).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from psycopg2.extensions import connection as PgConnection

from backend.database import connection as db_conn_mod
from backend.utils.timezone import today_kst, now_kst

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None

# 동시성 제어 — 같은 (entity, org) 쌍이 겹쳐 실행되지 않도록
_locks: dict[tuple[int, str], asyncio.Lock] = {}

# 최근 job 실행 요약 (UI 노출용)
_last_run: dict = {
    "started_at": None,
    "finished_at": None,
    "ok_count": 0,
    "error_count": 0,
    "results": [],   # [{entity_id, org, ok, detail}]
}


@contextmanager
def _db():
    """풀에서 healthy conn 대여 → rollback 후 반환."""
    if db_conn_mod._pool is None:
        raise RuntimeError("DB pool not initialized — scheduler cannot run")
    conn = db_conn_mod._acquire_healthy_conn()
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception as e:
            logger.warning("scheduler rollback failed: %s", e)
        try:
            db_conn_mod._pool.putconn(conn)
        except Exception:
            pass


def _gather_targets(conn: PgConnection) -> list[tuple[int, str]]:
    """자동 sync 대상 (entity_id, org).

    안전장치: `codef_last_sync_<org>`가 존재하는 org만 포함 — 초기 sync는
    사용자가 수동으로 먼저 돌려야 자동 인수인계됨. 신규 connected_id 등록만으로
    대량 INSERT가 터지는 것을 방지.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT cid.entity_id, cid.key
            FROM financeone.settings cid
            JOIN financeone.settings ls
              ON ls.entity_id = cid.entity_id
             AND ls.key = 'codef_last_sync_' || regexp_replace(cid.key, '^codef_connected_id_', '')
             AND COALESCE(NULLIF(ls.value, ''), NULL) IS NOT NULL
            WHERE cid.key LIKE 'codef_connected_id_%'
              AND cid.entity_id IS NOT NULL
              AND COALESCE(NULLIF(cid.value, ''), NULL) IS NOT NULL
            ORDER BY cid.entity_id, cid.key
            """
        )
        rows = cur.fetchall()
    finally:
        cur.close()
    targets: list[tuple[int, str]] = []
    for entity_id, key in rows:
        org = key.removeprefix("codef_connected_id_")
        if org:
            targets.append((entity_id, org))
    return targets


def _incremental_date_range(conn: PgConnection, entity_id: int, org: str) -> tuple[str, str]:
    """마지막 sync 시각 기반 (start_date, end_date) — YYYYMMDD.

    last_sync 없으면 오늘 기준 과거 3일. 있으면 그 날짜 -1일(여유분)부터 오늘.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT value
            FROM financeone.settings
            WHERE entity_id = %s AND key = %s
            """,
            [entity_id, f"codef_last_sync_{org}"],
        )
        row = cur.fetchone()
    finally:
        cur.close()

    today = today_kst()
    end_date = today.strftime("%Y%m%d")

    if row and row[0]:
        try:
            last = datetime.fromisoformat(row[0]).date()
            start = last - timedelta(days=1)
        except (ValueError, TypeError):
            start = today - timedelta(days=3)
    else:
        start = today - timedelta(days=3)
    return start.strftime("%Y%m%d"), end_date


async def _sync_one(entity_id: int, org: str) -> dict:
    """단일 (entity_id, org) sync. CodefError는 codef_api_log로 기록 + 요약 반환."""
    key = (entity_id, org)
    lock = _locks.setdefault(key, asyncio.Lock())
    if lock.locked():
        return {"entity_id": entity_id, "org": org, "ok": False,
                "detail": "skipped (previous run still in progress)"}

    async with lock:
        # 동기 DB/HTTP 작업은 thread pool 로 offload
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_one_sync, entity_id, org)


def _sync_one_sync(entity_id: int, org: str) -> dict:
    from backend.services.integrations.codef import (
        CodefClient, CodefError, BANK_ORGS, CARD_ORGS, PUBLIC_ORGS,
        get_connected_id, set_last_sync,
    )
    from backend.routers.integrations import _log_codef_error  # helper reuse

    client_id = os.environ.get("CODEF_CLIENT_ID", "")
    client_secret = os.environ.get("CODEF_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return {"entity_id": entity_id, "org": org, "ok": False,
                "detail": "CODEF creds not configured"}

    try:
        with _db() as conn:
            connected_id = get_connected_id(conn, entity_id, org)
            if not connected_id:
                return {"entity_id": entity_id, "org": org, "ok": False,
                        "detail": "connected_id missing"}
            start, end = _incremental_date_range(conn, entity_id, org)

            client = CodefClient(client_id, client_secret)
            try:
                if org in BANK_ORGS:
                    result = client.sync_bank_transactions(
                        conn, entity_id, connected_id, start, end,
                    )
                elif org in CARD_ORGS:
                    result = client.sync_card_approvals(
                        conn, entity_id, connected_id, start, end, org,
                    )
                elif org in PUBLIC_ORGS and org == "hometax":
                    # 홈택스 전자세금계산서 통합조회. our_biz_no 는 entities.business_number 자동 조회.
                    cur = conn.cursor()
                    cur.execute("SELECT business_number FROM entities WHERE id = %s", [entity_id])
                    biz_row = cur.fetchone()
                    cur.close()
                    our_biz_no = biz_row[0] if biz_row and biz_row[0] else None
                    result = client.sync_tax_invoices(
                        conn, entity_id, connected_id, start, end,
                        query_type="3", our_biz_no=our_biz_no,
                    )
                else:
                    return {"entity_id": entity_id, "org": org, "ok": False,
                            "detail": f"unknown org: {org}"}

                set_last_sync(conn, entity_id, org)
                conn.commit()

                # P0-3: codef sync 직후 forecast actual_amount 동기화 (current + prev month).
                # GET /forecast 가 더 이상 자동 sync 하지 않으므로 import 직후에 갱신 필요.
                try:
                    from backend.services.cashflow_service import sync_forecast_actuals as _sync_fc
                    today = today_kst()
                    py = today.year if today.month > 1 else today.year - 1
                    pm = today.month - 1 if today.month > 1 else 12
                    _sync_fc(conn, entity_id, today.year, today.month)
                    _sync_fc(conn, entity_id, py, pm)
                except Exception as sync_err:
                    logger.warning(
                        "forecast actuals sync after codef failed: entity=%s org=%s err=%s",
                        entity_id, org, sync_err,
                    )

                # Notify ExpenseOne about new card transactions
                if org in CARD_ORGS and (result.get("synced") or 0) > 0:
                    try:
                        from backend.routers.integrations import _notify_expenseone_card_sync
                        _notify_expenseone_card_sync()
                    except Exception as notify_err:
                        logger.warning("ExpenseOne notify failed: %s", notify_err)

                return {
                    "entity_id": entity_id, "org": org, "ok": True,
                    "range": f"{start}~{end}",
                    "detail": {
                        "synced": result.get("synced") or result.get("inserted"),
                        "duplicates": result.get("duplicates"),
                        "cancels": result.get("cancels"),
                        "total_fetched": result.get("total_fetched") or result.get("fetched"),
                        "unknown_direction": result.get("unknown_direction"),
                    },
                }
            except CodefError as e:
                conn.rollback()
                log_id = _log_codef_error(conn, entity_id, org, e)
                return {
                    "entity_id": entity_id, "org": org, "ok": False,
                    "detail": {
                        "message": str(e),
                        "code": getattr(e, "code", None),
                        "transaction_id": getattr(e, "transaction_id", None),
                        "log_id": log_id,
                    },
                }
            finally:
                client.close()
    except Exception as e:
        logger.exception("scheduler job crashed for entity=%s org=%s", entity_id, org)
        return {"entity_id": entity_id, "org": org, "ok": False,
                "detail": f"exception: {type(e).__name__}: {str(e)[:120]}"}


async def codef_sync_job() -> None:
    """전체 entity × org 순회."""
    global _last_run
    _last_run = {
        "started_at": now_kst().isoformat(),
        "finished_at": None,
        "ok_count": 0,
        "error_count": 0,
        "results": [],
    }
    logger.info("codef_sync_job start")
    try:
        with _db() as conn:
            targets = _gather_targets(conn)
    except Exception as e:
        logger.exception("failed to gather targets")
        _last_run["finished_at"] = now_kst().isoformat()
        _last_run["error_count"] = 1
        _last_run["results"] = [{"detail": f"gather_targets failed: {e}"}]
        return

    if not targets:
        logger.info("codef_sync_job: no targets")
        _last_run["finished_at"] = now_kst().isoformat()
        return

    # 순차 실행 — Codef 동시 호출에 대한 rate limit 안전 여유
    for entity_id, org in targets:
        result = await _sync_one(entity_id, org)
        _last_run["results"].append(result)
        if result.get("ok"):
            _last_run["ok_count"] += 1
        else:
            _last_run["error_count"] += 1

    _last_run["finished_at"] = now_kst().isoformat()
    logger.info("codef_sync_job done ok=%d err=%d",
                _last_run["ok_count"], _last_run["error_count"])


def start_scheduler() -> None:
    """FastAPI lifespan 시작 시 호출."""
    global _scheduler
    if _scheduler is not None:
        return

    # env var로 on/off + 주기 제어 (배포 환경에서 disable하기 쉽도록)
    if os.environ.get("SCHEDULER_ENABLED", "1").lower() in ("0", "false", "no"):
        logger.info("scheduler disabled via SCHEDULER_ENABLED")
        return

    # SCHEDULER_CRON_HOURS 우선 (예: "9,18" = KST 9시·18시). 없으면 INTERVAL_MIN fallback.
    cron_hours = os.environ.get("SCHEDULER_CRON_HOURS", "").strip()
    interval_min = int(os.environ.get("SCHEDULER_INTERVAL_MIN", "90"))

    _scheduler = AsyncIOScheduler()
    if cron_hours:
        # cron 모드 (KST 기준 고정 시간)
        hours_csv = ",".join(
            str(int(h.strip())) for h in cron_hours.split(",") if h.strip().isdigit()
        )
        trigger = CronTrigger(hour=hours_csv, minute=0, timezone="Asia/Seoul")
        trigger_desc = f"cron KST {hours_csv}:00"
    else:
        trigger = IntervalTrigger(minutes=interval_min)
        trigger_desc = f"interval {interval_min}min"

    _scheduler.add_job(
        codef_sync_job,
        trigger=trigger,
        id="codef_sync",
        name="Codef 카드/은행 자동 sync",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    _scheduler.start()
    logger.info("scheduler started (%s)", trigger_desc)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler shutdown")


def get_status() -> dict:
    """UI 노출용 현재 상태."""
    cron_hours = os.environ.get("SCHEDULER_CRON_HOURS", "").strip()
    info = {
        "running": _scheduler is not None and _scheduler.running,
        "mode": "cron" if cron_hours else "interval",
        "cron_hours": cron_hours or None,
        "interval_min": int(os.environ.get("SCHEDULER_INTERVAL_MIN", "90")),
        "enabled": os.environ.get("SCHEDULER_ENABLED", "1").lower() not in ("0", "false", "no"),
        "last_run": _last_run.copy() if _last_run else None,
    }
    if _scheduler is not None:
        jobs = []
        for j in _scheduler.get_jobs():
            jobs.append({
                "id": j.id,
                "name": j.name,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            })
        info["jobs"] = jobs
    return info


async def run_now() -> dict:
    """수동 트리거 — 즉시 sync_job 1회 실행."""
    await codef_sync_job()
    return _last_run.copy()

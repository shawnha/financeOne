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
    """자동 sync 대상 (entity_id, org) — 활성 env 의 connected_id 중 last_sync 가 있는 것만.

    안전장치: `codef_last_sync_<env>_<org>` (or legacy unscoped) 가 존재해야 포함됨 —
    초기 sync 는 사용자가 수동으로 먼저 돌려야 자동 인수인계됨.
    """
    from backend.services.integrations.codef import get_active_env

    active_env = get_active_env(conn)
    cid_prefix = f"codef_connected_id_{active_env}_"
    ls_prefix = f"codef_last_sync_{active_env}_"
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT cid.entity_id, cid.key
            FROM financeone.settings cid
            JOIN financeone.settings ls
              ON ls.entity_id = cid.entity_id
             AND ls.key = %s || regexp_replace(cid.key, %s, '')
             AND COALESCE(NULLIF(ls.value, ''), NULL) IS NOT NULL
            WHERE cid.key LIKE %s
              AND cid.entity_id IS NOT NULL
              AND COALESCE(NULLIF(cid.value, ''), NULL) IS NOT NULL
            ORDER BY cid.entity_id, cid.key
            """,
            [ls_prefix, f"^{cid_prefix}", f"{cid_prefix}%"],
        )
        rows = cur.fetchall()

        # demo 모드에서는 legacy unscoped 키도 호환 (마이그레이션 전 데이터)
        if active_env == "demo":
            cur.execute(
                """
                SELECT cid.entity_id, cid.key
                FROM financeone.settings cid
                JOIN financeone.settings ls
                  ON ls.entity_id = cid.entity_id
                 AND ls.key = 'codef_last_sync_' || regexp_replace(cid.key, '^codef_connected_id_', '')
                 AND COALESCE(NULLIF(ls.value, ''), NULL) IS NOT NULL
                WHERE cid.key LIKE 'codef_connected_id_%%'
                  AND cid.key NOT LIKE 'codef_connected_id_demo_%%'
                  AND cid.key NOT LIKE 'codef_connected_id_production_%%'
                  AND cid.entity_id IS NOT NULL
                  AND COALESCE(NULLIF(cid.value, ''), NULL) IS NOT NULL
                ORDER BY cid.entity_id, cid.key
                """
            )
            legacy_rows = cur.fetchall()
            # legacy 행도 active_env=demo 로 보고 합침 (org 만 추출)
            rows = list(rows) + [
                (eid, f"{cid_prefix}{k.removeprefix('codef_connected_id_')}")
                for eid, k in legacy_rows
            ]
    finally:
        cur.close()
    targets: list[tuple[int, str]] = []
    for entity_id, key in rows:
        org = key.removeprefix(cid_prefix)
        if org:
            targets.append((entity_id, org))
    # 중복 제거 (legacy + env-scoped 둘 다 있는 경우)
    seen = set()
    unique_targets = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique_targets.append(t)
    return unique_targets


def _incremental_date_range(
    conn: PgConnection, entity_id: int, org: str, env: Optional[str] = None,
) -> tuple[str, str]:
    """마지막 sync 시각 기반 (start_date, end_date) — YYYYMMDD.

    last_sync 없으면 오늘 기준 과거 3일. 있으면 그 날짜 -1일(여유분)부터 오늘.
    """
    from backend.services.integrations.codef import get_active_env
    eff_env = env or get_active_env(conn)
    cur = conn.cursor()
    try:
        # env-scoped 우선
        cur.execute(
            """
            SELECT value
            FROM financeone.settings
            WHERE entity_id = %s AND key = %s
            """,
            [entity_id, f"codef_last_sync_{eff_env}_{org}"],
        )
        row = cur.fetchone()
        if (not row or not row[0]) and eff_env == "demo":
            # legacy unscoped fallback (demo 만)
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
        get_active_credentials, resolve_base_url,
        get_codef_account, resolve_codef_card_numbers,
    )
    from backend.routers.integrations import _log_codef_error  # helper reuse

    try:
        with _db() as conn:
            active_env, client_id, client_secret, _pk = get_active_credentials(conn)
            if not client_id or not client_secret:
                return {"entity_id": entity_id, "org": org, "ok": False,
                        "detail": f"CODEF creds not configured for env={active_env}"}

            connected_id = get_connected_id(conn, entity_id, org, env=active_env)
            if not connected_id:
                return {"entity_id": entity_id, "org": org, "ok": False,
                        "detail": "connected_id missing"}
            start, end = _incremental_date_range(conn, entity_id, org)

            client = CodefClient(client_id, client_secret, base_url=resolve_base_url(active_env))
            try:
                if org in BANK_ORGS:
                    account = get_codef_account(conn, entity_id, org, env=active_env)
                    result = client.sync_bank_transactions(
                        conn, entity_id, connected_id, start, end, account=account, org=org,
                    )
                elif org in CARD_ORGS:
                    card_numbers = resolve_codef_card_numbers(conn, entity_id, org, env=active_env)
                    result = client.sync_card_approvals(
                        conn, entity_id, connected_id, start, end, org,
                        card_numbers=card_numbers,
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

                set_last_sync(conn, entity_id, org, env=active_env)
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
        # CODEF 타겟이 없어도 Mercury/Gowid 는 돌려야 하므로 return 하지 않음
        logger.info("codef_sync_job: no codef targets — mercury/gowid 만 실행")
    else:
        # 순차 실행 — Codef 동시 호출에 대한 rate limit 안전 여유
        for entity_id, org in targets:
            result = await _sync_one(entity_id, org)
            _last_run["results"].append(result)
            if result.get("ok"):
                _last_run["ok_count"] += 1
            else:
                _last_run["error_count"] += 1

    # Mercury sync (HOI) — codef 후 같은 cron 에서 자동 실행
    try:
        loop = asyncio.get_running_loop()
        mercury_result = await loop.run_in_executor(None, _mercury_sync_sync)
        _last_run["results"].append(mercury_result)
        if mercury_result.get("ok"):
            _last_run["ok_count"] += 1
        else:
            _last_run["error_count"] += 1
    except Exception as e:
        logger.warning("mercury sync in scheduler failed: %s", e)
        _last_run["results"].append({"source": "mercury", "ok": False, "detail": str(e)})
        _last_run["error_count"] += 1

    # Gowid sync (롯데카드) — codef 후 같은 cron 에서 자동 실행 (CODEF 와 격리)
    try:
        loop = asyncio.get_running_loop()
        gowid_result = await loop.run_in_executor(None, _gowid_sync_sync)
        _last_run["results"].append(gowid_result)
        if gowid_result.get("ok"):
            _last_run["ok_count"] += 1
        else:
            _last_run["error_count"] += 1
    except Exception as e:
        logger.warning("gowid sync in scheduler failed: %s", e)
        _last_run["results"].append({"source": "gowid", "ok": False, "detail": str(e)})
        _last_run["error_count"] += 1

    _last_run["finished_at"] = now_kst().isoformat()
    logger.info("auto_sync_job done ok=%d err=%d",
                _last_run["ok_count"], _last_run["error_count"])


def _mercury_sync_sync() -> dict:
    """Mercury HOI 자동 sync — accounts 모두 + balance + historical.

    토큰이 DB 에 저장되어 있으면 실행. 없으면 skip (non-fatal).
    """
    try:
        from backend.routers.integrations import _get_mercury_token
        from backend.services.integrations.mercury import MercuryClient
        from fastapi import HTTPException
    except Exception as e:
        return {"source": "mercury", "ok": False, "detail": f"import failed: {e}"}

    try:
        with _db() as conn:
            try:
                token = _get_mercury_token(conn)
            except HTTPException:
                return {"source": "mercury", "ok": False, "detail": "token not configured"}

            client = MercuryClient(token)
            synced_total = 0
            try:
                accounts = client.get_accounts()
                for acc in accounts:
                    acc_id = acc.get("id")
                    if not acc_id:
                        continue
                    try:
                        r = client.sync_transactions(conn, acc_id)
                        synced_total += r.get("synced", 0)
                    except Exception as e:
                        logger.warning("mercury account %s sync error: %s", acc_id, e)
                bal = client.sync_balance_snapshot(conn)
                hist = client.sync_historical_balances(conn)
                conn.commit()
                return {
                    "source": "mercury", "ok": True,
                    "detail": {
                        "accounts": len(accounts), "synced": synced_total,
                        "balance_upserted": bal.get("upserted"),
                        "historical_upserted": hist.get("snapshots_upserted"),
                        "drift": hist.get("reconstruction_drift"),
                    },
                }
            finally:
                client.close()
    except Exception as e:
        logger.exception("mercury sync crashed")
        return {"source": "mercury", "ok": False,
                "detail": f"exception: {type(e).__name__}: {str(e)[:120]}"}


def _gowid_sync_sync() -> dict:
    """Gowid 롯데카드 자동 sync — gowid_api_key 등록된 entity 전부, 최근 7일 롤링.

    dedup 은 gowid_id 마커 기준이라 겹치는 날 재sync 해도 안전. CODEF 와 격리됨.
    """
    try:
        from backend.services.integrations.gowid import GowidClient, get_api_key
    except Exception as e:
        return {"source": "gowid", "ok": False, "detail": f"import failed: {e}"}

    try:
        with _db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT entity_id FROM settings "
                "WHERE key = 'gowid_api_key' AND entity_id IS NOT NULL "
                "AND COALESCE(NULLIF(value, ''), NULL) IS NOT NULL "
                "ORDER BY entity_id"
            )
            entities = [r[0] for r in cur.fetchall()]
            if not entities:
                return {"source": "gowid", "ok": True, "detail": "no gowid entity", "synced": 0}

            end = today_kst()
            start = end - timedelta(days=7)
            synced_total = 0
            per_entity: dict[int, int] = {}
            for eid in entities:
                key = get_api_key(conn, eid)
                if not key:
                    continue
                client = GowidClient(key)
                try:
                    r = client.sync_expenses(
                        conn, eid, start.isoformat(), end.isoformat())
                    conn.commit()
                    synced_total += r.get("synced", 0)
                    per_entity[eid] = r.get("synced", 0)
                except Exception as e:
                    logger.warning("gowid entity %s sync error: %s", eid, e)
                finally:
                    client.close()
            return {"source": "gowid", "ok": True,
                    "detail": {"entities": entities, "synced": synced_total,
                               "per_entity": per_entity}}
    except Exception as e:
        logger.exception("gowid sync crashed")
        return {"source": "gowid", "ok": False,
                "detail": f"exception: {type(e).__name__}: {str(e)[:120]}"}


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
    interval_min = int(os.environ.get("SCHEDULER_INTERVAL_MIN", "120"))

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
    """UI 노출용 현재 상태.

    `last_sync_by_target` 은 DB(`settings.codef_last_sync_<org>`)에 영구 저장된
    마지막 sync 시각이라 in-memory `_last_run` 과 달리 Vercel(스케줄러 비활성,
    DISABLE_SCHEDULER=1)에서도 마지막 시각을 그대로 반환한다.
    """
    cron_hours = os.environ.get("SCHEDULER_CRON_HOURS", "").strip()
    serverless = os.environ.get("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes")
    info = {
        "running": _scheduler is not None and _scheduler.running,
        "mode": "cron" if cron_hours else "interval",
        "cron_hours": cron_hours or None,
        "interval_min": int(os.environ.get("SCHEDULER_INTERVAL_MIN", "120")),
        "enabled": os.environ.get("SCHEDULER_ENABLED", "1").lower() not in ("0", "false", "no"),
        "serverless": serverless,
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

    # DB 영구 기록 — Vercel(스케줄러 비활성) 환경에서도 마지막 sync 시각 표시 가능.
    info["last_sync_by_target"] = []
    try:
        if db_conn_mod._pool is not None:
            with _db() as conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        """
                        SELECT s.entity_id,
                               COALESCE(e.name, '?') AS entity_name,
                               regexp_replace(
                                   regexp_replace(s.key, '^codef_last_sync_', ''),
                                   '^(demo|production)_', ''
                               ) AS org,
                               regexp_replace(
                                   substring(s.key from '^codef_last_sync_(demo_|production_)?'),
                                   '_$', ''
                               ) AS env_prefix,
                               s.value,
                               s.updated_at
                        FROM financeone.settings s
                        LEFT JOIN financeone.entities e ON e.id = s.entity_id
                        WHERE s.key LIKE 'codef_last_sync_%'
                          AND s.entity_id IS NOT NULL
                        ORDER BY s.updated_at DESC NULLS LAST
                        """
                    )
                    rows = cur.fetchall()
                finally:
                    cur.close()
            info["last_sync_by_target"] = [
                {
                    "entity_id": r[0],
                    "entity_name": r[1],
                    "org": r[2],
                    "env": (r[3] or "legacy"),
                    "last_sync": (r[5].isoformat() if r[5] else r[4]),
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("get_status: last_sync_by_target query failed: %s", e)

    return info


async def run_now() -> dict:
    """수동 트리거 — 즉시 sync_job 1회 실행."""
    await codef_sync_job()
    return _last_run.copy()

"""FinanceOne v2 -- FastAPI Backend"""

import os
import re
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Vercel serverless: build root = /var/task (backend 폴더 내용이 펼쳐짐).
# 'backend.X' import 가 작동하도록 가짜 namespace package 등록.
# 로컬 dev 에서는 backend 가 실제 폴더이므로 등록 skip.
_THIS_DIR = Path(__file__).resolve().parent  # /var/task on Vercel, ./backend locally
if "backend" not in sys.modules and not (_THIS_DIR.parent / "backend").is_dir():
    _backend_pkg = types.ModuleType("backend")
    _backend_pkg.__path__ = [str(_THIS_DIR)]
    sys.modules["backend"] = _backend_pkg

# VERSION 파일은 프로젝트 루트에 있음. Vercel serverless 에서는 backend/ 가 root 라
# 파일이 없을 수 있어 fallback 처리.
def _load_version() -> str:
    candidates = [
        Path(__file__).resolve().parent.parent / "VERSION",
        Path(__file__).resolve().parent / "VERSION",
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text().strip()
            except Exception:
                continue
    return os.getenv("APP_VERSION", "0.0.0-dev")


_VERSION = _load_version()

# Vercel/serverless 환경: scheduler 비활성화 (cold start 마다 종료됨).
# 정기 sync 는 Vercel Cron Jobs 또는 외부 트리거로 대체.
_DISABLE_SCHEDULER = os.getenv("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes") or bool(os.getenv("VERCEL"))

from backend.database.connection import init_pool, close_pool
from backend.routers import entities, transactions, accounts, upload, dashboard, statements, slack, journal_entries, integrations, exchange_rates, intercompany, notes, cashflow, forecasts, card_settings, expenseone_match, invoices, opex
from backend.services.scheduler import start_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    if not _DISABLE_SCHEDULER:
        start_scheduler()
    yield
    if not _DISABLE_SCHEDULER:
        shutdown_scheduler()
    await close_pool()


app = FastAPI(
    title="FinanceOne API",
    version=_VERSION,
    lifespan=lifespan,
)

# CORS: 환경변수의 명시 origin + Vercel preview/production 도메인 정규식 fallback.
_ALLOWED_ORIGINS_ENV = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _ALLOWED_ORIGINS_ENV.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # *.vercel.app + 사용자 도메인 정규식 — 환경변수 ALLOWED_ORIGINS_REGEX 로 override 가능
    allow_origin_regex=os.getenv("ALLOWED_ORIGINS_REGEX", r"https://.*\.vercel\.app"),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(entities.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(upload.router)
app.include_router(dashboard.router)
app.include_router(statements.router)
app.include_router(slack.router)
app.include_router(journal_entries.router)
app.include_router(integrations.router)
app.include_router(exchange_rates.router)
app.include_router(intercompany.router)
app.include_router(notes.router)
app.include_router(cashflow.router)
app.include_router(forecasts.router)
app.include_router(card_settings.router)
app.include_router(expenseone_match.router)
app.include_router(invoices.router)
app.include_router(opex.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": _VERSION}

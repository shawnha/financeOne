"""FinanceOne v2 -- FastAPI Backend"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()

from backend.database.connection import init_pool, close_pool
from backend.routers import entities, transactions, accounts, upload, dashboard, statements, slack, journal_entries, integrations, exchange_rates, intercompany, notes, cashflow, forecasts, card_settings, expenseone_match
from backend.services.scheduler import start_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    start_scheduler()
    yield
    shutdown_scheduler()
    await close_pool()


app = FastAPI(
    title="FinanceOne API",
    version=_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
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


@app.get("/health")
async def health():
    return {"status": "ok", "version": _VERSION}

"""FinanceOne v2 -- FastAPI Backend"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database.connection import init_pool, close_pool
from backend.routers import entities, transactions, accounts, upload, dashboard, statements, slack, journal_entries, integrations, exchange_rates, intercompany, notes, cashflow, forecasts, card_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(
    title="FinanceOne API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
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


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.4.0"}

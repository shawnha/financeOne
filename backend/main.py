"""FinanceOne v2 — FastAPI Backend"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database.connection import init_pool, close_pool
from backend.routers import entities, transactions, accounts, upload, dashboard, statements


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
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(entities.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(upload.router)
app.include_router(dashboard.router)
app.include_router(statements.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

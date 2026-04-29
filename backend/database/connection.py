"""Database connection pool using psycopg2 (Supabase)"""

import logging
import os
from collections.abc import Generator
import psycopg2
from psycopg2 import pool
from psycopg2.extensions import connection as PgConnection
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_pool: pool.ThreadedConnectionPool | None = None

# Vercel serverless 에서도 FastAPI threadpool 이 같은 lambda 안에서 여러 동시 요청
# 처리 → 한 페이지에서 여러 endpoint 병렬 호출 시 pool 고갈.
# minconn=0 (lazy, cold start 단축) + maxconn=10 (concurrent 보장).
_IS_SERVERLESS = bool(os.getenv("VERCEL"))
_MIN_CONN = 0 if _IS_SERVERLESS else 2
_MAX_CONN = 10


async def init_pool():
    global _pool
    db_url = os.environ["DATABASE_URL"]
    _pool = pool.ThreadedConnectionPool(minconn=_MIN_CONN, maxconn=_MAX_CONN, dsn=db_url)
    logger.info(
        "Database connection pool initialized (min=%d, max=%d, serverless=%s)",
        _MIN_CONN, _MAX_CONN, _IS_SERVERLESS,
    )


async def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")


def _acquire_healthy_conn(max_attempts: int = 3) -> PgConnection:
    """Get a connection from pool, set search_path, discard stale conns.

    SET search_path TO financeone, public 매 acquire 마다 실행 — Supabase pooler 는
    DSN options 무시하고, psycopg2 C-extension conn 에 marker attribute 못 붙여서
    캐싱 불가. icn1 리전이라 RTT ~10ms 라 비용 무시 가능.
    """
    assert _pool is not None
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        conn = _pool.getconn()
        if not conn.closed:
            try:
                cur = conn.cursor()
                cur.execute("SET search_path TO financeone, public")
                cur.close()
                return conn
            except psycopg2.Error as e:
                last_err = e
                logger.warning("Stale DB connection (attempt %d/%d): %s", attempt + 1, max_attempts, e)
        try:
            _pool.putconn(conn, close=True)
        except Exception as put_err:
            logger.warning("Failed to discard stale conn: %s", put_err)
    raise RuntimeError(f"Could not acquire healthy DB connection after {max_attempts} attempts: {last_err}") from last_err


def get_db() -> Generator[PgConnection, None, None]:
    """FastAPI Depends() generator for DB connections."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized")
    conn = _acquire_healthy_conn()
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception as e:
            logger.warning("Rollback failed: %s", e)
            try:
                _pool.putconn(conn, close=True)
                return
            except Exception:
                pass
        _pool.putconn(conn)

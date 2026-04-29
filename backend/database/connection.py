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

# Vercel serverless: 한 lambda 인스턴스가 동시에 1개 요청만 처리.
# minconn=0 으로 init 시 connection 안 만들고, 첫 요청 때 lazy 생성 → cold start 단축.
_IS_SERVERLESS = bool(os.getenv("VERCEL"))
_MIN_CONN = 0 if _IS_SERVERLESS else 2
_MAX_CONN = 2 if _IS_SERVERLESS else 10


def _build_dsn() -> str:
    """DATABASE_URL + search_path 를 connect-time options 로 주입.

    매 request 마다 SET search_path 실행하면 Vercel iad1 ↔ Supabase ap-northeast-2
    RTT (~150ms) 이 추가됨. options 로 옮기면 connection 생성 시 1회만 실행.
    """
    db_url = os.environ["DATABASE_URL"]
    sep = "&" if "?" in db_url else "?"
    if "options=" in db_url:
        return db_url  # 이미 사용자가 options 지정했으면 건드리지 않음
    return f"{db_url}{sep}options=-csearch_path%3Dfinanceone,public"


async def init_pool():
    global _pool
    dsn = _build_dsn()
    _pool = pool.ThreadedConnectionPool(minconn=_MIN_CONN, maxconn=_MAX_CONN, dsn=dsn)
    logger.info(
        "Database connection pool initialized (min=%d, max=%d, serverless=%s, search_path=options)",
        _MIN_CONN, _MAX_CONN, _IS_SERVERLESS,
    )


async def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")


def _acquire_healthy_conn(max_attempts: int = 3) -> PgConnection:
    """Get a connection from pool. Trust conn.closed (no roundtrip), let real query
    surface connection errors. search_path 는 DSN options 으로 connect-time 설정.

    Vercel iad1 ↔ Supabase ap-northeast-2 RTT ~170ms — health probe 1회 = 170ms 절약.
    Stale 은 첫 쿼리에서 InterfaceError 로 잡아서 재시도.
    """
    assert _pool is not None
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        conn = _pool.getconn()
        if not conn.closed:
            return conn
        last_err = RuntimeError("Connection from pool is closed")
        try:
            _pool.putconn(conn, close=True)
        except Exception as put_err:
            logger.warning("Failed to discard closed conn: %s", put_err)
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

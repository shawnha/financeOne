"""Database connection pool using psycopg2 (Supabase)"""

import logging
import os
from collections.abc import Generator
from psycopg2 import pool
from psycopg2.extensions import connection as PgConnection
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_pool: pool.ThreadedConnectionPool | None = None


async def init_pool():
    global _pool
    db_url = os.environ["DATABASE_URL"]
    _pool = pool.ThreadedConnectionPool(minconn=2, maxconn=10, dsn=db_url)
    logger.info("Database connection pool initialized (Supabase)")


async def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")


def get_db() -> Generator[PgConnection, None, None]:
    """FastAPI Depends() generator for DB connections."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized")
    conn = _pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO financeone, public")
        cur.close()
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception as e:
            logger.warning("Rollback failed: %s", e)
        _pool.putconn(conn)

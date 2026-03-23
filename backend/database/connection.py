"""Database connection pool using psycopg2"""

import os
from collections.abc import Generator
from psycopg2 import pool
from psycopg2.extensions import connection as PgConnection
from dotenv import load_dotenv

load_dotenv()

_pool: pool.ThreadedConnectionPool | None = None


async def init_pool():
    global _pool
    db_url = os.environ["DATABASE_URL"]
    _pool = pool.ThreadedConnectionPool(minconn=2, maxconn=10, dsn=db_url)


async def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


def get_db() -> Generator[PgConnection, None, None]:
    """FastAPI Depends() generator for DB connections."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized")
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        try:
            conn.rollback()  # 미커밋 트랜잭션 정리
        except Exception:
            pass
        _pool.putconn(conn)

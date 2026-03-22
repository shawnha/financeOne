"""Database connection pool using psycopg2"""

import os
from psycopg2 import pool
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


def get_conn():
    if _pool is None:
        raise RuntimeError("Connection pool not initialized")
    return _pool.getconn()


def put_conn(conn):
    if _pool:
        _pool.putconn(conn)

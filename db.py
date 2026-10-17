"""Oracle database access for QBank.

A single connection pool is created when the application starts. Every query
goes through :func:`query` or :func:`execute`, which borrow a connection from
the pool and return it automatically.

All statements use bind variables. Apart from preventing SQL injection, this
lets Oracle reuse the parsed statement from the shared pool, which matters on
the modest hardware this runs on.
"""

from contextlib import contextmanager
import logging

import oracledb

from config import Config

log = logging.getLogger(__name__)

_pool: oracledb.ConnectionPool | None = None


def init_pool() -> None:
    """Create the connection pool. Called once at application start-up."""
    global _pool
    if _pool is not None:
        return
    _pool = oracledb.create_pool(
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        dsn=Config.DB_DSN,
        min=Config.DB_POOL_MIN,
        max=Config.DB_POOL_MAX,
        increment=1,
        getmode=oracledb.POOL_GETMODE_WAIT,
    )
    log.info("Oracle connection pool ready (dsn=%s)", Config.DB_DSN)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_connection():
    """Borrow a connection from the pool and release it afterwards."""
    if _pool is None:
        init_pool()
    connection = _pool.acquire()
    try:
        yield connection
    finally:
        _pool.release(connection)


def _rows_as_dicts(cursor) -> list[dict]:
    columns = [c[0].lower() for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query(sql: str, params: dict | None = None) -> list[dict]:
    """Run a SELECT and return the rows as a list of dictionaries."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params or {})
            return _rows_as_dicts(cursor)


def query_one(sql: str, params: dict | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: dict | None = None) -> int:
    """Run an INSERT, UPDATE or DELETE and commit. Returns rows affected."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params or {})
            affected = cursor.rowcount
        connection.commit()
        return affected


def insert_returning_id(sql: str, params: dict, id_column: str = "id") -> int:
    """Run an INSERT ... RETURNING <pk> INTO :id and return the new key."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            out_var = cursor.var(int)
            cursor.execute(sql, {**params, id_column: out_var})
            connection.commit()
            value = out_var.getvalue()
            # python-oracledb returns a list for RETURNING binds.
            return int(value[0] if isinstance(value, list) else value)


def healthy() -> bool:
    """True if the database answers a trivial query."""
    try:
        query("SELECT 1 AS ok FROM dual")
        return True
    except oracledb.Error as exc:
        log.warning("Database health check failed: %s", exc)
        return False

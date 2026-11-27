"""Shared fixtures for adapter tests against a real Postgres database.

Set TEST_POSTGRES_DSN to a DSN that may create and drop databases. Without it,
tests that request `pg_pool` or `clean_tables` are skipped.
"""
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"


@pytest.fixture(scope="session")
def pg_pool():
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is not set")
    db_name = f"api_test_{os.getpid()}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
    pool = None
    try:
        test_dsn = make_conninfo(dsn, dbname=db_name)
        with psycopg.connect(test_dsn, autocommit=True) as conn:
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                conn.execute(migration.read_text(encoding="utf-8"))
        pool = ConnectionPool(test_dsn, open=False)
        pool.open(wait=True, timeout=10)
        yield pool
    finally:
        if pool is not None:
            pool.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name))
            )


@pytest.fixture
def clean_tables(pg_pool):
    """Return a function `register(*tables)`; registered tables are truncated
    (with CASCADE) now and after the test, so tests stay independent."""
    tables: list[str] = []

    def truncate() -> None:
        if not tables:
            return
        names = sql.SQL(", ").join(sql.Identifier(t) for t in tables)
        with pg_pool.connection() as conn:
            conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(names))

    def register(*names: str) -> None:
        tables.extend(n for n in names if n not in tables)
        truncate()

    yield register
    truncate()

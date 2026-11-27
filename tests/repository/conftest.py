"""Fixtures for the PostgreSQL adapter tests.

They need a reachable database, given by TEST_DATABASE_URL, and are skipped
without it. Each test run builds the schema from db/migrations inside a
private PostgreSQL schema and drops it afterwards, so the data in the target
database is never touched. Override the migrations folder with MIGRATIONS_DIR.
"""
import os
import uuid
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

_DEFAULT_MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


@pytest.fixture(scope="session")
def pg_pool():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    migrations = Path(os.environ.get("MIGRATIONS_DIR", _DEFAULT_MIGRATIONS))
    schema = f"test_{uuid.uuid4().hex[:12]}"
    pool = ConnectionPool(
        url, min_size=1, max_size=4, open=True,
        kwargs={"options": f"-c search_path={schema}", "autocommit": False},
    )
    admin = ConnectionPool(url, min_size=1, max_size=1, open=True)
    with admin.connection() as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    try:
        with pool.connection() as conn:
            for sql_file in sorted(migrations.glob("*.sql")):
                conn.execute(sql_file.read_text())
        yield pool
    finally:
        pool.close()
        with admin.connection() as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


@pytest.fixture(autouse=False)
def clean_pg(pg_pool):
    """Empty the mutable tables before a test. Reference rows (roles, null defaults) stay."""
    with pg_pool.connection() as conn:
        conn.execute(
            "TRUNCATE AssistanceRecord, RecordMetadata, Employee RESTART IDENTITY CASCADE"
        )
        conn.execute("DELETE FROM Room WHERE uniqueId > 0")
        conn.execute("DELETE FROM Subsidiary WHERE uniqueId > 0")
    return pg_pool

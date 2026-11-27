"""Fixtures for the HTTP tests, which run the real app against PostgreSQL.

They reuse the session schema of the repository adapter tests and are skipped
without TEST_DATABASE_URL.
"""
import os
from urllib.parse import unquote, urlparse

import pytest

from tests.repository.conftest import clean_pg, pg_pool  # noqa: F401

JWT_SECRET = "test-secret-with-at-least-32-characters"


@pytest.fixture
def app_env(clean_pg, monkeypatch):  # noqa: F811
    """Environment for `create_app`, pointing at the private test schema.

    Leaves subsidiaries 1 and 2 (rooms 1 and 2 in subsidiary 1) ready for the
    bootstrap administrator and resets the id sequences the tests rely on.
    """
    with clean_pg.connection() as conn:
        schema = conn.execute("SHOW search_path").fetchone()[0].split(",")[0].strip()
        conn.execute("TRUNCATE Capacitation, EmployeeCapacitation, RevokedToken, LoginAttempt RESTART IDENTITY CASCADE")
        conn.execute("ALTER TABLE Subsidiary ALTER COLUMN uniqueId RESTART WITH 1")
        conn.execute("ALTER TABLE Room ALTER COLUMN uniqueId RESTART WITH 1")
        conn.execute("INSERT INTO Subsidiary (name) VALUES ('S1'), ('S2')")
        conn.execute(
            "INSERT INTO Room (subsidiary_id, name) VALUES (1, 'R1'), (1, 'R2')"
        )
    url = urlparse(os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
    return {
        "JWT_SECRET": JWT_SECRET,
        "POSTGRES_HOST": url.hostname or "localhost",
        "POSTGRES_PORT": str(url.port or 5432),
        "POSTGRES_DB": url.path.lstrip("/"),
        "POSTGRES_USER": unquote(url.username or ""),
        "POSTGRES_PASSWORD": unquote(url.password or ""),
        "BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
        "BOOTSTRAP_ADMIN_PASSWORD": "admin-pass",
    }

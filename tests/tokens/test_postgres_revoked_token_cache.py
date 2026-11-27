from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.tokens.postgres_revoked_token_cache import PostgresRevokedTokenCache
from api.tests.fakes import FakeClock


@pytest.fixture
def employee_id(pg_pool, clean_tables):
    clean_tables("employee", "revokedtoken")
    with pg_pool.connection() as conn:
        return conn.execute(
            "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
            "VALUES (0, 1, 'A', 'a@x.com', 'h') RETURNING id"
        ).fetchone()[0]


def future(minutes=5):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def rows(pool):
    with pool.connection() as conn:
        return conn.execute("SELECT jti, employee_id FROM RevokedToken").fetchall()


def insert_expired(pool, employee_id, jti="gone"):
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO RevokedToken (jti, employee_id, expires_at) "
            "VALUES (%s, %s, now() - interval '1 minute')",
            (jti, employee_id),
        )


def test_revoked_token_is_reported(pg_pool, employee_id):
    cache = PostgresRevokedTokenCache(pg_pool, FakeClock())
    assert not cache.is_revoked("t")
    cache.revoke("t", employee_id, future())
    assert cache.is_revoked("t") and not cache.is_revoked("other")
    assert rows(pg_pool) == [("t", employee_id)]


def test_revoke_is_idempotent(pg_pool, employee_id):
    cache = PostgresRevokedTokenCache(pg_pool, FakeClock())
    cache.revoke("t", employee_id, future())
    cache.revoke("t", employee_id, future())
    assert len(rows(pg_pool)) == 1


def test_revoke_with_past_expiry_stores_nothing(pg_pool, employee_id):
    cache = PostgresRevokedTokenCache(pg_pool, FakeClock())
    cache.revoke("old", employee_id, future(-1))
    assert rows(pg_pool) == [] and not cache.is_revoked("old")


def test_expired_revocation_is_not_reported(pg_pool, employee_id):
    insert_expired(pg_pool, employee_id)
    assert not PostgresRevokedTokenCache(pg_pool, FakeClock()).is_revoked("gone")


def test_revocation_survives_a_new_instance(pg_pool, employee_id):
    PostgresRevokedTokenCache(pg_pool, FakeClock()).revoke("t", employee_id, future())
    assert PostgresRevokedTokenCache(pg_pool, FakeClock()).is_revoked("t")


def test_hourly_cleanup_deletes_expired_rows_only(pg_pool, employee_id):
    clock = FakeClock()
    cache = PostgresRevokedTokenCache(pg_pool, clock)
    insert_expired(pg_pool, employee_id)
    cache.revoke("a", employee_id, future())
    assert {r[0] for r in rows(pg_pool)} == {"gone", "a"}
    clock._now = clock.now() + timedelta(hours=1, seconds=1)
    cache.revoke("b", employee_id, future())
    assert {r[0] for r in rows(pg_pool)} == {"a", "b"}

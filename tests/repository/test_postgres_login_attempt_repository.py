from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.repository.postgres_login_attempt_repository import (
    PostgresLoginAttemptRepository,
)
from api.tests.fakes import FakeClock, FakeLoginAttemptRepository

T0 = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)


@pytest.fixture(params=["fake", "postgres"])
def repo(request):
    if request.param == "fake":
        return FakeLoginAttemptRepository()
    pg_pool = request.getfixturevalue("pg_pool")
    request.getfixturevalue("clean_tables")("loginattempt")
    return PostgresLoginAttemptRepository(pg_pool, FakeClock(T0))


def test_counts_failures_after_since(repo):
    repo.record("a@x.com", T0 - 20 * MIN, False)
    repo.record("a@x.com", T0 - 5 * MIN, False)
    repo.record("a@x.com", T0 - 4 * MIN, False)
    assert repo.recent_failures("a@x.com", T0 - 15 * MIN) == 2


def test_success_resets_count_and_email_is_case_insensitive(repo):
    repo.record("A@x.com", T0 - 5 * MIN, False)
    repo.record("a@x.com", T0 - 4 * MIN, True)
    repo.record("a@X.com", T0 - 3 * MIN, False)
    assert repo.recent_failures("a@x.COM", T0 - 15 * MIN) == 1


def test_other_emails_are_not_counted(repo):
    repo.record("b@x.com", T0 - MIN, False)
    assert repo.recent_failures("a@x.com", T0 - 15 * MIN) == 0


def test_postgres_cleanup_deletes_rows_older_than_a_day(pg_pool, clean_tables):
    clean_tables("loginattempt")
    clock = FakeClock(T0)
    repo = PostgresLoginAttemptRepository(pg_pool, clock)
    repo.record("a@x.com", T0 - timedelta(days=2), False)
    clock._now = T0 + timedelta(hours=2)
    repo.record("a@x.com", clock.now(), False)
    with pg_pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM LoginAttempt").fetchone()[0] == 1

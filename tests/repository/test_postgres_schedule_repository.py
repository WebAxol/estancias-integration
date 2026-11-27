import pytest

from src.domain.models.employee import DayOfWeek
from src.infrastructure.repository.postgres_schedule_repository import (
    PostgresScheduleRepository,
)


@pytest.fixture
def repo(clean_pg):
    return PostgresScheduleRepository(clean_pg)


@pytest.fixture
def creator(clean_pg):
    """A real employee: clean_pg empties Employee, so created_by = 0 would not resolve."""
    with clean_pg.connection() as conn:
        conn.execute("INSERT INTO Subsidiary (name) VALUES ('S1')")
        return conn.execute(
            "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
            "SELECT uniqueId, 1, 'E1', 'e1@x.com', 'h' FROM Subsidiary WHERE uniqueId > 0 "
            "RETURNING id"
        ).fetchone()[0]


def test_find_by_id_returns_schedule_with_its_days(repo, clean_pg, creator):
    with clean_pg.connection() as conn:
        meta = conn.execute(
            "INSERT INTO RecordMetadata (created_by, lastly_updated_by) VALUES (%s, %s) RETURNING id",
            (creator, creator),
        ).fetchone()[0]
        sid = conn.execute(
            "INSERT INTO Schedule (name, record_meta_id) VALUES ('Morning', %s) RETURNING id",
            (meta,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO ScheduleDay (scheduleId, day, entry_time, exit_time) "
            "VALUES (%s, 'We', '06:00', '14:00')",
            (sid,),
        )
    schedule = repo.find_by_id(sid)
    assert schedule.name == "Morning"
    assert schedule.for_day(DayOfWeek.WEDNESDAY).entry_time.hour == 6
    assert schedule.for_day(DayOfWeek.MONDAY) is None


def test_find_by_id_returns_none_when_missing(repo):
    assert repo.find_by_id(999999) is None
def test_list_all_returns_active_schedules_with_days(repo, clean_pg, creator):
    with clean_pg.connection() as conn:
        for name, active in (("Morning", True), ("Retired", False)):
            meta = conn.execute(
                "INSERT INTO RecordMetadata (created_by, lastly_updated_by, active) "
                "VALUES (%s, %s, %s) RETURNING id",
                (creator, creator, active),
            ).fetchone()[0]
            sid = conn.execute(
                "INSERT INTO Schedule (name, record_meta_id) VALUES (%s, %s) RETURNING id",
                (name, meta),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO ScheduleDay (scheduleId, day, entry_time, exit_time) "
                "VALUES (%s, 'Mo', '06:00', '14:00')",
                (sid,),
            )
    schedules = repo.list_all()
    assert [s.name for s in schedules] == ["Morning"]
    assert len(schedules[0].days) == 1

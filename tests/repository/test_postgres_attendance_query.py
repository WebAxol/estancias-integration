from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.domain.models.access import Scope
from src.domain.models.attendance_entry import AttendanceStatus as S
from src.domain.models.attendance_view import AttendanceHistoryFilter
from src.domain.models.paging import Page
from src.infrastructure.repository.postgres_attendance_query import (
    PostgresAttendanceQuery,
)
from src.infrastructure.repository.postgres_attendance_repository import (
    PostgresAttendanceRepository,
)
from api.tests.fakes import make_attendance as _make

DAY = date(2025, 3, 10)
NOON = datetime(2025, 3, 10, 18, 0, tzinfo=timezone.utc)


def _entry(employee_id, status, day=DAY, author=None):
    at = datetime.combine(day, NOON.timetz())
    entry = _make(employee_id, status, at, work_date=day)
    author = author or employee_id
    return replace(
        entry, metadata=replace(entry.metadata, created_by=author, lastly_updated_by=author)
    )


@pytest.fixture
def world(clean_pg):
    """Site A: room R1 (minimum 2: e1, e2, e3 and a terminated one) and R2 (no minimum).
    Site B: room R3 (minimum 1: e4). Site C: no rooms."""
    ids = {}
    with clean_pg.connection() as conn:
        for key, name in (("a", "Site A"), ("b", "Site B"), ("c", "Site C")):
            ids[key] = conn.execute(
                "INSERT INTO Subsidiary (name) VALUES (%s) RETURNING uniqueId", (name,)
            ).fetchone()[0]
        for key, site, name, required in (
            ("r1", "a", "R1", 2), ("r2", "a", "R2", 0), ("r3", "b", "R3", 1)
        ):
            ids[key] = conn.execute(
                "INSERT INTO Room (subsidiary_id, name, required_personal) "
                "VALUES (%s, %s, %s) RETURNING uniqueId", (ids[site], name, required),
            ).fetchone()[0]
        for key, site, room, terminated in (
            ("e1", "a", "r1", None), ("e2", "a", "r1", None), ("e3", "a", "r1", None),
            ("gone", "a", "r1", date(2025, 1, 1)), ("e4", "b", "r3", None),
        ):
            ids[key] = conn.execute(
                "INSERT INTO Employee (subsidiary_id, room_id, roleId, name, email, "
                "password_hash, hired_at, terminated_at) "
                "VALUES (%s, %s, 1, %s, %s, 'h', '2024-01-01', %s) "
                "RETURNING id",
                (ids[site], ids[room], key.upper(), f"{key}@x.com", terminated),
            ).fetchone()[0]
    repo = PostgresAttendanceRepository(clean_pg)
    repo.save_all([
        _entry(ids["e1"], S.ON_TIME),
        _entry(ids["e2"], S.ABSENT, author=ids["e1"]),
        _entry(ids["e1"], S.EXITED),
        _entry(ids["e1"], S.LATE, day=DAY - timedelta(days=1)),
    ])
    ids["repo"], ids["query"] = repo, PostgresAttendanceQuery(clean_pg)
    return ids


def test_day_sheet_groups_rooms_employees_entries_and_coverage(world):
    sheets = world["query"].day_sheet(Scope(subsidiary_id=None), DAY)
    assert [s.room.name for s in sheets] == ["R1", "R2", "R3"]
    r1, r2, r3 = sheets
    assert r1.work_date == DAY and r1.room.required_personal == 2
    assert [row.employee.employee.id for row in r1.employees] == [
        world["e1"], world["e2"], world["e3"]
    ]
    assert r1.employees[0].employee.role_name is not None
    assert [a.status for a in r1.employees[0].attendances] == [S.ON_TIME, S.EXITED]
    assert [a.status for a in r1.employees[1].attendances] == [S.ABSENT]
    assert r1.employees[2].attendances == ()
    c = r1.coverage
    assert (c.required, c.assigned, c.absent, c.present) == (2, 3, 1, 1)
    assert c.available == 2 and not c.below_minimum
    assert r2.employees == () and r2.coverage.assigned == 0
    assert (r3.coverage.assigned, r3.coverage.present) == (1, 0)


def test_day_sheet_honours_site_and_room_scope(world):
    query = world["query"]
    assert [s.room.name for s in query.day_sheet(Scope(world["b"]), DAY)] == ["R3"]
    only = query.day_sheet(Scope(world["a"], room_id=world["r1"]), DAY)
    assert [s.room.name for s in only] == ["R1"]
    assert query.day_sheet(Scope(world["b"], room_id=world["r1"]), DAY) == []


def test_day_sheet_defaults_to_today_in_the_site_zone(world, clean_pg):
    today = datetime.now(ZoneInfo("America/Mexico_City")).date()
    world["repo"].save_all([_entry(world["e3"], S.ON_TIME, day=today)])
    sheet = world["query"].day_sheet(Scope(world["a"], room_id=world["r1"]), None)[0]
    assert sheet.work_date == today
    assert [a.status for a in sheet.employees[2].attendances] == [S.ON_TIME]


def test_coverage_gives_one_row_per_site_with_all_its_rooms(world):
    sites = world["query"].coverage(Scope(subsidiary_id=None), DAY)
    assert [s.name for s in sites] == ["Site A", "Site B", "Site C"]
    a, b, c = sites
    assert a.work_date == DAY
    assert (a.required, a.assigned, a.absent, a.present) == (2, 3, 1, 1)
    assert a.complete and a.rooms_below_minimum == 0
    assert (b.required, b.assigned, b.present) == (1, 1, 0)
    assert c.rooms == () and c.complete


def test_coverage_flags_a_room_below_its_minimum(world):
    world["repo"].save_all([_entry(world["e3"], S.ABSENT)])
    a = world["query"].coverage(Scope(world["a"]), DAY)[0]
    assert a.absent == 2 and a.rooms_below_minimum == 1 and not a.complete


def test_coverage_scope_and_default_date(world):
    query = world["query"]
    assert [s.name for s in query.coverage(Scope(world["b"]), DAY)] == ["Site B"]
    today = datetime.now(ZoneInfo("America/Mexico_City")).date()
    assert query.coverage(Scope(world["b"]), None)[0].work_date == today


def _filter(world, **overrides):
    data = dict(scope=Scope(subsidiary_id=None), date_from=DAY - timedelta(days=5), date_to=DAY)
    data.update(overrides)
    return AttendanceHistoryFilter(**data)


def test_history_orders_newest_first_with_names_and_total(world):
    result = world["query"].history(_filter(world), Page(limit=10, offset=0))
    assert result.total == 4
    assert [(v.entry.work_date, v.entry.status) for v in result.items][:1] == [
        (DAY, S.EXITED)
    ]
    assert result.items[-1].entry.work_date == DAY - timedelta(days=1)
    absent = next(v for v in result.items if v.entry.status is S.ABSENT)
    assert (absent.employee_name, absent.registered_by_name) == ("E2", "E1")
    assert absent.entry.reason and absent.entry.room_id == world["r1"]


def test_history_filters_and_pages(world):
    query = world["query"]
    by_range = query.history(_filter(world, date_from=DAY), Page())
    assert by_range.total == 3
    by_status = query.history(_filter(world, status=S.ABSENT), Page())
    assert [v.employee_name for v in by_status.items] == ["E2"]
    by_employee = query.history(_filter(world, employee_id=world["e1"]), Page())
    assert by_employee.total == 3
    by_room = query.history(_filter(world, room_id=world["r3"]), Page())
    assert by_room.total == 0 and by_room.items == ()
    second = query.history(_filter(world), Page(limit=2, offset=2))
    assert len(second.items) == 2 and second.total == 4


def test_history_scope_by_site_and_room(world):
    query = world["query"]
    assert query.history(_filter(world, scope=Scope(world["b"])), Page()).total == 0
    in_room = query.history(
        _filter(world, scope=Scope(world["a"], room_id=world["r1"])), Page()
    )
    assert in_room.total == 4
    assert query.history(
        _filter(world, scope=Scope(world["a"], room_id=world["r2"])), Page()
    ).total == 0


def test_history_keeps_the_total_when_the_page_is_past_the_end(world):
    result = world["query"].history(_filter(world), Page(limit=5, offset=50))
    assert result.items == () and result.total == 4

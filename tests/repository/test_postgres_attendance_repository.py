import threading
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from src.application.errors import (
    AttendanceAlreadyRecordedError,
    ClientUuidConflictError,
)
from src.domain.models.attendance_entry import AttendanceStatus as S
from src.infrastructure.repository.postgres_attendance_repository import (
    PostgresAttendanceRepository,
)
from api.tests.fakes import NOW, FakeAttendanceRepository, make_attendance as _make


def make_attendance(employee_id, status=S.ON_TIME, at=NOW, author=None, **overrides):
    """Like the shared helper, but `created_by` must be a real employee (foreign key)."""
    entry = _make(employee_id, status, at, **overrides)
    author = author or employee_id
    return replace(
        entry, metadata=replace(entry.metadata, created_by=author, lastly_updated_by=author)
    )


@pytest.fixture
def repo(clean_pg):
    with clean_pg.connection() as conn:
        conn.execute("INSERT INTO Subsidiary (name) VALUES ('S1')")
        conn.execute(
            "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
            "SELECT uniqueId, 1, 'E' || n, 'e' || n || '@x.com', 'h' "
            "FROM Subsidiary, generate_series(1, 3) n WHERE uniqueId > 0"
        )
    return PostgresAttendanceRepository(clean_pg)


@pytest.fixture
def ids(clean_pg, repo):
    with clean_pg.connection() as conn:
        return [r[0] for r in conn.execute("SELECT id FROM Employee ORDER BY id")]


def test_save_all_assigns_ids_and_round_trips(repo, ids):
    first, second = ids[0], ids[1]
    saved = repo.save_all(
        [make_attendance(first, client_uuid=uuid4()), make_attendance(second, S.LATE)]
    )
    assert saved[0].id is not None and saved[1].id == saved[0].id + 1
    assert saved[0].metadata.id is not None
    found = repo.list_by_employees_on_day([first, second], NOW.date())
    assert found == saved
    assert found[0].registered_at == NOW and found[0].registered_at.tzinfo is not None
    assert found[0].occurred_at == NOW and found[0].work_date == NOW.date()


def test_list_finds_entries_by_work_date_not_by_registration_time(repo, ids):
    a, b, c = ids
    yesterday = NOW.date() - timedelta(days=1)
    # Registered now, but belongs to yesterday's work date (an offline upload).
    repo.save_all(
        [
            make_attendance(a),
            make_attendance(b),
            make_attendance(a, S.EXITED, work_date=yesterday),
        ]
    )
    assert [(x.employee_id, x.status) for x in
            repo.list_by_employees_on_day([a], NOW.date())] == [(a, S.ON_TIME)]
    assert [(x.employee_id, x.status) for x in
            repo.list_by_employees_on_day([a], yesterday)] == [(a, S.EXITED)]
    assert repo.list_by_employees_on_day([c], NOW.date()) == []
    assert repo.list_by_employees_on_day([], NOW.date()) == []


def test_find_by_client_uuids(repo, ids):
    known, other = uuid4(), uuid4()
    saved = repo.save_all(
        [make_attendance(ids[0], client_uuid=known), make_attendance(ids[1])]
    )
    assert repo.find_by_client_uuids([known, other]) == [saved[0]]
    assert repo.find_by_client_uuids([other]) == []
    assert repo.find_by_client_uuids([]) == []


def test_save_all_is_all_or_nothing(repo, ids):
    with pytest.raises(Exception):
        repo.save_all([make_attendance(ids[0]), make_attendance(999_999)])
    assert repo.list_by_employees_on_day(ids, NOW.date()) == []


def test_second_arrival_of_the_day_is_rejected_and_rolls_back_the_batch(repo, ids):
    repo.save_all([make_attendance(ids[0])])
    with pytest.raises(AttendanceAlreadyRecordedError):
        repo.save_all([make_attendance(ids[1]), make_attendance(ids[0], S.LATE)])
    assert [e.employee_id for e in repo.list_by_employees_on_day(ids, NOW.date())] == [ids[0]]


def test_one_arrival_and_one_exit_per_day(repo, ids):
    repo.save_all([make_attendance(ids[0]), make_attendance(ids[0], S.EXITED)])
    with pytest.raises(AttendanceAlreadyRecordedError):
        repo.save_all([make_attendance(ids[0], S.EXITED)])


def test_repeated_client_uuid_is_rejected(repo, ids):
    token = uuid4()
    repo.save_all([make_attendance(ids[0], client_uuid=token)])
    with pytest.raises(ClientUuidConflictError):
        repo.save_all([make_attendance(ids[1], client_uuid=token)])


def test_concurrent_duplicate_arrival_stores_one_entry(repo, ids, clean_pg):
    """Connection A holds an uncommitted arrival. The save of B waits on the unique
    index and fails with the translated error once A commits."""
    employee = ids[0]
    outcome: list[object] = []

    def second_writer():
        try:
            outcome.append(repo.save_all([make_attendance(employee, S.LATE)]))
        except Exception as exc:  # noqa: BLE001 - the test inspects the type
            outcome.append(exc)

    with clean_pg.connection() as first:
        first.execute("SET LOCAL lock_timeout = '10s'")
        meta_id = first.execute(
            "INSERT INTO RecordMetadata (created_by, lastly_updated_by) "
            "VALUES (%s, %s) RETURNING id", (employee, employee),
        ).fetchone()[0]
        first.execute(
            "INSERT INTO AssistanceRecord (employee_id, record_meta_id, status, "
            "occurred_at, work_date) VALUES (%s, %s, 'ON_TIME', %s, %s)",
            (employee, meta_id, NOW, NOW.date()),
        )
        thread = threading.Thread(target=second_writer)
        thread.start()
        thread.join(timeout=1.0)
        assert thread.is_alive(), "the second save must wait for the first transaction"
    thread.join(timeout=10)
    assert len(outcome) == 1 and isinstance(outcome[0], AttendanceAlreadyRecordedError)
    stored = repo.list_by_employees_on_day([employee], NOW.date())
    assert [e.status for e in stored] == [S.ON_TIME]


def test_fake_enforces_the_same_unique_rules(ids=(1, 2)):
    fake = FakeAttendanceRepository()
    token = uuid4()
    fake.save_all([make_attendance(1, client_uuid=token), make_attendance(1, S.EXITED)])
    with pytest.raises(AttendanceAlreadyRecordedError):
        fake.save_all([make_attendance(2), make_attendance(1, S.LATE)])
    with pytest.raises(AttendanceAlreadyRecordedError):
        fake.save_all([make_attendance(1, S.EXITED)])
    with pytest.raises(ClientUuidConflictError):
        fake.save_all([make_attendance(2, client_uuid=token)])
    assert [a.employee_id for a in fake.items] == [1, 1]
    assert fake.find_by_client_uuids([token])[0].status is S.ON_TIME
    assert len(fake.list_by_employees_on_day([1, 2], NOW.date())) == 2

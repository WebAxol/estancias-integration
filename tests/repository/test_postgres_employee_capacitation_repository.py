import pytest

from src.infrastructure.repository.postgres_capacitation_repository import (
    PostgresCapacitationRepository,
)
from src.infrastructure.repository.postgres_employee_capacitation_repository import (
    PostgresEmployeeCapacitationRepository,
)
from src.domain.models.employee import RecordMetadata
from src.domain.models.employee_capacitation import EmployeeCapacitation
from api.tests.fakes import NOW, make_capacitation


def make_assignment(**overrides) -> EmployeeCapacitation:
    metadata = RecordMetadata(
        created_by=10, lastly_updated_by=10, created_at=NOW, lastly_updated_at=NOW
    )
    data = dict(employee_id=11, capacitation_id=3, metadata=metadata)
    data.update(overrides)
    return EmployeeCapacitation(**data)


@pytest.fixture
def seeded(clean_pg):
    with clean_pg.connection() as conn:
        conn.execute("INSERT INTO Subsidiary (name) VALUES ('S1')")
        conn.execute(
            "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
            "SELECT uniqueId, 1, 'E1', 'e1@x.com', 'h' FROM Subsidiary WHERE uniqueId > 0"
        )
        conn.execute("TRUNCATE Capacitation RESTART IDENTITY CASCADE")
        employee = conn.execute("SELECT id FROM Employee").fetchone()[0]
    capacitation = PostgresCapacitationRepository(clean_pg).save(
        make_capacitation(id=None, metadata=_metadata(employee))
    )
    return clean_pg, employee, capacitation


def _metadata(author):
    return RecordMetadata(
        created_by=author, lastly_updated_by=author, created_at=NOW, lastly_updated_at=NOW
    )


def test_capacitation_find_by_id(seeded):
    pool, employee, capacitation = seeded
    repo = PostgresCapacitationRepository(pool)
    found = repo.find_by_id(capacitation.id)
    assert (found.id, found.name, found.metadata.created_by) == (
        capacitation.id, "Fire safety", employee,
    )
    assert repo.find_by_id(9999) is None


def test_save_and_find_pending(seeded):
    pool, employee, capacitation = seeded
    repo = PostgresEmployeeCapacitationRepository(pool)
    assert repo.find_pending(employee, capacitation.id) is None
    saved = repo.save(
        make_assignment(
            employee_id=employee,
            capacitation_id=capacitation.id,
            metadata=_metadata(employee),
        )
    )
    assert saved.id is not None and saved.metadata.id is not None
    found = repo.find_pending(employee, capacitation.id)
    assert found.id == saved.id
    assert found.is_pending and found.accredited_at is None
    assert found.metadata.created_at == NOW


def _assign(repo, employee, capacitation_id, **overrides):
    return repo.save(
        make_assignment(
            employee_id=employee,
            capacitation_id=capacitation_id,
            metadata=_metadata(employee),
            **overrides,
        )
    )


def test_second_pending_assignment_is_rejected_but_a_completed_one_allows_another(seeded):
    from src.application.errors import CapacitationAlreadyAssignedError

    pool, employee, capacitation = seeded
    repo = PostgresEmployeeCapacitationRepository(pool)
    first = _assign(repo, employee, capacitation.id)
    with pytest.raises(CapacitationAlreadyAssignedError):
        _assign(repo, employee, capacitation.id)

    assert repo.complete(first.id, NOW) is not None
    assert _assign(repo, employee, capacitation.id).id != first.id


def test_state_check_rejects_a_completed_row_without_accreditation_date(seeded):
    import psycopg

    pool, employee, capacitation = seeded
    with pytest.raises(psycopg.errors.CheckViolation) as raised:
        with pool.connection() as conn:
            meta = conn.execute(
                "INSERT INTO RecordMetadata (created_by, lastly_updated_by) "
                "VALUES (%s, %s) RETURNING id",
                (employee, employee),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO EmployeeCapacitation "
                "(employeeId, capacitationId, record_meta_id, is_pending) "
                "VALUES (%s, %s, %s, FALSE)",
                (employee, capacitation.id, meta),
            )
    assert raised.value.diag.constraint_name == "ck_employee_capacitation_state"


def test_find_by_id_and_due_at_round_trip(seeded):
    from datetime import date

    pool, employee, capacitation = seeded
    repo = PostgresEmployeeCapacitationRepository(pool)
    saved = _assign(repo, employee, capacitation.id, due_at=date(2025, 6, 1))
    found = repo.find_by_id(saved.id)
    assert found.due_at == date(2025, 6, 1) and found.is_pending
    assert repo.find_by_id(9999) is None


def test_complete_marks_the_assignment_once(seeded):
    pool, employee, capacitation = seeded
    repo = PostgresEmployeeCapacitationRepository(pool)
    saved = _assign(repo, employee, capacitation.id)

    done = repo.complete(saved.id, NOW)
    assert not done.is_pending and done.accredited_at == NOW
    assert done.metadata.lastly_updated_at == NOW
    assert repo.complete(saved.id, NOW) is None
    assert repo.complete(9999, NOW) is None


def test_list_overdue_uses_assignment_deadline_then_course_deadline(seeded):
    from datetime import date

    from src.domain.models.access import Scope
    from src.domain.models.capacitation_view import AssignmentFilter
    from src.domain.models.paging import Page

    pool, employee, _ = seeded
    courses = PostgresCapacitationRepository(pool)
    late_course = courses.save(
        make_capacitation(id=None, metadata=_metadata(employee), due_at=date(2025, 1, 1))
    )
    open_course = courses.save(
        make_capacitation(id=None, metadata=_metadata(employee), due_at=date(2025, 12, 1))
    )
    repo = PostgresEmployeeCapacitationRepository(pool)
    by_course = _assign(repo, employee, late_course.id)  # course deadline is past
    by_own = _assign(repo, employee, open_course.id, due_at=date(2025, 2, 1))
    done = _assign(repo, employee, courses.save(
        make_capacitation(id=None, metadata=_metadata(employee), due_at=date(2025, 1, 1))
    ).id)
    repo.complete(done.id, NOW)

    today = date(2025, 3, 1)
    everything = AssignmentFilter(scope=Scope(subsidiary_id=None), today=today)
    overdue = repo.list(
        AssignmentFilter(scope=Scope(subsidiary_id=None), today=today, overdue=True),
        Page(),
    )
    assert [v.assignment.id for v in overdue.items] == [by_course.id, by_own.id]
    assert overdue.total == 2 and all(v.overdue for v in overdue.items)
    assert overdue.items[0].employee_name == "E1"
    assert overdue.items[0].course_due_at == date(2025, 1, 1)

    all_rows = repo.list(everything, Page(limit=2, offset=0))
    assert all_rows.total == 3 and len(all_rows.items) == 2
    pending = repo.list(
        AssignmentFilter(scope=Scope(subsidiary_id=None), today=today, is_pending=False),
        Page(),
    )
    assert [v.assignment.id for v in pending.items] == [done.id]
    other_site = repo.list(
        AssignmentFilter(scope=Scope(subsidiary_id=9999), today=today), Page()
    )
    assert other_site.total == 0 and other_site.items == ()

    mine = repo.list_for_employee(employee, pending_only=True, today=today)
    assert [v.assignment.id for v in mine] == [by_course.id, by_own.id]
    assert len(repo.list_for_employee(employee, pending_only=False, today=today)) == 3

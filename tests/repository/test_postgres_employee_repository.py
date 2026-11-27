from datetime import date, timedelta

import pytest

from src.application.errors import EmailAlreadyRegisteredError
from src.domain.models.access import Scope
from src.domain.models.employee import Employee
from src.domain.models.employee_view import EmployeeFilter
from src.domain.models.paging import Page
from src.domain.models.role_name import RoleName
from src.infrastructure.repository.postgres_employee_repository import (
    PostgresEmployeeRepository,
)


@pytest.fixture
def repo(clean_pg):
    with clean_pg.connection() as conn:
        conn.execute(
            "INSERT INTO Subsidiary (name) VALUES ('S1'), ('S2');"
        )
        conn.execute(
            "INSERT INTO Room (subsidiary_id, name) "
            "SELECT uniqueId, 'R' FROM Subsidiary WHERE name = 'S1'"
        )
    return PostgresEmployeeRepository(clean_pg)


def new_employee(email="a@x.com", subsidiary_id=None, room_id=None) -> Employee:
    return Employee(
        subsidiary_id=subsidiary_id, role_id=1, name="A", email=email,
        password_hash="h", room_id=room_id,
    )


def subsidiary_ids(pool):
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT uniqueId FROM Subsidiary WHERE uniqueId > 0 ORDER BY uniqueId"
        ).fetchall()
    return [r[0] for r in rows]


def room_id(pool):
    with pool.connection() as conn:
        return conn.execute("SELECT uniqueId FROM Room WHERE uniqueId > 0").fetchone()[0]


def test_save_assigns_id_and_finds_by_id_and_email(repo, clean_pg):
    s1, s2 = subsidiary_ids(clean_pg)
    first = repo.save(new_employee("a@x.com", s1), None)
    second = repo.save(new_employee("b@x.com", s2), None)
    assert second.id == first.id + 1
    assert repo.find_by_id(second.id).email == "b@x.com"
    assert repo.find_by_email("a@x.com").id == first.id
    assert repo.find_by_id(9999) is None and repo.find_by_email("z@x.com") is None


def test_round_trips_every_field(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    saved = repo.save(new_employee("a@x.com", s1, room_id(clean_pg)), None)
    found = repo.find_by_id(saved.id)
    assert found == saved
    assert (found.subsidiary_id, found.role_id, found.name, found.password_hash) == (
        s1, 1, "A", "h",
    )


def test_missing_room_is_none_and_stored_as_null_room(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    saved = repo.save(new_employee("a@x.com", s1), None)
    assert saved.room_id is None and repo.find_by_id(saved.id).room_id is None
    with clean_pg.connection() as conn:
        assert conn.execute("SELECT room_id FROM Employee").fetchone()[0] == 0


def test_list_by_subsidiary_filters(repo, clean_pg):
    s1, s2 = subsidiary_ids(clean_pg)
    repo.save(new_employee("a@x.com", s1), None)
    repo.save(new_employee("b@x.com", s2), None)
    assert [e.email for e in repo.list_by_subsidiary(s2)] == ["b@x.com"]
    assert repo.list_by_subsidiary(9999) == []


def test_list_by_room_filters(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    room = room_id(clean_pg)
    repo.save(new_employee("a@x.com", s1, room), None)
    repo.save(new_employee("b@x.com", s1), None)
    assert [e.email for e in repo.list_by_room(room)] == ["a@x.com"]
    assert repo.list_by_room(9999) == []


def test_duplicate_email_raises_email_already_registered(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    repo.save(new_employee("a@x.com", s1), None)
    with pytest.raises(EmailAlreadyRegisteredError):
        repo.save(new_employee("a@x.com", s1), None)


def test_session_state_hire_row_only(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    rid = room_id(clean_pg)
    saved = repo.save(new_employee("a@x.com", s1, rid), None)
    state = repo.find_session_state(saved.id)
    assert (state.room_id, state.subsidiary_id, state.terminated_at) == (rid, s1, None)
    assert state.last_change_at is not None


def test_session_state_none_room_and_unknown_id(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    saved = repo.save(new_employee("a@x.com", s1), None)
    assert repo.find_session_state(saved.id).room_id is None
    assert repo.find_session_state(9999) is None


def test_session_state_after_transfer_and_termination(repo, clean_pg):
    s1, s2 = subsidiary_ids(clean_pg)
    saved = repo.save(new_employee("a@x.com", s1), None)
    hired = repo.find_session_state(saved.id).last_change_at
    with clean_pg.connection() as conn:
        conn.execute(
            "UPDATE EmployeeChange SET changed_at = changed_at - interval '1 day' "
            "WHERE employee_id = %s",
            (saved.id,),
        )
        conn.execute(
            "UPDATE Employee SET subsidiary_id = %s WHERE id = %s", (s2, saved.id)
        )
    moved = repo.find_session_state(saved.id)
    assert moved.subsidiary_id == s2 and moved.terminated_at is None
    assert moved.last_change_at > hired - timedelta(days=1)
    with clean_pg.connection() as conn:
        conn.execute(
            "UPDATE Employee SET terminated_at = CURRENT_DATE WHERE id = %s",
            (saved.id,),
        )
    ended = repo.find_session_state(saved.id)
    assert ended.terminated_at is not None
    assert ended.last_change_at >= moved.last_change_at


def test_update_password_replaces_hash(repo):
    saved = repo.save(new_employee(subsidiary_id=subsidiary_ids(repo._pool)[0]), None)
    repo.update_password(saved.id, "new-hash")
    assert repo.find_by_id(saved.id).password_hash == "new-hash"


def _scope_all():
    return Scope(subsidiary_id=None)


def _seed_many(repo, pool):
    s1, s2 = subsidiary_ids(pool)
    room = room_id(pool)
    a = repo.save(new_employee("a@x.com", s1, room), None)
    b = repo.save(new_employee("b@x.com", s1), None)
    c = repo.save(new_employee("c@x.com", s2), None)
    return s1, s2, room, a, b, c


def test_find_view_joins_role_personnel_type_and_alias(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    manager = new_employee("m@x.com", s1)
    manager.role_id = 3
    manager.personnel_type_id = 1
    saved = repo.save(manager, None)
    view = repo.find_view(saved.id)
    assert view.role_name == RoleName.MANAGER and view.role_alias is None
    assert view.personnel_type_name == "Coordinator"
    assert view.employee.hired_at is not None
    with clean_pg.connection() as conn:
        meta = conn.execute(
            "INSERT INTO RecordMetadata (created_by, lastly_updated_by) "
            "VALUES (%s, %s) RETURNING id", (saved.id, saved.id),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO RoleAlias (subsidiary_id, role_id, alias, record_meta_id) "
            "VALUES (%s, 3, 'Directora de plantel', %s)", (s1, meta),
        )
    assert repo.find_view(saved.id).role_alias == "Directora de plantel"
    assert repo.find_view(9999) is None


def test_list_by_ids_returns_existing_in_id_order(repo, clean_pg):
    _, _, _, a, b, c = _seed_many(repo, clean_pg)
    assert [e.id for e in repo.list_by_ids([c.id, a.id, 9999])] == [a.id, c.id]
    assert repo.list_by_ids([]) == []


def test_list_views_scope_filters_order_and_total(repo, clean_pg):
    s1, s2, room, a, b, c = _seed_many(repo, clean_pg)
    page = Page(limit=10)
    everyone = repo.list_views(EmployeeFilter(scope=_scope_all()), page)
    assert [v.employee.id for v in everyone.items] == [a.id, b.id, c.id]
    assert everyone.total == 3
    site = repo.list_views(EmployeeFilter(scope=Scope(subsidiary_id=s1)), page)
    assert [v.employee.id for v in site.items] == [a.id, b.id]
    in_room = repo.list_views(EmployeeFilter(scope=_scope_all(), room_id=room), page)
    assert [v.employee.id for v in in_room.items] == [a.id]
    room_scope = repo.list_views(EmployeeFilter(scope=Scope(s1, room_id=room)), page)
    assert [v.employee.id for v in room_scope.items] == [a.id]
    by_role = repo.list_views(EmployeeFilter(scope=_scope_all(), role_id=9), page)
    assert by_role.items == () and by_role.total == 0
    by_type = repo.list_views(
        EmployeeFilter(scope=_scope_all(), personnel_type_id=0), page
    )
    assert by_type.total == 3


def test_list_views_active_filter(repo, clean_pg):
    _, _, _, a, b, c = _seed_many(repo, clean_pg)
    repo.update(b.terminate(date.today(), "left"), None)
    page = Page(limit=10)

    def ids(active):
        result = repo.list_views(EmployeeFilter(scope=_scope_all(), active=active), page)
        return [v.employee.id for v in result.items]

    assert ids(True) == [a.id, c.id]
    assert ids(False) == [b.id]
    assert ids(None) == [a.id, b.id, c.id]


def test_list_views_pages_keep_total_and_concatenate(repo, clean_pg):
    _seed_many(repo, clean_pg)
    flt = EmployeeFilter(scope=_scope_all())
    first = repo.list_views(flt, Page(limit=2, offset=0))
    second = repo.list_views(flt, Page(limit=2, offset=2))
    beyond = repo.list_views(flt, Page(limit=2, offset=10))
    assert (first.total, second.total, beyond.total) == (3, 3, 3)
    assert len(first.items) == 2 and len(second.items) == 1 and beyond.items == ()
    full = repo.list_views(flt, Page(limit=10))
    assert first.items + second.items == full.items


def test_update_writes_fields_and_clears_room(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    saved = repo.save(new_employee("a@x.com", s1, room_id(clean_pg)), None)
    saved.name = "Renamed"
    saved.personnel_type_id = 2
    saved.assign_room(None)
    repo.update(saved, None)
    found = repo.find_by_id(saved.id)
    assert (found.name, found.personnel_type_id, found.room_id) == ("Renamed", 2, None)


def _changes(pool, employee_id):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT change_type::text, changed_by FROM EmployeeChange "
            "WHERE employee_id = %s ORDER BY id", (employee_id,),
        ).fetchall()


def test_writes_record_actor_in_employee_change(repo, clean_pg):
    s1, s2 = subsidiary_ids(clean_pg)
    admin = repo.save(new_employee("admin@x.com", s1), None)
    hired = repo.save(new_employee("a@x.com", s1), admin.id)
    hired.subsidiary_id = s2
    repo.update(hired, admin.id)
    repo.update(hired.terminate(date.today(), "left"), admin.id)
    assert _changes(clean_pg, admin.id) == [("HIRED", None)]
    assert _changes(clean_pg, hired.id) == [
        ("HIRED", admin.id), ("TRANSFERRED", admin.id), ("TERMINATED", admin.id),
    ]


def test_actor_does_not_leak_to_next_transaction(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    admin = repo.save(new_employee("admin@x.com", s1), None)
    repo.save(new_employee("a@x.com", s1), admin.id)
    other = repo.save(new_employee("b@x.com", s1), None)
    assert _changes(clean_pg, other.id) == [("HIRED", None)]


def test_save_and_update_translate_integrity_errors(repo, clean_pg):
    from src.application.errors import IntegrityRuleError
    s1, s2 = subsidiary_ids(clean_pg)
    saved = repo.save(new_employee("a@x.com", s1), None)
    saved.room_id = room_id(clean_pg)  # room belongs to s1
    saved.subsidiary_id = s2
    with pytest.raises(IntegrityRuleError):
        repo.update(saved, None)
    with pytest.raises(EmailAlreadyRegisteredError):
        repo.save(new_employee("A@x.com", s1), None)
def test_find_by_email_ignores_case(repo, clean_pg):
    s1, _ = subsidiary_ids(clean_pg)
    saved = repo.save(new_employee("Mixed@X.com", s1), None)
    assert repo.find_by_email("mixed@x.COM").id == saved.id

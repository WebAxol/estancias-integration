import pytest
from src.application.errors import RoomNameTakenError
from src.domain.models.access import Scope
from src.domain.models.subsidiary import Room

from src.infrastructure.repository.postgres_subsidiary_repository import (
    PostgresSubsidiaryRepository,
)


@pytest.fixture
def repo(pg_pool):
    return PostgresSubsidiaryRepository(pg_pool)


def test_find_by_id_and_find_room(repo, pg_pool):
    with pg_pool.connection() as conn:
        site = conn.execute(
            "INSERT INTO Subsidiary (name) VALUES ('S-find') RETURNING uniqueId"
        ).fetchone()[0]
        room = conn.execute(
            "INSERT INTO Room (subsidiary_id, name, required_personal) "
            "VALUES (%s, 'R-find', 3) RETURNING uniqueId",
            (site,),
        ).fetchone()[0]
    found = repo.find_by_id(site)
    assert (found.id, found.name) == (site, "S-find") and found.timezone
    found_room = repo.find_room(room)
    assert (found_room.subsidiary_id, found_room.required_personal) == (site, 3)
    assert repo.find_by_id(99999) is None and repo.find_room(99999) is None


def _site(conn, name):
    return conn.execute(
        "INSERT INTO Subsidiary (name) VALUES (%s) RETURNING uniqueId", (name,)
    ).fetchone()[0]


def test_list_excludes_site_zero_and_honours_scope(repo, clean_pg):
    with clean_pg.connection() as conn:
        a, b = _site(conn, "A"), _site(conn, "B")
    assert [s.id for s in repo.list(Scope(subsidiary_id=None))] == [a, b]
    assert [s.id for s in repo.list(Scope(subsidiary_id=b))] == [b]
    assert repo.list(Scope(subsidiary_id=0)) == []


def test_save_update_room_and_unique_name(repo, clean_pg):
    with clean_pg.connection() as conn:
        a, b = _site(conn, "A"), _site(conn, "B")
    saved = repo.save_room(Room(0, a, "Sala", 2), actor_id=None)
    assert saved.id > 0 and (saved.subsidiary_id, saved.name, saved.required_personal) == (a, "Sala", 2)
    other = repo.save_room(Room(0, a, "Otra", 1), actor_id=None)
    repo.save_room(Room(0, b, "Sala", 1), actor_id=None)  # same name, other site: fine
    with pytest.raises(RoomNameTakenError):
        repo.save_room(Room(0, a, "Sala", 5), actor_id=None)
    repo.update_room(Room(saved.id, a, "Sala 2", 4), actor_id=None)
    assert repo.find_room(saved.id).name == "Sala 2"
    assert repo.find_room(saved.id).required_personal == 4
    with pytest.raises(RoomNameTakenError):
        repo.update_room(Room(other.id, a, "Sala 2", 1), actor_id=None)


def test_list_rooms_counts_active_employees_and_scopes(repo, clean_pg):
    with clean_pg.connection() as conn:
        a, b = _site(conn, "A"), _site(conn, "B")
    room_a = repo.save_room(Room(0, a, "RA", 1), None)
    room_b = repo.save_room(Room(0, b, "RB", 1), None)
    with clean_pg.connection() as conn:
        for i, term in enumerate((None, None, "2024-01-01")):
            conn.execute(
                "INSERT INTO Employee (subsidiary_id, room_id, roleId, name, email, password_hash,"
                " hired_at, terminated_at) VALUES (%s, %s, 4, 'E', %s, 'x', '2023-01-01', %s)",
                (a, room_a.id, f"e{i}@x.com", term),
            )
    views = repo.list_rooms(Scope(subsidiary_id=None))
    assert [(v.room.id, v.assigned_count) for v in views] == [(room_a.id, 2), (room_b.id, 0)]
    assert [v.room.id for v in repo.list_rooms(Scope(subsidiary_id=b))] == [room_b.id]
    assert [v.room.id for v in repo.list_rooms(Scope(subsidiary_id=a, room_id=room_a.id))] == [room_a.id]

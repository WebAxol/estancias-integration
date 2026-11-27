from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.application.errors import ClientUuidConflictError, IntegrityRuleError
from src.domain.models.access import Scope
from src.domain.models.incident import Incident
from src.domain.models.incident_type import IncidentType
from src.domain.models.incident_view import IncidentFilter
from src.domain.models.paging import Page
from src.infrastructure.repository.postgres_incident_query import PostgresIncidentQuery
from src.infrastructure.repository.postgres_incident_repository import (
    PostgresIncidentRepository,
)
from src.infrastructure.repository.postgres_incident_type_repository import (
    PostgresIncidentTypeRepository,
)
from api.tests.fakes import (
    NOW,
    FakeIncidentRepository,
    FakeIncidentTypeRepository,
    make_incident,
)

@pytest.fixture
def world(clean_pg):
    """Site A with coordinator ca and employees e1, e2. Site B with coordinator cb and e3."""
    # clean_pg truncates RecordMetadata and Employee with CASCADE, which empties Incident.
    pg_pool = clean_pg
    ids = {}
    with pg_pool.connection() as conn:
        for key, name in (("a", "Site A"), ("b", "Site B")):
            ids[key] = conn.execute(
                "INSERT INTO Subsidiary (name) VALUES (%s) RETURNING uniqueId", (name,)
            ).fetchone()[0]
        for key, site, name in (
            ("ca", "a", "Coord A"), ("e1", "a", "Ann"), ("e2", "a", "Bob"),
            ("cb", "b", "Coord B"), ("e3", "b", "Cy"),
        ):
            ids[key] = conn.execute(
                "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
                "VALUES (%s, 1, %s, %s, 'h') RETURNING id",
                (ids[site], name, f"{key}@x.com"),
            ).fetchone()[0]
        ids["type"] = conn.execute(
            "SELECT id FROM IncidentType WHERE name = 'Safety'"
        ).fetchone()[0]
        ids["other"] = conn.execute(
            "SELECT id FROM IncidentType WHERE name = 'Conduct'"
        ).fetchone()[0]
    return ids


def make(world, author="ca", employees=("e1",), type_key="type", at=NOW, **overrides):
    base = make_incident(
        id=None,
        created_by=world[author],
        employee_ids=[world[e] for e in employees],
        incident_type_id=world[type_key],
    )
    return replace(base, occurred_at=at, **overrides)


@pytest.fixture(params=["fake", "postgres"])
def backend(request):
    """(repository, ids): the fake with made-up ids, or the adapter with a real world."""
    if request.param == "fake":
        keys = ("a", "b", "ca", "cb", "e1", "e2", "e3", "type", "other")
        return FakeIncidentRepository(), {k: 10 + n for n, k in enumerate(keys)}
    pool = request.getfixturevalue("pg_pool")
    return PostgresIncidentRepository(pool), request.getfixturevalue("world")


def test_save_round_trips_by_client_uuid(backend):
    repo, world = backend
    key = uuid4()
    incident = make(world, employees=("e2", "e1"), description="Spill", client_uuid=key)
    saved = repo.save(incident)
    assert saved.id is not None
    found = repo.find_by_client_uuid(key)
    assert found == saved
    assert found.employee_ids == (world["e2"], world["e1"])
    assert found.description == "Spill" and found.occurred_at == NOW
    assert repo.find_by_client_uuid(uuid4()) is None


def test_duplicate_client_uuid_is_translated(backend):
    repo, world = backend
    key = uuid4()
    repo.save(make(world, client_uuid=key))
    with pytest.raises(ClientUuidConflictError):
        repo.save(make(world, client_uuid=key))


def test_postgres_fills_site_and_time_and_keeps_explicit_site(pg_pool, world):
    repo = PostgresIncidentRepository(pg_pool)
    implicit = repo.save(replace(make(world), occurred_at=None))
    assert implicit.subsidiary_id == world["a"]
    assert implicit.occurred_at is not None and implicit.occurred_at.tzinfo is not None
    explicit = repo.save(make(world, subsidiary_id=world["b"], employees=("e3",)))
    assert explicit.subsidiary_id == world["b"]


def test_postgres_save_is_atomic(pg_pool, world):
    repo = PostgresIncidentRepository(pg_pool)
    with pytest.raises(IntegrityRuleError):
        repo.save(
            replace(make(world), employee_ids=(world["e1"], 999999))  # unknown employee
        )
    with pg_pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM Incident").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM RecordMetadata").fetchone()[0] == 0


def test_incident_type_repository(pg_pool, world):
    types = PostgresIncidentTypeRepository(pg_pool)
    found = types.find_by_id(world["type"])
    assert isinstance(found, IncidentType) and found.name == "Safety"
    assert found.description
    assert types.find_by_id(999999) is None
    assert FakeIncidentTypeRepository(found).find_by_id(found.id) == found


def test_query_filters_orders_and_counts(pg_pool, world):
    repo = PostgresIncidentRepository(pg_pool)
    query = PostgresIncidentQuery(pg_pool)
    day = timedelta(days=1)
    old = repo.save(make(world, at=NOW - 3 * day, employees=("e1", "e2")))
    mid = repo.save(make(world, at=NOW - day, type_key="other", employees=("e2",)))
    new = repo.save(make(world, at=NOW, description="Latest"))
    other_site = repo.save(make(world, author="cb", employees=("e3",), at=NOW))

    def ids(**kw):
        scope = kw.pop("scope", Scope(subsidiary_id=world["a"]))
        result = query.list(IncidentFilter(scope=scope, **kw), Page())
        return [v.incident.id for v in result.items], result.total

    assert ids() == ([new.id, mid.id, old.id], 3)
    assert ids(scope=Scope(subsidiary_id=None))[1] == 4
    assert ids(scope=Scope(subsidiary_id=None), subsidiary_id=world["b"]) == (
        [other_site.id], 1)
    assert ids(employee_id=world["e2"]) == ([mid.id, old.id], 2)
    assert ids(incident_type_id=world["other"]) == ([mid.id], 1)
    assert ids(registered_by=world["cb"]) == ([], 0)
    assert ids(date_from=(NOW - day).date(), date_to=(NOW - day).date()) == ([mid.id], 1)

    first = query.list(IncidentFilter(scope=Scope(subsidiary_id=world["a"])), Page(limit=1))
    assert first.total == 3 and [v.incident.id for v in first.items] == [new.id]
    beyond = query.list(
        IncidentFilter(scope=Scope(subsidiary_id=world["a"])), Page(limit=5, offset=10)
    )
    assert beyond.items == () and beyond.total == 3


def test_query_returns_names_and_all_employees(pg_pool, world):
    repo = PostgresIncidentRepository(pg_pool)
    saved = repo.save(make(world, employees=("e2", "e1"), description="Spill"))
    view = PostgresIncidentQuery(pg_pool).list(
        IncidentFilter(scope=Scope(subsidiary_id=None)), Page()
    ).items[0]
    assert view.incident == saved
    assert view.incident_type_name == "Safety"
    assert view.registered_by_name == "Coord A"


def test_query_date_filter_uses_the_site_time_zone(pg_pool, world):
    with pg_pool.connection() as conn:
        conn.execute(
            "UPDATE Subsidiary SET timezone = 'America/Mexico_City' WHERE uniqueId = %s",
            (world["a"],),
        )
    repo = PostgresIncidentRepository(pg_pool)
    # 03:00 UTC on the 11th is 21:00 on the 10th in Mexico City (UTC-6).
    saved = repo.save(make(world, at=datetime(2025, 3, 11, 3, 0, tzinfo=timezone.utc)))
    query = PostgresIncidentQuery(pg_pool)
    scope = Scope(subsidiary_id=world["a"])
    on_tenth = IncidentFilter(scope=scope, date_from=date(2025, 3, 10), date_to=date(2025, 3, 10))
    on_eleventh = replace(on_tenth, date_from=date(2025, 3, 11), date_to=date(2025, 3, 11))
    assert [v.incident.id for v in query.list(on_tenth, Page()).items] == [saved.id]
    assert query.list(on_eleventh, Page()).items == ()

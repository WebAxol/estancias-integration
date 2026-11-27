from dataclasses import replace
from datetime import timedelta
import pytest
from src.domain.models.access import Scope
from src.domain.models.paging import Page
from src.infrastructure.repository.postgres_coordinator_query import (
    PostgresCoordinatorQuery,
)
from src.infrastructure.repository.postgres_incident_repository import (
    PostgresIncidentRepository,
)
from api.tests.fakes import NOW, make_incident
@pytest.fixture
def world(clean_pg):
    """Site A: coordinators Zoe and Abe, manager Max, employee Ann.
    Site B: coordinator Cy. Zoe has an alias in site A. Ned is a terminated coordinator."""
    ids = {}
    with clean_pg.connection() as conn:
        for key, name in (("a", "Site A"), ("b", "Site B")):
            ids[key] = conn.execute(
                "INSERT INTO Subsidiary (name) VALUES (%s) RETURNING uniqueId", (name,)
            ).fetchone()[0]
        roles = {
            r: i for i, r in conn.execute("SELECT id, name FROM Role").fetchall()
        }
        for key, site, role, name in (
            ("zoe", "a", "Coordinator", "Zoe"), ("abe", "a", "Coordinator", "Abe"),
            ("max", "a", "Manager", "Max"), ("ann", "a", "Employee", "Ann"),
            ("cy", "b", "Coordinator", "Cy"), ("ned", "a", "Coordinator", "Ned"),
        ):
            ids[key] = conn.execute(
                "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
                "VALUES (%s, %s, %s, %s, 'h') RETURNING id",
                (ids[site], roles[role], name, f"{key}@x.com"),
            ).fetchone()[0]
        conn.execute(
            "UPDATE Employee SET terminated_at = CURRENT_DATE, termination_reason = 'left' "
            "WHERE id = %s", (ids["ned"],),
        )
        meta = conn.execute(
            "INSERT INTO RecordMetadata (created_by, lastly_updated_by) VALUES (%s, %s) "
            "RETURNING id", (ids["max"], ids["max"]),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO RoleAlias (subsidiary_id, role_id, alias, record_meta_id) "
            "VALUES (%s, %s, 'Lead', %s)", (ids["a"], roles["Coordinator"], meta),
        )
        ids["type"] = conn.execute(
            "SELECT id FROM IncidentType WHERE name = 'Safety'"
        ).fetchone()[0]
    return ids
def add_incident(pool, world, author, at, employee="ann"):
    base = make_incident(
        id=None, created_by=world[author], employee_ids=[world[employee]],
        incident_type_id=world["type"],
    )
    return PostgresIncidentRepository(pool).save(replace(base, occurred_at=at))
def test_lists_active_coordinators_with_counts_and_alias(pg_pool, world):
    add_incident(pg_pool, world, "zoe", NOW - timedelta(days=2))
    add_incident(pg_pool, world, "zoe", NOW)
    add_incident(pg_pool, world, "cy", NOW, employee="ann")
    result = PostgresCoordinatorQuery(pg_pool).list(Scope(subsidiary_id=None), Page())
    by_name = {s.employee.employee.name: s for s in result.items}
    assert set(by_name) == {"Abe", "Cy", "Zoe"}  # no manager, employee or terminated one
    assert result.total == 3
    assert [s.employee.employee.name for s in result.items] == ["Abe", "Cy", "Zoe"]
    assert by_name["Zoe"].incident_count == 2 and by_name["Zoe"].last_incident_at == NOW
    assert by_name["Zoe"].employee.role_alias == "Lead"
    assert by_name["Abe"].incident_count == 0 and by_name["Abe"].last_incident_at is None
    assert by_name["Cy"].incident_count == 1 and by_name["Cy"].employee.role_alias is None
def test_scope_and_page(pg_pool, world):
    query = PostgresCoordinatorQuery(pg_pool)
    own = query.list(Scope(subsidiary_id=world["a"]), Page())
    assert [s.employee.employee.name for s in own.items] == ["Abe", "Zoe"] and own.total == 2
    first = query.list(Scope(subsidiary_id=world["a"]), Page(limit=1))
    assert [s.employee.employee.name for s in first.items] == ["Abe"] and first.total == 2
    beyond = query.list(Scope(subsidiary_id=world["a"]), Page(limit=5, offset=10))
    assert beyond.items == () and beyond.total == 2
    assert query.list(Scope(subsidiary_id=999999), Page()).total == 0

import pytest
from src.domain.models.catalog import CatalogKind
from src.infrastructure.repository.postgres_catalog_query import PostgresCatalogQuery
@pytest.fixture
def query(clean_pg):
    return PostgresCatalogQuery(clean_pg)
def test_roles_are_the_four_assignable_ones(query):
    assert [r.name for r in query.list(CatalogKind.ROLES)] == [
        "Employee", "Coordinator", "Manager", "Director"
    ]
def test_personnel_types_include_default_type(query):
    items = query.list(CatalogKind.PERSONNEL_TYPES)
    assert items[0].id == 0 and len(items) >= 2
def test_incident_types_are_listed_by_id(query):
    items = query.list(CatalogKind.INCIDENT_TYPES)
    assert items and [i.id for i in items] == sorted(i.id for i in items)


def test_schedules_kind_is_not_supported(query):
    with pytest.raises(ValueError):
        query.list(CatalogKind.SCHEDULES)

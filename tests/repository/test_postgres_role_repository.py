import pytest

from src.domain.models.role_name import RoleName
from src.infrastructure.repository.postgres_role_repository import PostgresRoleRepository
from api.tests.fakes import DEFAULT_PERMISSIONS, ROLE_IDS


@pytest.fixture
def repo(pg_pool):
    return PostgresRoleRepository(pg_pool)


@pytest.mark.parametrize("role_name", list(RoleName))
def test_find_by_id_returns_each_role(repo, role_name):
    role = repo.find_by_id(ROLE_IDS[role_name])

    assert role is not None
    assert role.id == ROLE_IDS[role_name]
    assert role.name is role_name


@pytest.mark.parametrize("role_id", [0, 999])
def test_find_by_id_returns_none_for_null_or_missing_role(repo, role_id):
    assert repo.find_by_id(role_id) is None


@pytest.mark.parametrize("role_name", list(RoleName))
def test_permissions_match_migrations_004_012_and_014(repo, role_name):
    """Expected sets are section 3.1 of the requirements (tests/fakes.py)."""
    assert repo.permissions_for(ROLE_IDS[role_name]) == DEFAULT_PERMISSIONS[role_name]


def test_permissions_for_null_or_missing_role_is_empty(repo):
    assert repo.permissions_for(0) == frozenset()
    assert repo.permissions_for(999) == frozenset()

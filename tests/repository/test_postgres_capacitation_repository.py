import pytest

from src.infrastructure.repository.postgres_capacitation_repository import (
    PostgresCapacitationRepository,
)
from src.domain.models.capacitation import Capacitation
from src.domain.models.employee import RecordMetadata
from api.tests.fakes import NOW


def make_capacitation(name="Fire safety") -> Capacitation:
    meta = RecordMetadata(
        created_by=10, lastly_updated_by=10, created_at=NOW, lastly_updated_at=NOW
    )
    return Capacitation(name=name, description="Annual course", metadata=meta)


@pytest.fixture
def repo(clean_pg):
    with clean_pg.connection() as conn:
        conn.execute("INSERT INTO Subsidiary (name) VALUES ('S1')")
        conn.execute(
            "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
            "SELECT uniqueId, 1, 'E1', 'e1@x.com', 'h' FROM Subsidiary WHERE uniqueId > 0"
        )
        conn.execute("TRUNCATE Capacitation RESTART IDENTITY CASCADE")
    return PostgresCapacitationRepository(clean_pg)


def test_save_persists_capacitation_and_metadata(repo, clean_pg):
    with clean_pg.connection() as conn:
        author = conn.execute("SELECT id FROM Employee").fetchone()[0]
    entry = make_capacitation()
    entry = type(entry)(
        name=entry.name,
        description=entry.description,
        metadata=type(entry.metadata)(
            created_by=author,
            lastly_updated_by=author,
            created_at=entry.metadata.created_at,
            lastly_updated_at=entry.metadata.lastly_updated_at,
        ),
    )

    saved = repo.save(entry)

    assert saved.id is not None and saved.metadata.id is not None
    with clean_pg.connection() as conn:
        row = conn.execute(
            "SELECT c.name, c.description, m.created_by FROM Capacitation c "
            "JOIN RecordMetadata m ON m.id = c.record_meta_id WHERE c.id = %s",
            (saved.id,),
        ).fetchone()
    assert row == ("Fire safety", "Annual course", author)


def _new(repo, author, **overrides):
    from dataclasses import replace

    entry = make_capacitation(**{k: v for k, v in overrides.items() if k == "name"})
    meta = replace(entry.metadata, created_by=author, lastly_updated_by=author)
    fields = {k: v for k, v in overrides.items() if k != "name"}
    return repo.save(replace(entry, metadata=meta, **fields))


def test_save_stores_dates_and_fills_the_creators_site(repo, clean_pg):
    from datetime import date

    with clean_pg.connection() as conn:
        author, site = conn.execute("SELECT id, subsidiary_id FROM Employee").fetchone()
    saved = _new(repo, author, starts_at=date(2025, 1, 1), due_at=date(2025, 2, 1))
    found = repo.find_by_id(saved.id)
    assert saved.subsidiary_id == site == found.subsidiary_id
    assert (found.starts_at, found.due_at) == (date(2025, 1, 1), date(2025, 2, 1))


def test_list_filters_by_scope_and_joins_the_creator_name(repo, clean_pg):
    from src.domain.models.access import Scope

    with clean_pg.connection() as conn:
        author, site = conn.execute("SELECT id, subsidiary_id FROM Employee").fetchone()
    local = _new(repo, author, name="Local")
    foundation = _new(repo, author, name="Foundation", subsidiary_id=0)

    everything = repo.list(Scope(subsidiary_id=None))
    assert [v.capacitation.id for v in everything] == [local.id, foundation.id]
    assert everything[0].created_by_name == "E1"

    site_only = repo.list(Scope(subsidiary_id=site))
    assert [v.capacitation.id for v in site_only] == [local.id]
    with_foundation = repo.list(Scope(subsidiary_id=site, include_foundation=True))
    assert [v.capacitation.id for v in with_foundation] == [local.id, foundation.id]
    assert repo.list(Scope(subsidiary_id=9999)) == []
